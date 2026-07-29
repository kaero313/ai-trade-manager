import type { AssetItem, PortfolioSummary } from '../services/portfolioService'

export type PortfolioDataStateKind =
  | 'live'
  | 'snapshot'
  | 'cached-refetch-error'
  | 'empty'
  | 'hard-error'
  | 'loading'

export interface PortfolioDataStateInput {
  data: PortfolioSummary | null | undefined
  error?: unknown
  isError: boolean
  isLoading: boolean
  isRefetchError?: boolean
}

export interface PortfolioDataState {
  kind: PortfolioDataStateKind
  portfolio: PortfolioSummary | null
  canDisplayAmounts: boolean
  canUseAiContext: boolean
  isStale: boolean
  source: PortfolioSummary['source'] | null
  updatedAt: string | null
  errorCode: string | null
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isValidAsset(item: AssetItem): boolean {
  return (
    typeof item.currency === 'string' &&
    item.currency.trim().length > 0 &&
    isFiniteNumber(item.balance) &&
    item.balance >= 0 &&
    isFiniteNumber(item.locked) &&
    item.locked >= 0 &&
    isFiniteNumber(item.avg_buy_price) &&
    item.avg_buy_price >= 0 &&
    isFiniteNumber(item.current_price) &&
    item.current_price >= 0 &&
    isFiniteNumber(item.total_value) &&
    item.total_value >= 0 &&
    isFiniteNumber(item.pnl_percentage)
  )
}

function hasDisplayablePortfolioData(data: PortfolioSummary): boolean {
  return (
    (data.source === 'live' || data.source === 'snapshot') &&
    isFiniteNumber(data.total_net_worth) &&
    data.total_net_worth >= 0 &&
    isFiniteNumber(data.total_pnl) &&
    Array.isArray(data.items) &&
    data.items.every(isValidAsset)
  )
}

function normalizeErrorCode(dataError: string | null | undefined, queryError: unknown): string | null {
  const normalizedDataError = String(dataError ?? '').trim()
  if (normalizedDataError) {
    return normalizedDataError
  }

  if (queryError instanceof Error) {
    const normalizedMessage = queryError.message.trim()
    return normalizedMessage || 'PORTFOLIO_FETCH_FAILED'
  }

  if (typeof queryError === 'string' && queryError.trim()) {
    return queryError.trim()
  }

  return null
}

export function resolvePortfolioDataState({
  data,
  error,
  isError,
  isLoading,
  isRefetchError = false,
}: PortfolioDataStateInput): PortfolioDataState {
  if (!data) {
    if (isLoading && !isError) {
      return {
        kind: 'loading',
        portfolio: null,
        canDisplayAmounts: false,
        canUseAiContext: false,
        isStale: false,
        source: null,
        updatedAt: null,
        errorCode: null,
      }
    }

    return {
      kind: 'hard-error',
      portfolio: null,
      canDisplayAmounts: false,
      canUseAiContext: false,
      isStale: false,
      source: null,
      updatedAt: null,
      errorCode: normalizeErrorCode(null, error) ?? 'PORTFOLIO_UNAVAILABLE',
    }
  }

  const errorCode = normalizeErrorCode(data.error, error)

  if (data.source === 'empty') {
    return {
      kind: 'empty',
      portfolio: data,
      canDisplayAmounts: false,
      canUseAiContext: false,
      isStale: Boolean(data.is_stale),
      source: data.source,
      updatedAt: data.updated_at,
      errorCode,
    }
  }

  if (!hasDisplayablePortfolioData(data)) {
    return {
      kind: 'hard-error',
      portfolio: null,
      canDisplayAmounts: false,
      canUseAiContext: false,
      isStale: false,
      source: null,
      updatedAt: data.updated_at,
      errorCode: errorCode ?? 'PORTFOLIO_INVALID_DATA',
    }
  }

  const hasCachedRefreshError = isRefetchError || isError
  const kind: PortfolioDataStateKind =
    data.source === 'snapshot'
      ? 'snapshot'
      : hasCachedRefreshError || data.is_stale || Boolean(errorCode)
        ? 'cached-refetch-error'
        : 'live'

  return {
    kind,
    portfolio: data,
    canDisplayAmounts: true,
    canUseAiContext: true,
    isStale: data.source === 'snapshot' || Boolean(data.is_stale) || hasCachedRefreshError,
    source: data.source,
    updatedAt: data.updated_at,
    errorCode,
  }
}

export function resolvePortfolioUnavailableMessage(state: PortfolioDataState): string {
  if (state.kind === 'empty') {
    return '실시간 계좌 조회와 저장된 스냅샷을 모두 확보하지 못했습니다. 실제 0원으로 확정된 상태가 아니므로 금액과 AI 분석을 표시하지 않습니다.'
  }

  const normalizedError = String(state.errorCode ?? '').toUpperCase()
  if (normalizedError.includes('IP')) {
    return '허용된 IP에서 계좌 정보를 조회할 수 없습니다. Upbit API 허용 IP를 확인해 주세요.'
  }
  if (normalizedError.includes('KEY')) {
    return '거래소 API 키 상태를 확인할 수 없습니다. 운영 환경의 키 설정을 확인해 주세요.'
  }
  if (normalizedError.includes('AUTH') || normalizedError.includes('401')) {
    return '거래소 인증 상태를 확인할 수 없습니다. 인증 설정을 확인한 뒤 다시 시도해 주세요.'
  }
  if (normalizedError.includes('INVALID_DATA')) {
    return '계좌 응답의 숫자 형식이 올바르지 않아 금액과 AI 분석을 안전하게 숨겼습니다.'
  }

  return '계좌 정보를 확인할 수 없습니다. 조회가 복구되기 전에는 금액 표시와 AI 분석을 사용할 수 없습니다.'
}
