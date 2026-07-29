import axios, { AxiosHeaders } from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const ADMIN_TOKEN_STORAGE_KEY = 'ai-trade-manager-admin-token'

export const ADMIN_TOKEN_REQUIRED_EVENT = 'ai-trade-manager:admin-token-required'
export const ADMIN_SESSION_INVALIDATED_EVENT = 'ai-trade-manager:admin-session-invalidated'

export interface AdminTokenRequestDetail {
  reason: string
  persistent: boolean
  resolve: (token: string) => void
  reject: (error: Error) => void
}

export interface AdminTokenRequestOptions {
  forcePrompt?: boolean
  persistent?: boolean
}

let pendingAdminSessionPromise: Promise<void> | null = null

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
})

export function getStoredAdminToken(): string | null {
  if (typeof window === 'undefined') {
    return null
  }

  const token = window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim()
  return token || null
}

export function storeAdminToken(token: string): void {
  if (typeof window === 'undefined') {
    return
  }

  const normalizedToken = token.trim()
  if (!normalizedToken) {
    window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
    return
  }

  window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, normalizedToken)
}

export function clearAdminToken(): void {
  if (typeof window === 'undefined') {
    return
  }

  window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY)
}

export function invalidateAdminSession(): void {
  clearAdminToken()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(ADMIN_SESSION_INVALIDATED_EVENT))
  }
}

function invalidateAdminSessionForToken(rejectedToken: string): boolean {
  const storedToken = getStoredAdminToken()
  if (storedToken === null || rejectedToken !== storedToken) {
    return false
  }

  invalidateAdminSession()
  return true
}

export async function requestAdminToken(
  reason: string,
  options: AdminTokenRequestOptions = {},
): Promise<string> {
  const forcePrompt = options.forcePrompt ?? false
  const persistent = options.persistent ?? true
  const storedToken = forcePrompt ? null : getStoredAdminToken()
  if (storedToken !== null) {
    return storedToken
  }

  if (typeof window === 'undefined') {
    throw new Error('관리 토큰을 입력할 수 있는 브라우저 환경이 아닙니다.')
  }

  return new Promise((resolve, reject) => {
    window.dispatchEvent(
      new CustomEvent<AdminTokenRequestDetail>(ADMIN_TOKEN_REQUIRED_EVENT, {
        detail: { reason, persistent, resolve, reject },
      }),
    )
  })
}

export async function validateAdminSession(adminToken: string): Promise<void> {
  await apiClient.get('/admin/session', {
    headers: {
      'X-Admin-Token': adminToken,
    },
    timeout: 6000,
  })
}

async function establishAdminSession(): Promise<void> {
  const storedToken = getStoredAdminToken()
  if (storedToken !== null) {
    try {
      await validateAdminSession(storedToken)
      return
    } catch (error) {
      const status = axios.isAxiosError(error) ? error.response?.status : null
      if (status !== 401 && status !== 403) {
        throw error
      }
      // 인증 거절일 때만 저장 토큰을 버리고 한 번 다시 입력받습니다.
      invalidateAdminSessionForToken(storedToken)
    }
  }

  const promptedToken = await requestAdminToken('관리 화면 접근', {
    forcePrompt: storedToken !== null,
    persistent: true,
  })
  await validateAdminSession(promptedToken)
}

export function ensureAdminSession(): Promise<void> {
  if (pendingAdminSessionPromise !== null) {
    return pendingAdminSessionPromise
  }

  pendingAdminSessionPromise = establishAdminSession().finally(() => {
    pendingAdminSessionPromise = null
  })
  return pendingAdminSessionPromise
}

apiClient.interceptors.request.use((config) => {
  const token = getStoredAdminToken()
  if (token) {
    const headers = AxiosHeaders.from(config.headers)
    if (!headers.has('X-Admin-Token')) {
      headers.set('X-Admin-Token', token)
    }
    config.headers = headers
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status
      if (status === 401 || status === 403) {
        const rejectedToken = AxiosHeaders.from(error.config?.headers).get('X-Admin-Token')
        if (typeof rejectedToken === 'string') {
          invalidateAdminSessionForToken(rejectedToken)
        }
      }
    }
    return Promise.reject(error)
  },
)

export interface StrategyParams {
  ema_fast: number
  ema_slow: number
  rsi: number
  rsi_min: number
  trailing_stop_pct: number
}

export interface RiskParams {
  max_capital_pct: number
  max_daily_loss_pct: number
  position_size_pct: number
  max_concurrent_positions: number
  cooldown_minutes: number
}

export interface ScheduleParams {
  enabled: boolean
  start_hour: number | null
  end_hour: number | null
}

export interface BotConfig {
  symbols?: string[]
  allocation_pct_per_symbol?: number[]
  strategy?: StrategyParams
  risk?: RiskParams
  schedule?: ScheduleParams
  trade_mode?: string
}

export type LiveOrderMode = 'ARMED' | 'EXIT_ONLY' | 'BLOCK_ALL'

export interface LiveOrderGateStatus {
  mode: LiveOrderMode
  generation: number
  version: number
  reason_code: string
  reason: string
  source: string
  changed_at: string | null
  active_liquidation_operation_id: number | null
  rollout_enabled: boolean
  state_available: boolean
}

export interface BotStatus {
  running: boolean
  last_heartbeat: string | null
  last_error: string | null
  latest_action: string | null
  live_order_mode: LiveOrderMode
  live_order_generation: number
  live_order_version: number
  live_order_reason_code: string
  live_order_reason: string
  live_order_source: string
  live_order_changed_at: string | null
  live_order_active_liquidation_operation_id: number | null
  live_order_liquidation_status?: string | null
  live_order_liquidation_phase?: string | null
  live_order_liquidation_remaining?: number | null
  live_order_rollout_enabled: boolean
  live_order_state_available: boolean
  trading_mode: TradingMode
  trading_mode_version: number
  trading_mode_reason_code: string
  trading_mode_reason: string
  trading_mode_source: string
  trading_mode_actor_ref: string | null
  trading_mode_changed_at: string | null
  trading_mode_state_available: boolean
  trading_mode_mirror_consistent: boolean
  trading_mode_unavailable_reason: string | null
}

export interface TradingModeStatus {
  mode: TradingMode
  version: number
  reason_code: string
  reason: string
  source: string
  actor_ref: string | null
  changed_at: string | null
  state_available: boolean
  mirror_consistent: boolean
  unavailable_reason: string | null
}

export interface AdminReauthRequest {
  purpose: 'ENABLE_LIVE_TRADING'
}

export interface AdminReauthResponse {
  reauth_proof: string
  expires_at: string
}

export interface EnableLiveTradingRequest {
  expected_version: number
  expected_gate_generation: number
  expected_gate_version: number
  reason: string
  confirmation: 'ENABLE_LIVE_TRADING'
  reauth_proof: string
}

export interface EnablePaperTradingRequest {
  expected_version: number
  reason: string
}

export interface ArmLiveOrderGateRequest {
  expected_generation: number
  expected_version: number
  reason: string
  confirmation: 'ENABLE_LIVE_ORDERS'
}

export interface BlockLiveOrderGateRequest {
  reason: string
}

export type LiquidationOperationStatus =
  | 'PREPARING'
  | 'IN_PROGRESS'
  | 'COMPLETED'
  | 'PARTIAL'
  | 'FAILED'
  | 'NO_ASSETS'

export type LiquidationOperationPhase =
  | 'BLOCKING'
  | 'DISCOVERING_ORDERS'
  | 'CANCELING_ORDERS'
  | 'RECONCILING_CANCELED_ORDERS'
  | 'SNAPSHOTTING_TARGETS'
  | 'SUBMITTING'
  | 'WAITING_FILLS'
  | 'VERIFYING'
  | 'TERMINAL'

export type LiquidationVerificationStatus =
  | 'PENDING'
  | 'VERIFIED'
  | 'ERROR'
  | 'LEGACY_UNVERIFIED'

export type LiquidationResultCode =
  | 'LIQUIDATED'
  | 'DUST_REMAINING'
  | 'LOCKED_REMAINING'
  | 'UNSUPPORTED_MARKET'
  | 'ORDER_FAILED'
  | 'VERIFY_FAILED'
  | 'LEDGER_MISMATCH'

export interface LiquidationOperationSummary {
  discovered_orders?: number
  cancel_confirmed?: number
  cancel_unknown?: number
  attempted?: number
  succeeded?: number
  failed?: number
  remaining?: number
}

export interface LiquidationCancellationItem {
  exchange_uuid: string
  identifier?: string | null
  market?: string | null
  side?: string | null
  ownership?: 'MANAGED' | 'EXTERNAL' | string | null
  status?: string | null
  attempt_count?: number
  executed_volume?: string | null
  remaining_volume?: string | null
  error_code?: string | null
  error_message?: string | null
}

export interface LiquidationOperationItem {
  currency?: string | null
  market: string
  requested_volume?: string | null
  intent_id: number | null
  identifier: string | null
  exchange_uuid: string | null
  submission_status: string | null
  exchange_state: string | null
  projection_status: string | null
  executed_volume: string | null
  remaining_volume: string | null
  initial_balance?: string | null
  initial_locked?: string | null
  post_cancel_balance?: string | null
  post_cancel_locked?: string | null
  final_balance?: string | null
  final_locked?: string | null
  estimated_value_krw?: string | null
  result_code?: LiquidationResultCode | string | null
  error_code: string | null
  error_message?: string | null
}

export interface LiquidationOperation {
  id: number
  idempotency_key: string
  status: LiquidationOperationStatus
  contract_version?: number
  cancel_scope?: 'ACCOUNT_ALL' | 'LEGACY_NONE' | string | null
  phase?: LiquidationOperationPhase | string | null
  verification_status?: LiquidationVerificationStatus | string | null
  summary?: LiquidationOperationSummary | null
  cancellations?: LiquidationCancellationItem[]
  items: LiquidationOperationItem[]
  initial_accounts_observed_at?: string | null
  post_cancel_accounts_observed_at?: string | null
  final_accounts_observed_at?: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface LiquidationRequest {
  scope: 'ACCOUNT_ALL'
  confirmation: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL'
}

export interface LatestAiAnalysis {
  id: number
  symbol: string
  decision: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  recommended_weight: number
  reasoning: string
  accuracy_label?: string | null
  actual_price_diff_pct?: number | null
  created_at: string
}

export interface ManualAiCycleResponse {
  symbol: string
  analysis: LatestAiAnalysis
  trade_evaluated: boolean
  order_created: boolean
  order_id: number | null
  order_intent_id: number | null
  order_side: 'BUY' | 'SELL' | null
  submission_status: string | null
  exchange_state: string | null
  message: string
  started_at: string
  finished_at: string
}

export interface AITradeRecord {
  symbol: string
  side: 'BUY' | 'SELL'
  price: number
  qty: number
  confidence: number
  decision: 'BUY' | 'SELL' | 'HOLD'
  executed_at: string
}

export interface AIPerformanceSummary {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  accuracy_rate: number
  total_realized_pnl_krw: number
  avg_confidence: number
  recent_trades: AITradeRecord[]
}

export type TradingMode = 'live' | 'paper'

export interface MarketSentimentSnapshot {
  score: number
  classification: string
  updated_at: string
}

export interface SystemConfigItem {
  id: number
  config_key: string
  config_value: string
  description: string | null
  version: number
}

export interface SystemConfigUpdateItem {
  config_key: string
  config_value: string
  expected_version: number
}

export type AiProviderRuntimeStatusKind =
  | 'active'
  | 'fallback_ready'
  | 'ready'
  | 'blocked'
  | 'disabled'
  | 'missing_key'
  | 'error'

export interface AiProviderRuntimeStatusItem {
  provider: 'gemini' | 'openai'
  rank: number
  enabled: boolean
  model: string
  models: Record<string, string>
  api_key_configured: boolean
  status: AiProviderRuntimeStatusKind
  is_candidate: boolean
  skip_reason: string | null
  blocked_until: string | null
  reason: string | null
  last_error_at: string | null
  last_error: string | null
  last_success_at: string | null
}

export interface AiProviderRuntimeStatusResponse {
  generated_at: string
  active_provider: 'gemini' | 'openai' | null
  providers: AiProviderRuntimeStatusItem[]
}

export interface PaperTradingResetResponse {
  message: string
  deleted_order_history_count: number
  deleted_position_count: number
  paper_trading_krw_balance: string
}

export interface ChatSession {
  session_id: string
  last_message_preview: string
  last_activity: string
}

export interface ChatMessage {
  id: number
  session_id: string
  role: string
  content: string
  agent_name: string | null
  is_tool_call: boolean
  created_at: string
}

export interface ChatStreamEvent {
  type: string
  agent_name: string
  content: string
}

export interface ApprovalPayload {
  config_key: string
  config_value: string
  expected_version: number
}

export type ChatSessionSurface = 'ai_banker' | 'portfolio'

interface ChatSessionCreateRequest {
  surface: ChatSessionSurface
}

interface ChatSessionCreateResponse {
  session_id: string
}

interface ChatSessionApiItem {
  session_id: string
  created_at: string
  content_preview: string
}

function mapChatSession(item: ChatSessionApiItem): ChatSession {
  return {
    session_id: item.session_id,
    last_message_preview: item.content_preview,
    last_activity: item.created_at,
  }
}

async function buildStreamError(response: Response): Promise<Error> {
  const fallbackMessage = `채팅 스트림 요청에 실패했습니다. (${response.status})`
  const rawBody = (await response.text()).trim()
  if (!rawBody) {
    return new Error(fallbackMessage)
  }

  try {
    const parsed = JSON.parse(rawBody) as { detail?: string }
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
      return new Error(parsed.detail)
    }
  } catch {
    return new Error(rawBody)
  }

  return new Error(fallbackMessage)
}

export async function getBotStatus(): Promise<BotStatus> {
  const { data } = await apiClient.get<BotStatus>('/status', {
    timeout: 6000,
  })
  return data
}

export async function getTradingMode(): Promise<TradingModeStatus> {
  await requestAdminToken('거래 모드 상태 조회')
  const { data } = await apiClient.get<TradingModeStatus>('/bot/trading-mode', {
    timeout: 6000,
  })
  return data
}

export async function reauthAdminForLiveTrading(
  adminToken: string,
): Promise<AdminReauthResponse> {
  const payload: AdminReauthRequest = {
    purpose: 'ENABLE_LIVE_TRADING',
  }
  const { data } = await apiClient.post<AdminReauthResponse>('/admin/reauth', payload, {
    headers: {
      'X-Admin-Token': adminToken,
    },
  })
  return data
}

export async function enableLiveTrading(
  payload: EnableLiveTradingRequest,
  idempotencyKey: string,
  adminToken: string,
): Promise<TradingModeStatus> {
  const { data } = await apiClient.post<TradingModeStatus>('/bot/trading-mode/live', payload, {
    headers: {
      'Idempotency-Key': idempotencyKey,
      'X-Admin-Token': adminToken,
    },
  })
  return data
}

export async function enablePaperTrading(
  payload: EnablePaperTradingRequest,
  idempotencyKey: string,
): Promise<TradingModeStatus> {
  await requestAdminToken('paper 거래 모드 전환')
  const { data } = await apiClient.post<TradingModeStatus>('/bot/trading-mode/paper', payload, {
    headers: {
      'Idempotency-Key': idempotencyKey,
    },
  })
  return data
}

export async function startBot(): Promise<BotStatus> {
  await requestAdminToken('봇 가동')
  const { data } = await apiClient.post<BotStatus>('/bot/start')
  return data
}

export async function stopBot(): Promise<BotStatus> {
  await requestAdminToken('봇 정지')
  const { data } = await apiClient.post<BotStatus>('/bot/stop')
  return data
}

export async function getLiveOrderGate(): Promise<LiveOrderGateStatus> {
  await requestAdminToken('실주문 Gate 상태 조회')
  const { data } = await apiClient.get<LiveOrderGateStatus>('/bot/order-gate')
  return data
}

export async function armLiveOrderGate(
  payload: ArmLiveOrderGateRequest,
  idempotencyKey: string,
): Promise<LiveOrderGateStatus> {
  await requestAdminToken('실주문 Gate 재무장')
  const { data } = await apiClient.post<LiveOrderGateStatus>('/bot/order-gate/arm', payload, {
    headers: {
      'Idempotency-Key': idempotencyKey,
    },
  })
  return data
}

export async function blockLiveOrderGate(
  payload: BlockLiveOrderGateRequest,
  idempotencyKey: string,
): Promise<LiveOrderGateStatus> {
  await requestAdminToken('실주문 Gate 즉시 차단')
  const { data } = await apiClient.post<LiveOrderGateStatus>('/bot/order-gate/block', payload, {
    headers: {
      'Idempotency-Key': idempotencyKey,
    },
  })
  return data
}

export async function getBotConfig(): Promise<BotConfig> {
  const { data } = await apiClient.get<BotConfig>('/config')
  return data
}

export async function liquidateAll(
  idempotencyKey: string,
  payload: LiquidationRequest,
): Promise<LiquidationOperation> {
  await requestAdminToken('전량 롤백')
  const { data } = await apiClient.post<LiquidationOperation>('/bot/liquidate', payload, {
    headers: {
      'Idempotency-Key': idempotencyKey,
    },
  })
  return data
}

export async function getLiquidation(id: number): Promise<LiquidationOperation> {
  await requestAdminToken('전량 롤백 상태 조회')
  const { data } = await apiClient.get<LiquidationOperation>(`/bot/liquidations/${id}`)
  return data
}

export async function getMarketSentiment(): Promise<MarketSentimentSnapshot> {
  const { data } = await apiClient.get<MarketSentimentSnapshot>('/markets/sentiment')
  return data
}

export async function getLatestAiAnalysis(symbol: string): Promise<LatestAiAnalysis | null> {
  const { data } = await apiClient.get<LatestAiAnalysis | null>('/ai/latest-analysis', {
    params: { symbol },
    timeout: 6000,
  })
  return data
}

export async function runManualAiCycle(
  symbol: string,
  confirmTradeExecution = true,
): Promise<ManualAiCycleResponse> {
  await requestAdminToken('수동 AI Cycle')
  const { data } = await apiClient.post<ManualAiCycleResponse>(
    '/ai/manual-cycle',
    {
      symbol,
      confirm_trade_execution: confirmTradeExecution,
    },
    {
      timeout: 120000,
    },
  )
  return data
}

export async function fetchAIPerformance(): Promise<AIPerformanceSummary> {
  const { data } = await apiClient.get<AIPerformanceSummary>('/ai/performance')
  return data
}

export async function getSystemConfigs(): Promise<SystemConfigItem[]> {
  const { data } = await apiClient.get<SystemConfigItem[]>('/system/configs')
  return data
}

export async function updateSystemConfigs(
  items: SystemConfigUpdateItem[],
): Promise<SystemConfigItem[]> {
  await requestAdminToken('AI 운용 설정 저장')
  const { data } = await apiClient.put<SystemConfigItem[]>('/system/configs', items)
  return data
}

export async function getAiProviderRuntimeStatus(): Promise<AiProviderRuntimeStatusResponse> {
  const { data } = await apiClient.get<AiProviderRuntimeStatusResponse>(
    '/system/ai/providers/status',
  )
  return data
}

export async function resetAiProviderStatus(expectedVersion: number): Promise<SystemConfigItem> {
  await requestAdminToken('AI provider 차단 상태 초기화')
  const { data } = await apiClient.post<SystemConfigItem>(
    '/system/ai/providers/status/reset',
    { expected_version: expectedVersion },
  )
  return data
}

export async function resetPaperTradingState(): Promise<PaperTradingResetResponse> {
  await requestAdminToken('모의투자 상태 초기화')
  const { data } = await apiClient.post<PaperTradingResetResponse>('/system/paper/reset')
  return data
}

export async function createChatSession(
  surface: ChatSessionSurface = 'ai_banker',
): Promise<ChatSessionCreateResponse> {
  const payload: ChatSessionCreateRequest = { surface }
  const { data } = await apiClient.post<ChatSessionCreateResponse>('/chat/sessions', payload)
  return data
}

export async function getChatSessions(
  surface: ChatSessionSurface = 'ai_banker',
): Promise<ChatSession[]> {
  const { data } = await apiClient.get<ChatSessionApiItem[]>('/chat/sessions', {
    params: { surface },
  })
  return data.map(mapChatSession)
}

export async function getChatMessages(sessionId: string): Promise<ChatMessage[]> {
  const { data } = await apiClient.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`)
  return data
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${sessionId}`)
}

export async function approveChatConfigChange(
  sessionId: string,
  payload: ApprovalPayload,
): Promise<SystemConfigItem[]> {
  await requestAdminToken('AI Banker 설정 변경 승인')
  const { data } = await apiClient.post<SystemConfigItem[]>(
    `/chat/sessions/${sessionId}/approve`,
    payload,
  )
  return data
}

export async function streamChatMessage(
  sessionId: string,
  content: string,
  onEvent: (event: ChatStreamEvent) => void,
  options?: { timeoutMs?: number },
): Promise<void> {
  const adminToken = getStoredAdminToken()
  if (adminToken === null) {
    throw new Error('관리자 인증이 만료되었습니다. 다시 인증해 주세요.')
  }

  const controller = new AbortController()
  const timeoutId =
    typeof options?.timeoutMs === 'number' && Number.isFinite(options.timeoutMs)
      ? window.setTimeout(() => controller.abort(), options.timeoutMs)
      : null
  const clearStreamTimeout = () => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId)
    }
  }
  try {
    const response = await fetch(`${API_BASE_URL}/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        'X-Admin-Token': adminToken,
      },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    })

    if (response.status === 401 || response.status === 403) {
      invalidateAdminSessionForToken(adminToken)
    }

    if (!response.ok) {
      throw await buildStreamError(response)
    }

    if (!response.body) {
      throw new Error('채팅 스트림 응답 본문이 비어 있습니다.')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let pendingDataLines: string[] = []

    const emitPendingEvent = () => {
      if (pendingDataLines.length === 0) {
        return
      }

      const payload = pendingDataLines.join('\n').trim()
      pendingDataLines = []

      if (!payload) {
        return
      }

      onEvent(JSON.parse(payload) as ChatStreamEvent)
    }

    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })

      let newlineIndex = buffer.indexOf('\n')
      while (newlineIndex !== -1) {
        const rawLine = buffer.slice(0, newlineIndex)
        buffer = buffer.slice(newlineIndex + 1)

        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
        if (line === '') {
          emitPendingEvent()
        } else if (line.startsWith('data:')) {
          pendingDataLines.push(line.slice(5).trimStart())
        }

        newlineIndex = buffer.indexOf('\n')
      }

      if (done) {
        const remainingLine = buffer.endsWith('\r') ? buffer.slice(0, -1) : buffer
        if (remainingLine.startsWith('data:')) {
          pendingDataLines.push(remainingLine.slice(5).trimStart())
        }
        emitPendingEvent()
        break
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('AI 응답이 지연되어 요청을 종료했습니다. 잠시 후 다시 시도해 주세요.')
    }

    throw error
  } finally {
    clearStreamTimeout()
  }
}
