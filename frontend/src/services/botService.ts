import { apiClient } from './api'

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

export interface GridParams {
  target_coin: string
  grid_upper_bound: number
  grid_lower_bound: number
  grid_order_krw: number
  grid_sell_pct: number
  grid_cooldown_seconds: number
  trade_mode: string
}

export interface BotConfig {
  symbols?: string[]
  allocation_pct_per_symbol?: number[]
  strategy?: StrategyParams
  risk?: RiskParams
  schedule?: ScheduleParams
  grid?: GridParams
}

export interface BotStatus {
  running: boolean
  last_heartbeat: string | null
  last_error: string | null
}

export async function fetchConfig(): Promise<BotConfig> {
  const { data } = await apiClient.get<BotConfig>('/config')
  return data
}

export async function updateConfig(config: BotConfig): Promise<BotConfig> {
  const { data } = await apiClient.post<BotConfig>('/config', config)
  return data
}

export async function getBotStatus(): Promise<BotStatus> {
  const { data } = await apiClient.get<BotStatus>('/status')
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

export async function liquidateAll(): Promise<void> {
  await apiClient.post('/bot/liquidate')
}
