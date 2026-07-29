import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from '@headlessui/react'
import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { type FormEvent, useEffect, useRef, useState } from 'react'

import {
  armLiveOrderGate,
  blockLiveOrderGate,
  enableLiveTrading,
  enablePaperTrading,
  getBotStatus,
  reauthAdminForLiveTrading,
  requestAdminToken,
  startBot,
  stopBot,
} from '../../services/api'
import type {
  ArmLiveOrderGateRequest,
  BotStatus,
  EnableLiveTradingRequest,
  EnablePaperTradingRequest,
  LiveOrderGateStatus,
  LiveOrderMode,
  TradingMode,
  TradingModeStatus,
} from '../../services/api'

type ActionType = 'start' | 'stop' | 'block' | 'arm' | 'mode-live' | 'mode-paper' | null
type NoticeType = 'success' | 'error'

interface NoticeState {
  message: string
  type: NoticeType
}

interface BotControlPanelProps {
  portfolioError?: string | null
}

interface PendingGateRequest<TPayload> {
  idempotencyKey: string
  payload: TPayload
}

type PendingLiveModeRequest = PendingGateRequest<EnableLiveTradingRequest>
type PendingPaperModeRequest = PendingGateRequest<EnablePaperTradingRequest>

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

function resolvePortfolioWarningMessage(portfolioError: string | null | undefined): string | null {
  if (portfolioError === null || portfolioError === undefined) {
    return null
  }

  if (portfolioError === 'UPBIT_KEY_MISSING') {
    return '업비트 API 키가 설정되지 않아 자산 조회 및 매매 기능이 제한됩니다.'
  }
  if (portfolioError === 'UPBIT_AUTH_IP_NOT_ALLOWED') {
    return '현재 서버 IP가 업비트 API 허용 목록에 없어 자산 조회 및 매매 기능이 제한됩니다.'
  }
  if (portfolioError === 'UPBIT_AUTH_ERROR') {
    return '업비트 API 인증 또는 권한 설정 문제로 자산 조회 및 매매 기능이 제한됩니다.'
  }

  return '업비트 자산 정보를 불러오지 못해 자산 조회 및 매매 기능이 제한됩니다.'
}

function formatGateChangedAt(value: string | null | undefined): string {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function mergeGateStatus(status: BotStatus, gate: LiveOrderGateStatus): BotStatus {
  return {
    ...status,
    live_order_mode: gate.mode,
    live_order_generation: gate.generation,
    live_order_version: gate.version,
    live_order_reason_code: gate.reason_code,
    live_order_reason: gate.reason,
    live_order_source: gate.source,
    live_order_changed_at: gate.changed_at,
    live_order_active_liquidation_operation_id: gate.active_liquidation_operation_id,
    live_order_rollout_enabled: gate.rollout_enabled,
    live_order_state_available: gate.state_available,
  }
}

function gateModeClassName(mode: LiveOrderMode, available: boolean): string {
  if (!available || mode === 'BLOCK_ALL') {
    return 'text-status-danger'
  }
  if (mode === 'EXIT_ONLY') {
    return 'text-warning'
  }
  return 'text-brand-bright'
}

function isTradingMode(value: unknown): value is TradingMode {
  return value === 'paper' || value === 'live'
}

function tradingModeFromBotStatus(status: BotStatus | undefined): TradingModeStatus | null {
  if (!status || !isTradingMode(status.trading_mode) || !Number.isInteger(status.trading_mode_version)) {
    return null
  }
  return {
    mode: status.trading_mode,
    version: status.trading_mode_version,
    reason_code: status.trading_mode_reason_code,
    reason: status.trading_mode_reason,
    source: status.trading_mode_source,
    actor_ref: status.trading_mode_actor_ref,
    changed_at: status.trading_mode_changed_at,
    state_available: status.trading_mode_state_available,
    mirror_consistent: status.trading_mode_mirror_consistent,
    unavailable_reason: status.trading_mode_unavailable_reason,
  }
}

function mergeTradingModeStatus(status: BotStatus, mode: TradingModeStatus): BotStatus {
  return {
    ...status,
    trading_mode: mode.mode,
    trading_mode_version: mode.version,
    trading_mode_reason_code: mode.reason_code,
    trading_mode_reason: mode.reason,
    trading_mode_source: mode.source,
    trading_mode_actor_ref: mode.actor_ref,
    trading_mode_changed_at: mode.changed_at,
    trading_mode_state_available: mode.state_available,
    trading_mode_mirror_consistent: mode.mirror_consistent,
    trading_mode_unavailable_reason: mode.unavailable_reason,
  }
}

function tradingModeClassName(mode: TradingMode | null, available: boolean): string {
  if (!available || mode === null) {
    return 'text-status-danger'
  }
  return mode === 'live' ? 'text-status-danger' : 'text-warning'
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

function isAmbiguousHttpFailure(error: unknown): boolean {
  if (!isAxiosError(error)) {
    return false
  }
  if (!error.response) {
    return true
  }
  return typeof error.response.status === 'number' && error.response.status >= 500
}

function BotControlPanel({ portfolioError = null }: BotControlPanelProps) {
  const queryClient = useQueryClient()
  const [activeAction, setActiveAction] = useState<ActionType>(null)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const [isArmFormOpen, setIsArmFormOpen] = useState(false)
  const [armReason, setArmReason] = useState('')
  const [armConfirmation, setArmConfirmation] = useState('')
  const [pendingArmRequest, setPendingArmRequest] = useState<
    PendingGateRequest<ArmLiveOrderGateRequest> | null
  >(null)
  const [pendingBlockRequest, setPendingBlockRequest] = useState<
    PendingGateRequest<{ reason: string }> | null
  >(null)
  const [modeFormTarget, setModeFormTarget] = useState<TradingMode | null>(null)
  const [modeReason, setModeReason] = useState('')
  const [liveConfirmation, setLiveConfirmation] = useState('')
  const [pendingLiveModeRequest, setPendingLiveModeRequest] =
    useState<PendingLiveModeRequest | null>(null)
  const [pendingPaperModeRequest, setPendingPaperModeRequest] =
    useState<PendingPaperModeRequest | null>(null)
  const [stopDrainPending, setStopDrainPending] = useState(false)
  const modeReasonInputRef = useRef<HTMLTextAreaElement | null>(null)
  const armReasonInputRef = useRef<HTMLTextAreaElement | null>(null)

  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  useEffect(() => {
    if (notice === null) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setNotice(null)
    }, 3000)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [notice])

  const isLoading = botStatusQuery.isLoading
  const isError = botStatusQuery.isError
  const botStatus = botStatusQuery.data
  const isActive = botStatus?.running ?? false
  const isSubmitting = activeAction !== null
  const gateMode = botStatus?.live_order_mode ?? 'BLOCK_ALL'
  const gateStateAvailable = botStatus?.live_order_state_available ?? false
  const rolloutEnabled = botStatus?.live_order_rollout_enabled ?? false
  const tradingModeStatus = tradingModeFromBotStatus(botStatus)
  const tradingMode = isTradingMode(tradingModeStatus?.mode) ? tradingModeStatus.mode : null
  const tradingModeStateAvailable =
    !botStatusQuery.isError &&
    tradingModeStatus?.state_available === true &&
    tradingModeStatus.mirror_consistent === true &&
    tradingModeStatus.version >= 1 &&
    tradingMode !== null
  const canStop =
    Boolean(botStatus) && (isActive || gateMode !== 'BLOCK_ALL' || stopDrainPending)
  const canArm =
    Boolean(botStatus) &&
    isActive &&
    tradingModeStateAvailable &&
    tradingMode === 'live' &&
    gateStateAvailable &&
    rolloutEnabled &&
    gateMode === 'BLOCK_ALL'
  const canBlock = Boolean(botStatus) && gateStateAvailable && gateMode !== 'BLOCK_ALL'
  const canEnableLiveMode =
    Boolean(botStatus) &&
    tradingModeStateAvailable &&
    tradingMode === 'paper' &&
    !isActive &&
    rolloutEnabled &&
    gateStateAvailable &&
    gateMode === 'BLOCK_ALL' &&
    botStatus?.live_order_active_liquidation_operation_id === null
  const canEnablePaperMode =
    Boolean(tradingModeStatus) &&
    Number.isInteger(tradingModeStatus?.version) &&
    (tradingModeStatus?.version ?? 0) >= 1 &&
    (tradingMode !== 'paper' || !tradingModeStateAvailable)
  const badgeLabel = isError ? 'ERROR' : isLoading ? 'CHECK' : isActive ? 'ACTIVE' : 'STOP'
  const badgeClassName = isError
    ? 'bg-status-danger/10 text-status-danger'
    : isActive
      ? 'bg-brand/10 text-brand-bright'
      : 'bg-surface-high text-content-secondary'
  const portfolioWarningMessage = resolvePortfolioWarningMessage(portfolioError)

  const invalidateControlQueries = () => {
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
      queryClient.invalidateQueries({ queryKey: ['live-order-gate'] }),
      queryClient.invalidateQueries({ queryKey: ['trading-mode'] }),
    ])
  }

  const applyGateStatus = (gate: LiveOrderGateStatus) => {
    queryClient.setQueryData<BotStatus>(['bot-status'], (currentStatus) =>
      currentStatus ? mergeGateStatus(currentStatus, gate) : currentStatus,
    )
    queryClient.setQueryData(['live-order-gate'], gate)
  }

  const applyTradingModeStatus = (mode: TradingModeStatus) => {
    queryClient.setQueryData<BotStatus>(['bot-status'], (currentStatus) =>
      currentStatus ? mergeTradingModeStatus(currentStatus, mode) : currentStatus,
    )
    queryClient.setQueryData(['trading-mode'], mode)
  }

  const handleStart = async () => {
    setActiveAction('start')
    setNotice(null)

    try {
      const nextStatus = await startBot()
      queryClient.setQueryData(['bot-status'], nextStatus)
      invalidateControlQueries()
      setNotice({
        message: `분석 런타임을 시작했습니다. 실주문 Gate는 자동 재무장하지 않았습니다 (${nextStatus.live_order_mode}).`,
        type: 'success',
      })
    } catch (error) {
      setNotice({ message: resolveErrorMessage(error, '봇 가동 요청에 실패했습니다.'), type: 'error' })
    } finally {
      setActiveAction(null)
    }
  }

  const handleStop = async () => {
    setActiveAction('stop')
    setNotice(null)

    try {
      const nextStatus = await stopBot()
      queryClient.setQueryData(['bot-status'], nextStatus)
      setStopDrainPending(false)
      invalidateControlQueries()
      setNotice({
        message: '런타임 정지와 신규 실주문 차단(BLOCK_ALL)이 완료되었습니다.',
        type: 'success',
      })
    } catch (error) {
      const drainPending = resolveErrorCode(error) === 'ORDER_GATE_DRAIN_PENDING'
      setStopDrainPending(drainPending)
      setNotice({
        message: drainPending
          ? '런타임 정지와 BLOCK_ALL은 적용됐습니다. 기존 제출 확인이 끝난 뒤 정지 상태를 다시 확인해 주세요.'
          : resolveErrorMessage(error, '봇 정지 요청에 실패했습니다.'),
        type: 'error',
      })
      invalidateControlQueries()
    } finally {
      setActiveAction(null)
    }
  }

  const handleBlock = async () => {
    let request = pendingBlockRequest
    if (!request) {
      const reason = window.prompt(
        '신규 실주문을 즉시 차단하는 사유를 10자 이상 입력해 주세요.',
      )
      if (reason === null) {
        return
      }
      const normalizedReason = reason.trim().replace(/\s+/g, ' ')
      if (normalizedReason.length < 10) {
        setNotice({ message: '즉시 차단 사유는 10자 이상이어야 합니다.', type: 'error' })
        return
      }
      if (!window.confirm('신규 Upbit 주문을 즉시 차단하시겠습니까?')) {
        return
      }
      request = {
        idempotencyKey: window.crypto.randomUUID(),
        payload: { reason: normalizedReason },
      }
      setPendingBlockRequest(request)
    }

    setActiveAction('block')
    setNotice(null)
    try {
      const gate = await blockLiveOrderGate(request.payload, request.idempotencyKey)
      applyGateStatus(gate)
      setPendingBlockRequest(null)
      invalidateControlQueries()
      setNotice({ message: '신규 실주문을 BLOCK_ALL로 즉시 차단했습니다.', type: 'success' })
    } catch (error) {
      const isAmbiguousFailure = isAmbiguousHttpFailure(error)
      const drainPending = resolveErrorCode(error) === 'ORDER_GATE_DRAIN_PENDING'
      if (!isAmbiguousFailure && !drainPending) {
        setPendingBlockRequest(null)
      }
      setNotice({
        message: drainPending
          ? 'BLOCK_ALL은 적용됐습니다. 기존 제출 확인이 끝난 뒤 동일 차단 키로 다시 확인해 주세요.'
          : isAmbiguousFailure
            ? `${resolveErrorMessage(error, '차단 응답을 확인하지 못했습니다.')} 같은 요청 키로 다시 확인합니다.`
            : resolveErrorMessage(error, '실주문 즉시 차단에 실패했습니다.'),
        type: 'error',
      })
      invalidateControlQueries()
    } finally {
      setActiveAction(null)
    }
  }

  const handleArmSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!botStatus || (!canArm && !pendingArmRequest)) {
      setNotice({ message: '현재 상태에서는 실주문 Gate를 재무장할 수 없습니다.', type: 'error' })
      return
    }

    let request = pendingArmRequest
    if (!request) {
      const normalizedReason = armReason.trim().replace(/\s+/g, ' ')
      if (normalizedReason.length < 10 || armConfirmation !== 'ENABLE_LIVE_ORDERS') {
        setNotice({ message: '10자 이상 사유와 정확한 확인 문구가 필요합니다.', type: 'error' })
        return
      }
      request = {
        idempotencyKey: window.crypto.randomUUID(),
        payload: {
          expected_generation: botStatus.live_order_generation,
          expected_version: botStatus.live_order_version,
          reason: normalizedReason,
          confirmation: 'ENABLE_LIVE_ORDERS',
        },
      }
      setPendingArmRequest(request)
    }

    setActiveAction('arm')
    setNotice(null)
    try {
      const gate = await armLiveOrderGate(request.payload, request.idempotencyKey)
      applyGateStatus(gate)
      setPendingArmRequest(null)
      setArmReason('')
      setArmConfirmation('')
      setIsArmFormOpen(false)
      invalidateControlQueries()
      setNotice({ message: '실주문 Gate를 ARMED로 재무장했습니다.', type: 'success' })
    } catch (error) {
      const isAmbiguousFailure = isAmbiguousHttpFailure(error)
      if (!isAmbiguousFailure) {
        setPendingArmRequest(null)
      }
      setNotice({
        message: isAmbiguousFailure
          ? `${resolveErrorMessage(error, '재무장 응답을 확인하지 못했습니다.')} 같은 Idempotency-Key로만 재시도합니다.`
          : resolveErrorMessage(error, '실주문 Gate 재무장에 실패했습니다.'),
        type: 'error',
      })
      invalidateControlQueries()
    } finally {
      setActiveAction(null)
    }
  }

  const openModeForm = (target: TradingMode) => {
    setModeFormTarget(target)
    setNotice(null)
    if (target === 'live' && pendingLiveModeRequest) {
      setModeReason(pendingLiveModeRequest.payload.reason)
      setLiveConfirmation(pendingLiveModeRequest.payload.confirmation)
    } else if (target === 'paper' && pendingPaperModeRequest) {
      setModeReason(pendingPaperModeRequest.payload.reason)
    } else {
      setModeReason('')
      setLiveConfirmation('')
    }
  }

  const handleLiveModeSubmit = async () => {
    if (!tradingModeStatus || (!canEnableLiveMode && !pendingLiveModeRequest)) {
      setNotice({
        message: '현재 상태에서는 live 거래 모드로 전환할 수 없습니다.',
        type: 'error',
      })
      return
    }

    const normalizedReason = modeReason.trim().replace(/\s+/g, ' ')
    if (
      !pendingLiveModeRequest &&
      (normalizedReason.length < 10 || liveConfirmation !== 'ENABLE_LIVE_TRADING')
    ) {
      setNotice({ message: '10자 이상의 사유와 정확한 확인 문구가 필요합니다.', type: 'error' })
      return
    }

    setActiveAction('mode-live')
    setNotice(null)
    const hadPendingRequest = pendingLiveModeRequest !== null
    let request = pendingLiveModeRequest
    try {
      const adminToken = await requestAdminToken('live 거래 모드 전환 재인증', {
        forcePrompt: true,
        persistent: false,
      })
      if (!request) {
        const reauth = await reauthAdminForLiveTrading(adminToken)
        request = {
          idempotencyKey: window.crypto.randomUUID(),
          payload: {
            expected_version: tradingModeStatus.version,
            expected_gate_generation: botStatus?.live_order_generation ?? -1,
            expected_gate_version: botStatus?.live_order_version ?? -1,
            reason: normalizedReason,
            confirmation: 'ENABLE_LIVE_TRADING',
            reauth_proof: reauth.reauth_proof,
          },
        }
        setPendingLiveModeRequest(request)
      }

      const nextMode = await enableLiveTrading(
        request.payload,
        request.idempotencyKey,
        adminToken,
      )
      applyTradingModeStatus(nextMode)
      setPendingLiveModeRequest(null)
      setModeReason('')
      setLiveConfirmation('')
      setModeFormTarget(null)
      invalidateControlQueries()
      setNotice({
        message: '거래 모드를 live로 전환했습니다. 런타임 시작과 Gate 재무장은 별도로 수행해야 합니다.',
        type: 'success',
      })
    } catch (error) {
      const isNetworkError = isAxiosError(error) && !error.response
      const isServerError =
        isAxiosError(error) &&
        typeof error.response?.status === 'number' &&
        error.response.status >= 500
      const wasCancelledBeforeHttp = hadPendingRequest && !isAxiosError(error)
      const canRetrySameRequest =
        request !== null && (isNetworkError || isServerError || wasCancelledBeforeHttp)
      if (!canRetrySameRequest) {
        setPendingLiveModeRequest(null)
      }
      setNotice({
        message: canRetrySameRequest
          ? `${resolveErrorMessage(error, 'live 전환 응답을 확인하지 못했습니다.')} 같은 Idempotency-Key로만 재시도합니다.`
          : resolveErrorMessage(error, 'live 거래 모드 전환에 실패했습니다.'),
        type: 'error',
      })
      invalidateControlQueries()
    } finally {
      setActiveAction(null)
    }
  }

  const handlePaperModeSubmit = async () => {
    if (!tradingModeStatus || (!canEnablePaperMode && !pendingPaperModeRequest)) {
      setNotice({
        message: '현재 상태에서는 paper 거래 모드로 전환할 수 없습니다.',
        type: 'error',
      })
      return
    }

    const normalizedReason = modeReason.trim().replace(/\s+/g, ' ')
    if (!pendingPaperModeRequest && normalizedReason.length < 10) {
      setNotice({ message: 'paper 전환 사유를 10자 이상 입력해 주세요.', type: 'error' })
      return
    }

    const hadPendingRequest = pendingPaperModeRequest !== null
    let request = pendingPaperModeRequest
    if (!request) {
      request = {
        idempotencyKey: window.crypto.randomUUID(),
        payload: {
          expected_version: tradingModeStatus.version,
          reason: normalizedReason,
        },
      }
      setPendingPaperModeRequest(request)
    }

    setActiveAction('mode-paper')
    setNotice(null)
    try {
      const nextMode = await enablePaperTrading(request.payload, request.idempotencyKey)
      applyTradingModeStatus(nextMode)
      setPendingPaperModeRequest(null)
      setModeReason('')
      setModeFormTarget(null)
      invalidateControlQueries()
      setNotice({
        message: '거래 모드를 paper로 전환하고 런타임 및 실주문 Gate 정지를 요청했습니다.',
        type: 'success',
      })
    } catch (error) {
      const isNetworkError = isAxiosError(error) && !error.response
      const isServerError =
        isAxiosError(error) &&
        typeof error.response?.status === 'number' &&
        error.response.status >= 500
      const drainPending = resolveErrorCode(error) === 'ORDER_GATE_DRAIN_PENDING'
      const wasCancelledBeforeHttp = hadPendingRequest && !isAxiosError(error)
      const canRetrySameRequest =
        isNetworkError || isServerError || drainPending || wasCancelledBeforeHttp
      if (!canRetrySameRequest) {
        setPendingPaperModeRequest(null)
      }
      setNotice({
        message:
          canRetrySameRequest
            ? `${resolveErrorMessage(error, 'paper 전환 완료 여부를 확인하지 못했습니다.')} 같은 Idempotency-Key로만 재시도합니다.`
            : resolveErrorMessage(error, 'paper 거래 모드 전환에 실패했습니다.'),
        type: 'error',
      })
      invalidateControlQueries()
    } finally {
      setActiveAction(null)
    }
  }

  const handleModeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (modeFormTarget === 'live') {
      await handleLiveModeSubmit()
      return
    }
    if (modeFormTarget === 'paper') {
      await handlePaperModeSubmit()
    }
  }

  return (
    <aside className="quantum-card rounded-xl p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-warning">
            Bot Control
          </p>
          <h2 className="mt-2 text-lg font-bold text-content">실시간 파라미터 제어</h2>
        </div>
        <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-bold ${badgeClassName}`}>
          {badgeLabel}
        </span>
      </header>

      <p className="mt-3 text-sm leading-6 text-content-muted">
        봇 런타임과 매매 잠금 상태를 확인하고, 원격 시작/정지를 즉시 전송합니다.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="border-l-2 border-brand pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-content-muted">Runtime</p>
          <p className="mt-2 font-mono text-base font-bold text-content">
            {isActive ? 'RUNNING' : isError ? 'UNKNOWN' : 'STOPPED'}
          </p>
        </div>
        <div className="border-l-2 border-warning pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-content-muted">
            Trading Mode
          </p>
          <p
            className={`mt-2 font-mono text-base font-bold ${tradingModeClassName(tradingMode, tradingModeStateAvailable)}`}
          >
            {tradingModeStateAvailable && tradingMode ? tradingMode.toUpperCase() : 'UNAVAILABLE'}
          </p>
        </div>
        <div className="border-l-2 border-status-danger pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-content-muted">Order Gate</p>
          <p
            className={`mt-2 font-mono text-base font-bold ${gateModeClassName(gateMode, gateStateAvailable)}`}
          >
            {gateStateAvailable ? gateMode : 'BLOCK_ALL'}
          </p>
        </div>
        <div className="border-l-2 border-brand-secondary pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-content-muted">Rollout</p>
          <p
            className={`mt-2 font-mono text-base font-bold ${rolloutEnabled ? 'text-brand-bright' : 'text-status-danger'}`}
          >
            {rolloutEnabled ? 'ENABLED' : 'OFF'}
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-lg bg-surface-lowest/60 px-3 py-3 text-xs leading-5 text-content-secondary">
        <div className="flex items-start justify-between gap-3">
          <span className="text-content-muted">거래 모드 사유</span>
          <span className="text-right font-semibold text-content">
            {tradingModeStateAvailable
              ? tradingModeStatus?.reason
              : tradingModeStatus?.unavailable_reason ?? '거래 모드 상태를 확인할 수 없습니다.'}
          </span>
        </div>
        <div className="mt-2 flex items-start justify-between gap-3">
          <span className="text-content-muted">Mode / Gate 버전</span>
          <span className="text-right font-mono">
            {tradingModeStatus?.version ?? '-'} / {botStatus?.live_order_generation ?? '-'}·
            {botStatus?.live_order_version ?? '-'}
          </span>
        </div>
        <div className="mt-2 flex items-start justify-between gap-3">
          <span className="text-content-muted">Gate 사유</span>
          <span className="text-right font-semibold text-content">
            {botStatus?.live_order_reason ?? '제어 상태를 확인할 수 없어 차단합니다.'}
          </span>
        </div>
        <div className="mt-2 flex items-start justify-between gap-3">
          <span className="text-content-muted">변경</span>
          <span className="text-right font-mono">
            {botStatus?.live_order_source ?? 'SYSTEM'} ·{' '}
            {formatGateChangedAt(botStatus?.live_order_changed_at)}
          </span>
        </div>
        <div className="mt-2 flex items-start justify-between gap-3">
          <span className="text-content-muted">활성 청산</span>
          <span className="text-right font-mono">
            {botStatus?.live_order_active_liquidation_operation_id
              ? `#${botStatus.live_order_active_liquidation_operation_id}`
              : '-'}
          </span>
        </div>
      </div>

      {!tradingModeStateAvailable && (
        <div className="mt-4 rounded-lg bg-status-danger/10 px-3 py-2 text-xs font-semibold leading-5 text-status-danger">
          거래 모드가 누락·불일치·조회 실패 상태입니다. live로 간주하지 않으며 실주문을 차단합니다.
        </div>
      )}

      {portfolioWarningMessage && (
        <div className="mt-4 rounded-lg bg-surface-lowest/75 px-3 py-2 text-xs font-semibold leading-5 text-warning">
          자산 연결 제한
        </div>
      )}

      <section className="mt-5 border-t border-border-subtle/80 pt-5">
        <div className="mb-3 grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => openModeForm('live')}
            disabled={
              isSubmitting ||
              (!canEnableLiveMode && !pendingLiveModeRequest)
            }
            className="rounded-lg border border-status-danger/35 bg-status-danger/8 px-3 py-2 text-xs font-bold text-status-danger transition hover:bg-status-danger/14 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pendingLiveModeRequest ? '동일 live 요청 재확인' : 'LIVE 모드 전환'}
          </button>
          <button
            type="button"
            onClick={() => openModeForm('paper')}
            disabled={
              isSubmitting ||
              (!canEnablePaperMode && !pendingPaperModeRequest)
            }
            className="rounded-lg border border-warning/35 bg-warning/8 px-3 py-2 text-xs font-bold text-warning transition hover:bg-warning/14 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pendingPaperModeRequest ? '동일 paper 요청 재확인' : 'PAPER 모드 전환'}
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={handleStart}
            disabled={isSubmitting || isLoading || isActive}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              isActive
                ? 'cursor-not-allowed bg-brand/10 text-brand/45'
                : 'bg-brand/14 text-brand-bright hover:bg-brand/22'
            } disabled:opacity-70`}
          >
            {activeAction === 'start' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>{activeAction === 'start' ? '가동 중...' : '봇 가동'}</span>
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={isSubmitting || isLoading || !canStop}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              !canStop
                ? 'cursor-not-allowed bg-surface-lowest/75 text-content-muted'
                : 'bg-surface-lowest text-content hover:bg-surface-high'
            } disabled:opacity-70`}
          >
            {activeAction === 'stop' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>
              {activeAction === 'stop'
                ? '정지 중...'
                : stopDrainPending
                  ? '정지 상태 재확인'
                  : '봇 정지'}
            </span>
          </button>
          <button
            type="button"
            onClick={handleBlock}
            disabled={isSubmitting || isLoading || (!canBlock && !pendingBlockRequest)}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-status-danger/12 px-3 py-2 text-sm font-semibold text-status-danger transition-colors hover:bg-status-danger/20 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {activeAction === 'block' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>
              {activeAction === 'block'
                ? '차단 중...'
                : pendingBlockRequest
                  ? '동일 차단 재확인'
                  : '실주문 즉시 차단'}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setIsArmFormOpen(true)}
            disabled={isSubmitting || isLoading || (!canArm && !pendingArmRequest)}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand/12 px-3 py-2 text-sm font-semibold text-brand-bright transition-colors hover:bg-brand/20 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {pendingArmRequest ? '재무장 응답 재확인' : '실주문 재무장'}
          </button>
        </div>
        <p className="mt-3 text-xs leading-5 text-content-muted">
          봇 가동은 분석 런타임만 시작합니다. 실주문 차단은 별도 재무장 확인을 완료할 때까지
          유지됩니다.
        </p>
      </section>

      {notice && (
        <p
          role={notice.type === 'error' ? 'alert' : 'status'}
          aria-live={notice.type === 'error' ? 'assertive' : 'polite'}
          aria-atomic="true"
          className={`mt-4 rounded-lg bg-surface-lowest/75 px-3 py-2 text-xs font-semibold ${
            notice.type === 'success'
              ? 'text-status-success'
              : 'text-status-danger'
          }`}
        >
          {notice.message}
        </p>
      )}

      <Dialog
        open={modeFormTarget !== null}
        onClose={() => {
          if (activeAction !== 'mode-live' && activeAction !== 'mode-paper') {
            setModeFormTarget(null)
          }
        }}
        initialFocus={modeReasonInputRef}
        className="relative z-50"
      >
        <DialogBackdrop className="fixed inset-0 bg-canvas/80 backdrop-blur-sm" />
        <div className="fixed inset-0 flex items-center justify-center overflow-y-auto p-4">
          <DialogPanel
            as="form"
            onSubmit={handleModeSubmit}
            className="w-full max-w-lg rounded-xl border border-warning/25 bg-surface-low p-5 shadow-2xl"
          >
            <DialogTitle className="text-lg font-bold text-content">
              {modeFormTarget === 'live' ? 'LIVE 거래 모드 전환' : 'PAPER 거래 모드 전환'}
            </DialogTitle>
            <p className="mt-2 text-sm leading-6 text-status-danger">
              {modeFormTarget === 'live'
                ? '관리자 토큰을 강제로 다시 입력하고 5분 proof를 발급합니다. 성공해도 런타임과 Gate는 자동으로 켜지지 않습니다.'
                : '안전 모드로 전환하면서 백엔드가 런타임 정지와 BLOCK_ALL을 함께 확인합니다.'}
            </p>

            <label className="mt-4 block text-xs font-semibold text-content-secondary" htmlFor="mode-reason">
              운영 사유 (10자 이상)
            </label>
            <textarea
              ref={modeReasonInputRef}
              id="mode-reason"
              value={
                modeFormTarget === 'live' && pendingLiveModeRequest
                  ? pendingLiveModeRequest.payload.reason
                  : modeFormTarget === 'paper' && pendingPaperModeRequest
                    ? pendingPaperModeRequest.payload.reason
                    : modeReason
              }
              onChange={(event) => setModeReason(event.target.value)}
              readOnly={Boolean(pendingLiveModeRequest || pendingPaperModeRequest)}
              rows={3}
              className="mt-2 w-full rounded-lg border border-border-subtle bg-surface-lowest px-3 py-2 text-sm text-content outline-none focus:border-warning read-only:opacity-65"
            />

            {modeFormTarget === 'live' && (
              <>
                <label
                  className="mt-4 block text-xs font-semibold text-content-secondary"
                  htmlFor="live-mode-confirmation"
                >
                  확인 문구: ENABLE_LIVE_TRADING
                </label>
                <input
                  id="live-mode-confirmation"
                  value={pendingLiveModeRequest?.payload.confirmation ?? liveConfirmation}
                  onChange={(event) => setLiveConfirmation(event.target.value)}
                  readOnly={Boolean(pendingLiveModeRequest)}
                  autoComplete="off"
                  className="mt-2 w-full rounded-lg border border-border-subtle bg-surface-lowest px-3 py-2 font-mono text-sm text-content outline-none focus:border-status-danger read-only:opacity-65"
                />
              </>
            )}

            <p className="mt-3 break-all font-mono text-[11px] text-content-muted">
              Idempotency-Key:{' '}
              {modeFormTarget === 'live'
                ? pendingLiveModeRequest?.idempotencyKey ?? '재인증 후 UUID v4 생성'
                : pendingPaperModeRequest?.idempotencyKey ?? '제출 시 UUID v4 생성'}
            </p>

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              {(pendingLiveModeRequest || pendingPaperModeRequest) && (
                <button
                  type="button"
                  onClick={() => {
                    if (window.confirm('기존 요청의 재시도를 포기하고 새 요청을 작성하시겠습니까?')) {
                      setPendingLiveModeRequest(null)
                      setPendingPaperModeRequest(null)
                      setModeReason('')
                      setLiveConfirmation('')
                    }
                  }}
                  className="mr-auto rounded-lg px-3 py-2 text-xs font-semibold text-warning hover:bg-warning/10"
                >
                  새 요청 작성
                </button>
              )}
              <button
                type="button"
                onClick={() => setModeFormTarget(null)}
                disabled={activeAction === 'mode-live' || activeAction === 'mode-paper'}
                className="rounded-lg px-3 py-2 text-sm font-semibold text-content-secondary hover:bg-surface-high disabled:opacity-50"
              >
                닫기
              </button>
              <button
                type="submit"
                aria-busy={activeAction === 'mode-live' || activeAction === 'mode-paper'}
                disabled={
                  activeAction === 'mode-live' ||
                  activeAction === 'mode-paper' ||
                  (!pendingLiveModeRequest &&
                    !pendingPaperModeRequest &&
                    (modeReason.trim().replace(/\s+/g, ' ').length < 10 ||
                      (modeFormTarget === 'live' &&
                        liveConfirmation !== 'ENABLE_LIVE_TRADING')))
                }
                className="inline-flex items-center gap-2 rounded-lg bg-warning/16 px-3 py-2 text-sm font-bold text-warning hover:bg-warning/24 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {(activeAction === 'mode-live' || activeAction === 'mode-paper') && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {modeFormTarget === 'live'
                  ? pendingLiveModeRequest
                    ? '동일 요청 재시도'
                    : '재인증 후 LIVE 전환'
                  : pendingPaperModeRequest
                    ? '동일 요청 재시도'
                    : 'PAPER 전환'}
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>

      <Dialog
        open={isArmFormOpen}
        onClose={() => {
          if (activeAction !== 'arm') {
            setIsArmFormOpen(false)
          }
        }}
        initialFocus={armReasonInputRef}
        className="relative z-50"
      >
        <DialogBackdrop className="fixed inset-0 bg-canvas/80 backdrop-blur-sm" />
        <div className="fixed inset-0 flex items-center justify-center overflow-y-auto p-4">
          <DialogPanel
            as="form"
            onSubmit={handleArmSubmit}
            className="w-full max-w-lg rounded-xl border border-brand/25 bg-surface-low p-5 shadow-2xl"
          >
            <DialogTitle className="text-lg font-bold text-content">실주문 Gate 재무장</DialogTitle>
            <p className="mt-2 text-sm leading-6 text-status-danger">
              이 작업은 신규 Upbit 주문을 다시 허용합니다. generation{' '}
              {pendingArmRequest?.payload.expected_generation ?? botStatus?.live_order_generation ?? '-'} / version{' '}
              {pendingArmRequest?.payload.expected_version ?? botStatus?.live_order_version ?? '-'}을 기준으로
              검증합니다.
            </p>

            <label className="mt-4 block text-xs font-semibold text-content-secondary" htmlFor="arm-reason">
              운영 사유 (10자 이상)
            </label>
            <textarea
              ref={armReasonInputRef}
              id="arm-reason"
              value={pendingArmRequest?.payload.reason ?? armReason}
              onChange={(event) => setArmReason(event.target.value)}
              readOnly={Boolean(pendingArmRequest)}
              rows={3}
              className="mt-2 w-full rounded-lg border border-border-subtle bg-surface-lowest px-3 py-2 text-sm text-content outline-none focus:border-brand read-only:opacity-65"
            />

            <label
              className="mt-4 block text-xs font-semibold text-content-secondary"
              htmlFor="arm-confirmation"
            >
              확인 문구: ENABLE_LIVE_ORDERS
            </label>
            <input
              id="arm-confirmation"
              value={pendingArmRequest?.payload.confirmation ?? armConfirmation}
              onChange={(event) => setArmConfirmation(event.target.value)}
              readOnly={Boolean(pendingArmRequest)}
              autoComplete="off"
              className="mt-2 w-full rounded-lg border border-border-subtle bg-surface-lowest px-3 py-2 font-mono text-sm text-content outline-none focus:border-brand read-only:opacity-65"
            />

            <p className="mt-3 break-all font-mono text-[11px] text-content-muted">
              Idempotency-Key: {pendingArmRequest?.idempotencyKey ?? '제출 시 UUID v4 생성'}
            </p>

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              {pendingArmRequest && (
                <button
                  type="button"
                  onClick={() => {
                    if (
                      window.confirm(
                        '응답이 유실된 기존 요청 키를 폐기하고 새 요청을 작성하시겠습니까?',
                      )
                    ) {
                      setPendingArmRequest(null)
                      setArmReason('')
                      setArmConfirmation('')
                    }
                  }}
                  className="mr-auto rounded-lg px-3 py-2 text-xs font-semibold text-warning hover:bg-warning/10"
                >
                  새 요청 작성
                </button>
              )}
              <button
                type="button"
                onClick={() => setIsArmFormOpen(false)}
                disabled={activeAction === 'arm'}
                className="rounded-lg px-3 py-2 text-sm font-semibold text-content-secondary hover:bg-surface-high disabled:opacity-50"
              >
                닫기
              </button>
              <button
                type="submit"
                aria-busy={activeAction === 'arm'}
                disabled={
                  activeAction === 'arm' ||
                  (!pendingArmRequest &&
                    (armReason.trim().replace(/\s+/g, ' ').length < 10 ||
                      armConfirmation !== 'ENABLE_LIVE_ORDERS'))
                }
                className="inline-flex items-center gap-2 rounded-lg bg-brand/18 px-3 py-2 text-sm font-bold text-brand-bright hover:bg-brand/26 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {activeAction === 'arm' && <Loader2 className="h-4 w-4 animate-spin" />}
                {pendingArmRequest ? '동일 키로 재시도' : '재무장 승인'}
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>

    </aside>
  )
}

export default BotControlPanel
