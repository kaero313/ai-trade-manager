import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
})

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

export interface BotStatus {
  running: boolean
  last_heartbeat: string | null
  last_error: string | null
  latest_action: string | null
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
}

export interface SystemConfigUpdateItem {
  config_key: string
  config_value: string
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

export async function startBot(): Promise<BotStatus> {
  const { data } = await apiClient.post<BotStatus>('/bot/start')
  return data
}

export async function stopBot(): Promise<BotStatus> {
  const { data } = await apiClient.post<BotStatus>('/bot/stop')
  return data
}

export async function getBotConfig(): Promise<BotConfig> {
  const { data } = await apiClient.get<BotConfig>('/config')
  return data
}

export async function updateBotConfig(config: BotConfig): Promise<BotConfig> {
  const { data } = await apiClient.post<BotConfig>('/config', config)
  return data
}

export async function liquidateAll(): Promise<void> {
  await apiClient.post('/bot/liquidate')
}

export async function getMarketSentiment(): Promise<MarketSentimentSnapshot> {
  const { data } = await apiClient.get<MarketSentimentSnapshot>('/markets/sentiment')
  return data
}

export async function getLatestAiAnalysis(symbol: string): Promise<LatestAiAnalysis | null> {
  const { data } = await apiClient.get<LatestAiAnalysis | null>('/ai/latest-analysis', {
    params: { symbol },
  })
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
  const { data } = await apiClient.put<SystemConfigItem[]>('/system/configs', items)
  return data
}

export async function getAiProviderRuntimeStatus(): Promise<AiProviderRuntimeStatusResponse> {
  const { data } = await apiClient.get<AiProviderRuntimeStatusResponse>(
    '/system/ai/providers/status',
  )
  return data
}

export async function resetPaperTradingState(): Promise<PaperTradingResetResponse> {
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
      },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    })

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
