import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useState } from 'react'

import { PORTFOLIO_SUMMARY_QUERY_KEY } from '../../hooks/usePortfolioSummary'
import { getBotStatus, getLiquidation, liquidateAll } from '../../services/api'
import type {
  LiquidationOperation,
  LiquidationOperationItem,
  LiquidationOperationStatus,
} from '../../services/api'

type ActionType = 'liquidate' | null
type FeedbackTone = 'success' | 'progress' | 'warning' | 'error'

interface LiquidationFeedback {
  tone: FeedbackTone
  message: string
}

const LIQUIDATION_CONFIRMATION = 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL'
const LIQUIDATION_OPERATION_KEY_STORAGE = 'ai-trade-manager-liquidation-operation-key'
const LIQUIDATION_OPERATION_STORAGE = 'ai-trade-manager-liquidation-operation'
const TERMINAL_LIQUIDATION_STATUSES = new Set<LiquidationOperationStatus>([
  'COMPLETED',
  'PARTIAL',
  'FAILED',
  'NO_ASSETS',
])

const FEEDBACK_TONE_CLASS: Record<FeedbackTone, string> = {
  success: 'text-status-success',
  progress: 'text-brand-bright',
  warning: 'text-warning',
  error: 'text-status-danger',
}

const PHASE_LABELS: Record<string, string> = {
  BLOCKING: '신규 주문 차단',
  DISCOVERING_ORDERS: '미체결 주문 확인',
  CANCELING_ORDERS: '미체결 주문 취소',
  RECONCILING_CANCELED_ORDERS: '취소 주문 체결 원장 반영',
  SNAPSHOTTING_TARGETS: '청산 대상 잔고 확정',
  SUBMITTING: '청산 주문 제출',
  WAITING_FILLS: '체결 및 원장 반영 대기',
  VERIFYING: '최종 잔고 검증',
  TERMINAL: '종결',
}

const RESULT_LABELS: Record<string, string> = {
  LIQUIDATED: '청산 완료',
  DUST_REMAINING: '최소 주문액 미만 잔여',
  LOCKED_REMAINING: '잠긴 자산 잔여',
  UNSUPPORTED_MARKET: 'KRW 마켓 미지원',
  ORDER_FAILED: '주문 실패',
  VERIFY_FAILED: '최종 검증 실패',
  LEDGER_MISMATCH: '거래소 잔고와 원장 불일치',
}

function getStoredLiquidationKey(): string | null {
  if (typeof window === 'undefined') {
    return null
  }

  const operationKey = window.sessionStorage.getItem(LIQUIDATION_OPERATION_KEY_STORAGE)?.trim()
  return operationKey || null
}

function getStoredLiquidationOperation(): LiquidationOperation | null {
  if (typeof window === 'undefined') {
    return null
  }

  const rawOperation = window.sessionStorage.getItem(LIQUIDATION_OPERATION_STORAGE)
  if (!rawOperation) {
    return null
  }

  try {
    const operation: unknown = JSON.parse(rawOperation)
    if (
      operation &&
      typeof operation === 'object' &&
      'id' in operation &&
      typeof operation.id === 'number' &&
      'idempotency_key' in operation &&
      typeof operation.idempotency_key === 'string' &&
      'status' in operation &&
      typeof operation.status === 'string' &&
      'items' in operation &&
      Array.isArray(operation.items)
    ) {
      return operation as LiquidationOperation
    }
  } catch {
    window.sessionStorage.removeItem(LIQUIDATION_OPERATION_STORAGE)
  }
  return null
}

function getStoredLiquidationState(): {
  operationKey: string | null
  operation: LiquidationOperation | null
} {
  const operationKey = getStoredLiquidationKey()
  const operation = getStoredLiquidationOperation()
  if (operation && operation.idempotency_key !== operationKey) {
    window.sessionStorage.removeItem(LIQUIDATION_OPERATION_STORAGE)
    return { operationKey, operation: null }
  }
  return { operationKey, operation }
}

function storeLiquidationKey(operationKey: string): void {
  window.sessionStorage.setItem(LIQUIDATION_OPERATION_KEY_STORAGE, operationKey)
}

function storeLiquidationOperation(operation: LiquidationOperation): void {
  window.sessionStorage.setItem(LIQUIDATION_OPERATION_STORAGE, JSON.stringify(operation))
}

function clearStoredLiquidation(): void {
  window.sessionStorage.removeItem(LIQUIDATION_OPERATION_KEY_STORAGE)
  window.sessionStorage.removeItem(LIQUIDATION_OPERATION_STORAGE)
}

function isTerminalLiquidationStatus(status: LiquidationOperationStatus): boolean {
  return TERMINAL_LIQUIDATION_STATUSES.has(status)
}

function phaseLabel(operation: LiquidationOperation): string {
  const phase = operation.phase?.trim().toUpperCase()
  return phase ? (PHASE_LABELS[phase] ?? phase) : '상태 확인'
}

function summarizeFailedItems(items: LiquidationOperationItem[]): string {
  const failedItems = items.filter((item) => {
    const submissionStatus = item.submission_status?.trim().toUpperCase()
    const resultCode = item.result_code?.trim().toUpperCase()
    return Boolean(item.error_code || (resultCode && resultCode !== 'LIQUIDATED')) || submissionStatus === 'REJECTED'
  })

  if (failedItems.length === 0) {
    return ''
  }

  const visibleItems = failedItems.slice(0, 3).map((item) => {
    const result = item.result_code?.trim() || item.error_code?.trim()
    const resultLabel = result ? (RESULT_LABELS[result] ?? result) : null
    return resultLabel ? `${item.market || item.currency} (${resultLabel})` : item.market
  })
  const remainingCount = failedItems.length - visibleItems.length
  const remainingLabel = remainingCount > 0 ? ` 외 ${remainingCount}건` : ''
  return ` 확인 필요 항목: ${visibleItems.join(', ')}${remainingLabel}`
}

function resolveLiquidationFeedback(operation: LiquidationOperation): LiquidationFeedback {
  const operationLabel = `청산 작업 #${operation.id}`
  const verificationStatus = operation.verification_status?.trim().toUpperCase()

  if (operation.status === 'PREPARING' || operation.status === 'IN_PROGRESS') {
    return {
      tone: 'progress',
      message: `${operationLabel}: ${phaseLabel(operation)} 단계가 진행 중입니다. 미확정 상태를 성공으로 간주하지 않습니다.`,
    }
  }

  if (operation.status === 'COMPLETED' && verificationStatus === 'VERIFIED') {
    return {
      tone: 'success',
      message: `${operationLabel}이 거래소 잔고와 내부 원장 검증까지 완료되었습니다.`,
    }
  }

  if (operation.status === 'COMPLETED') {
    return {
      tone: 'warning',
      message: `${operationLabel}은 완료 기록이지만 최종 검증 증거가 없습니다. 성공으로 표시하지 않습니다.`,
    }
  }

  if (operation.status === 'NO_ASSETS') {
    return {
      tone: 'warning',
      message:
        verificationStatus === 'VERIFIED'
          ? `${operationLabel}: 거래소 조회 결과 청산할 가상자산이 없습니다.`
          : `${operationLabel}: 청산 대상 없음 기록의 검증 증거가 없습니다.`,
    }
  }

  const failedItems = summarizeFailedItems(operation.items)
  if (operation.status === 'PARTIAL') {
    return {
      tone: 'warning',
      message: `${operationLabel}이 잔여 자산 또는 원장 불일치로 부분 종결되었습니다.${failedItems}`,
    }
  }

  return {
    tone: 'error',
    message: `${operationLabel}이 실패했습니다.${failedItems}`,
  }
}

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (
      detail &&
      typeof detail === 'object' &&
      'message' in detail &&
      typeof detail.message === 'string' &&
      detail.message.trim()
    ) {
      return detail.message
    }
    if (error.message) {
      return error.message
    }
  }
  return fallback
}

function resolveErrorCode(error: unknown): string | null {
  if (!isAxiosError(error)) {
    return null
  }
  const detail = error.response?.data?.detail
  if (
    detail &&
    typeof detail === 'object' &&
    'error_code' in detail &&
    typeof detail.error_code === 'string'
  ) {
    return detail.error_code
  }
  return null
}

function resolveActiveLiquidationOperation(error: unknown): LiquidationOperation | null {
  if (!isAxiosError(error)) {
    return null
  }
  const detail = error.response?.data?.detail
  if (!detail || typeof detail !== 'object' || !('active_liquidation_operation' in detail)) {
    return null
  }
  const operation = detail.active_liquidation_operation
  if (
    !operation ||
    typeof operation !== 'object' ||
    !('id' in operation) ||
    typeof operation.id !== 'number' ||
    !('idempotency_key' in operation) ||
    typeof operation.idempotency_key !== 'string' ||
    !('status' in operation) ||
    typeof operation.status !== 'string' ||
    !('items' in operation) ||
    !Array.isArray(operation.items)
  ) {
    return null
  }
  return operation as LiquidationOperation
}

function optionalCount(value: number | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ko-KR') : '-'
}

function optionalAmount(value: string | null | undefined): string {
  return value?.trim() || '-'
}

function LiquidationDetails({ operation }: { operation: LiquidationOperation }) {
  const summary = operation.summary
  const showSummary = Boolean(summary || operation.cancellations?.length)
  const isLegacyUnverified =
    operation.verification_status?.trim().toUpperCase() === 'LEGACY_UNVERIFIED'

  return (
    <section className="mt-4 rounded-lg border border-border-subtle bg-surface-lowest/75 p-3 text-xs text-content-secondary">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold text-content">청산 작업 #{operation.id}</h3>
        <div className="flex flex-wrap gap-1.5">
          <span className="rounded bg-surface-high px-2 py-1 font-mono text-[11px] text-brand-bright">
            {phaseLabel(operation)}
          </span>
          <span
            className={`rounded bg-surface-high px-2 py-1 font-mono text-[11px] ${
              operation.status === 'COMPLETED' &&
              operation.verification_status?.trim().toUpperCase() === 'VERIFIED'
                ? 'text-status-success'
                : 'text-warning'
            }`}
          >
            검증 {operation.verification_status || '미제공'}
          </span>
        </div>
      </div>

      {isLegacyUnverified && (
        <p className="mt-3 rounded bg-warning/10 px-3 py-2 font-semibold leading-5 text-warning">
          이전 계약으로 생성된 작업이라 최종 잔고 검증 증거가 없습니다.
        </p>
      )}

      {showSummary && (
        <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
          <div>
            <dt className="text-content-muted">발견 주문</dt>
            <dd className="mt-1 font-mono text-content">
              {optionalCount(summary?.discovered_orders)}
            </dd>
          </div>
          <div>
            <dt className="text-content-muted">취소 확인 / 미확정</dt>
            <dd className="mt-1 font-mono text-content">
              {optionalCount(summary?.cancel_confirmed)} / {optionalCount(summary?.cancel_unknown)}
            </dd>
          </div>
          <div>
            <dt className="text-content-muted">청산 시도</dt>
            <dd className="mt-1 font-mono text-content">
              {optionalCount(summary?.attempted)}
            </dd>
          </div>
          <div>
            <dt className="text-content-muted">성공 / 실패</dt>
            <dd className="mt-1 font-mono text-content">
              {optionalCount(summary?.succeeded)} / {optionalCount(summary?.failed)}
            </dd>
          </div>
          <div>
            <dt className="text-content-muted">잔여 자산</dt>
            <dd className="mt-1 font-mono text-warning">
              {optionalCount(summary?.remaining)}
            </dd>
          </div>
        </dl>
      )}

      {operation.cancellations && operation.cancellations.length > 0 && (
        <div className="mt-3">
          <p className="font-semibold text-content">미체결 주문 취소</p>
          <ul className="mt-2 space-y-1">
            {operation.cancellations.map((cancellation) => (
              <li
                key={cancellation.exchange_uuid}
                className="flex flex-wrap justify-between gap-x-3 rounded bg-surface-low px-2 py-1.5"
              >
                <span>
                  {cancellation.market || '마켓 미상'} ·{' '}
                  {cancellation.ownership === 'EXTERNAL' ? '수동/외부 주문' : '관리 주문'}
                </span>
                <span className="font-mono text-content">
                  {cancellation.status || '상태 미확정'}
                  {cancellation.error_code ? ` · ${cancellation.error_code}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {operation.items.length > 0 && (
        <div className="mt-3">
          <p className="font-semibold text-content">자산별 청산 및 잔여</p>
          <ul className="mt-2 space-y-2">
            {operation.items.map((item, index) => {
              const resultCode = item.result_code?.trim()
              return (
                <li
                  key={`${item.market}-${item.currency ?? ''}-${index}`}
                  className="rounded bg-surface-low px-2 py-2"
                >
                  <div className="flex flex-wrap justify-between gap-2">
                    <span className="font-semibold text-content">
                      {item.market || item.currency || '자산 미상'}
                    </span>
                    <span
                      className={
                        resultCode === 'LIQUIDATED' &&
                        operation.status === 'COMPLETED' &&
                        operation.verification_status?.trim().toUpperCase() === 'VERIFIED'
                          ? 'text-status-success'
                          : 'text-warning'
                      }
                    >
                      {resultCode
                        ? (RESULT_LABELS[resultCode] ?? resultCode)
                        : item.error_code || '진행 중'}
                    </span>
                  </div>
                  <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <div>
                      <dt className="text-content-muted">최초 balance / locked</dt>
                      <dd className="mt-1 break-all font-mono">
                        {optionalAmount(item.initial_balance)} / {optionalAmount(item.initial_locked)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">요청 / 체결</dt>
                      <dd className="mt-1 break-all font-mono">
                        {optionalAmount(item.requested_volume)} / {optionalAmount(item.executed_volume)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">최종 balance / locked</dt>
                      <dd className="mt-1 break-all font-mono text-warning">
                        {optionalAmount(item.final_balance)} / {optionalAmount(item.final_locked)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-content-muted">평가액(KRW)</dt>
                      <dd className="mt-1 break-all font-mono">
                        {optionalAmount(item.estimated_value_krw)}
                      </dd>
                    </div>
                  </dl>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}

function ControlPanel() {
  const queryClient = useQueryClient()
  const [initialStoredLiquidation] = useState(() => getStoredLiquidationState())
  const storedOperation = initialStoredLiquidation.operation
  const [activeAction, setActiveAction] = useState<ActionType>(null)
  const [pendingOperationKey, setPendingOperationKey] = useState<string | null>(
    initialStoredLiquidation.operationKey,
  )
  const [pendingOperationId, setPendingOperationId] = useState<number | null>(
    storedOperation?.id ?? null,
  )
  const [lastOperation, setLastOperation] = useState<LiquidationOperation | null>(storedOperation)
  const [confirmation, setConfirmation] = useState('')
  const [feedback, setFeedback] = useState<LiquidationFeedback | null>(() =>
    storedOperation ? resolveLiquidationFeedback(storedOperation) : null,
  )
  const [requiresNewAuthorization, setRequiresNewAuthorization] = useState(false)

  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 5000,
    placeholderData: (previousData) => previousData,
  })

  const isSubmitting = activeAction !== null
  const hasPendingOperation = pendingOperationKey !== null || pendingOperationId !== null
  const hasTerminalResult = Boolean(
    lastOperation && isTerminalLiquidationStatus(lastOperation.status),
  )
  const hasValidConfirmation = confirmation === LIQUIDATION_CONFIRMATION
  const canCreateLiquidation =
    !botStatusQuery.isError &&
    botStatusQuery.data?.trading_mode === 'live' &&
    Number.isInteger(botStatusQuery.data.trading_mode_version) &&
    botStatusQuery.data.trading_mode_version >= 1 &&
    botStatusQuery.data.trading_mode_state_available === true &&
    botStatusQuery.data.trading_mode_mirror_consistent === true
  const newLiquidationBlockReason = botStatusQuery.isError
    ? '봇 상태 조회에 실패해 신규 실자산 청산 요청을 차단합니다. 기존 진행 작업의 재확인은 계속할 수 있습니다.'
    : botStatusQuery.isLoading || !botStatusQuery.data
      ? '거래 모드를 확인하는 동안 신규 실자산 청산 요청을 차단합니다.'
      : botStatusQuery.data.trading_mode === 'paper' &&
          botStatusQuery.data.trading_mode_state_available === true &&
          botStatusQuery.data.trading_mode_mirror_consistent === true
        ? 'PAPER 모드에서는 신규 실자산 청산 요청을 만들 수 없습니다.'
        : '거래 모드가 누락·불일치·unavailable 상태여서 신규 실자산 청산 요청을 차단합니다.'

  const rememberOperation = (operation: LiquidationOperation) => {
    storeLiquidationKey(operation.idempotency_key)
    storeLiquidationOperation(operation)
    setPendingOperationKey(operation.idempotency_key)
    setPendingOperationId(operation.id)
    setLastOperation(operation)
  }

  const handleLiquidate = async () => {
    if (!hasPendingOperation && !canCreateLiquidation) {
      setFeedback({ tone: 'warning', message: newLiquidationBlockReason })
      return
    }
    if (!hasPendingOperation && !hasValidConfirmation) {
      setFeedback({ tone: 'warning', message: '계정 전체 청산 확인 문구를 정확히 입력해 주세요.' })
      return
    }

    if (!hasPendingOperation) {
      const confirmed = window.confirm(
        'Upbit 계정의 봇 주문뿐 아니라 수동·외부 wait/watch 주문도 모두 취소한 뒤 전량 시장가 매도를 시작합니다. 계속하시겠습니까?',
      )
      if (!confirmed) {
        return
      }
    }

    const operationKey = pendingOperationKey ?? window.crypto.randomUUID()
    if (!pendingOperationKey) {
      storeLiquidationKey(operationKey)
      setPendingOperationKey(operationKey)
    }

    setActiveAction('liquidate')
    setFeedback(null)

    try {
      const operation =
        pendingOperationId === null
          ? await liquidateAll(operationKey, {
              scope: 'ACCOUNT_ALL',
              confirmation: LIQUIDATION_CONFIRMATION,
            })
          : await getLiquidation(pendingOperationId)

      rememberOperation(operation)
      setRequiresNewAuthorization(false)
      setFeedback(resolveLiquidationFeedback(operation))
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
        queryClient.invalidateQueries({ queryKey: ['live-order-gate'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-orders'] }),
        queryClient.invalidateQueries({ queryKey: PORTFOLIO_SUMMARY_QUERY_KEY }),
      ])
    } catch (error) {
      const errorCode = resolveErrorCode(error)
      const activeOperation = resolveActiveLiquidationOperation(error)
      const isActiveOperationConflict =
        isAxiosError(error) &&
        error.response?.status === 409 &&
        (errorCode === 'ORDER_GATE_GENERATION_CONFLICT' ||
          errorCode === 'LIQUIDATION_OPERATION_CONFLICT' ||
          errorCode === 'ACTIVE_LIQUIDATION_EXISTS') &&
        activeOperation !== null
      if (isActiveOperationConflict) {
        rememberOperation(activeOperation)
        setRequiresNewAuthorization(false)
        setFeedback(resolveLiquidationFeedback(activeOperation))
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
          queryClient.invalidateQueries({ queryKey: ['live-order-gate'] }),
        ])
        return
      }
      const isRevokedAuthorization =
        isAxiosError(error) &&
        error.response?.status === 409 &&
        (errorCode === 'EMERGENCY_AUTH_REVOKED' ||
          errorCode === 'ORDER_GATE_REQUEST_SUPERSEDED')
      if (isRevokedAuthorization) {
        clearStoredLiquidation()
        setPendingOperationKey(null)
        setPendingOperationId(null)
        setLastOperation(null)
        setConfirmation('')
        setRequiresNewAuthorization(true)
        setFeedback({
          tone: 'warning',
          message:
            '기존 청산 권한이 폐기되어 같은 요청 키를 더 이상 사용하지 않습니다. 확인 문구를 다시 입력하면 새 UUID로 요청합니다.',
        })
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
          queryClient.invalidateQueries({ queryKey: ['live-order-gate'] }),
        ])
        return
      }

      if (isAxiosError(error) && error.response?.status === 404 && pendingOperationId !== null) {
        setPendingOperationId(null)
      }

      const isNetworkError = isAxiosError(error) && !error.response
      const retryNotice = isNetworkError
        ? ' 같은 요청 키를 보존했습니다. 다시 시도하면 기존 작업을 이어서 확인합니다.'
        : ''
      setFeedback({
        tone: 'error',
        message: `${resolveErrorMessage(error, '전량 청산 요청을 확인하지 못했습니다.')}${retryNotice}`,
      })
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
        queryClient.invalidateQueries({ queryKey: ['live-order-gate'] }),
      ])
    } finally {
      setActiveAction(null)
    }
  }

  const handleResetLiquidation = () => {
    clearStoredLiquidation()
    setPendingOperationKey(null)
    setPendingOperationId(null)
    setLastOperation(null)
    setConfirmation('')
    setFeedback(null)
    setRequiresNewAuthorization(false)
  }

  let actionLabel = '계정 전체 청산 시작'
  if (activeAction === 'liquidate') {
    actionLabel = '처리 중...'
  } else if (requiresNewAuthorization) {
    actionLabel = '새 청산 요청 (새 UUID)'
  } else if (hasTerminalResult) {
    actionLabel = '청산 결과 다시 확인'
  } else if (pendingOperationId !== null) {
    actionLabel = '청산 상태 확인'
  } else if (pendingOperationKey) {
    actionLabel = '동일 요청 재시도'
  }

  return (
    <aside className="quantum-card rounded-xl p-5">
      <header className="mb-4">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-status-danger">
          Emergency Control
        </p>
        <h2 className="mt-2 text-lg font-bold text-content">비상 제어</h2>
      </header>

      <section>
        <p className="rounded-lg bg-status-danger/10 px-3 py-2 text-xs font-semibold leading-5 text-status-danger">
          계정 전체 청산은 봇 주문뿐 아니라 이 Upbit 계정에서 직접 만든 수동·외부 wait/watch
          주문도 모두 취소합니다.
        </p>
        <p className="mt-3 text-xs leading-5 text-content-muted">
          미체결 주문 취소를 확인한 뒤에만 EXIT_ONLY 권한으로 시장가 매도를 제출합니다. 잔여
          balance·locked 또는 원장 불일치는 성공으로 표시하지 않습니다.
        </p>

        {!hasPendingOperation && (
          <>
            <label
              className="mt-4 block text-xs font-semibold text-content-secondary"
              htmlFor="liquidation-confirmation"
            >
              확인 문구: {LIQUIDATION_CONFIRMATION}
            </label>
            <input
              id="liquidation-confirmation"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="off"
              className="mt-2 w-full rounded-lg border border-border-subtle bg-surface-lowest px-3 py-2 font-mono text-sm text-content outline-none focus:border-status-danger"
            />
          </>
        )}

        <button
          type="button"
          onClick={handleLiquidate}
          disabled={
            isSubmitting ||
            (!hasPendingOperation && (!canCreateLiquidation || !hasValidConfirmation))
          }
          className="mt-4 w-full rounded-lg bg-action-destructive px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-action-destructive/85 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {actionLabel}
        </button>

        {hasTerminalResult && (
          <button
            type="button"
            onClick={handleResetLiquidation}
            disabled={isSubmitting}
            className="mt-2 w-full rounded-lg border border-warning/40 px-3 py-2 text-xs font-semibold text-warning hover:bg-warning/10 disabled:opacity-50"
          >
            결과 닫고 새 청산 준비
          </button>
        )}

        {!hasPendingOperation && !canCreateLiquidation && (
          <p className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-xs font-semibold leading-5 text-warning">
            {newLiquidationBlockReason}
          </p>
        )}
      </section>

      {feedback && (
        <p
          role={feedback.tone === 'error' ? 'alert' : 'status'}
          aria-live={feedback.tone === 'error' ? 'assertive' : 'polite'}
          aria-atomic="true"
          className={`mt-4 rounded-lg bg-surface-lowest/75 px-3 py-2 text-xs font-semibold ${FEEDBACK_TONE_CLASS[feedback.tone]}`}
        >
          {feedback.message}
        </p>
      )}

      {lastOperation && <LiquidationDetails operation={lastOperation} />}
    </aside>
  )
}

export default ControlPanel
