import { apiClient } from './api'

export type BacktestTimeframe = '60m' | '240m' | 'days'

export interface BacktestRunRequest {
  market: string
  start_date: string
  end_date: string
  timeframe: BacktestTimeframe
  initial_balance: number
  grid_upper_bound: number
  grid_lower_bound: number
  grid_order_krw: number
  grid_sell_pct: number
  grid_cooldown_seconds: number
}

export interface BacktestSummary {
  total_return_pct: number
  max_drawdown_pct: number
  win_rate: number
  number_of_trades: number
}

export interface BacktestCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface BacktestMarker {
  time: number
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square'
  color: string
  text: string
  side: 'buy' | 'sell'
  price: number
  qty: number
}

export interface BacktestTrade {
  index: number
  timestamp: string
  side: string
  price: number
  qty: number
  fee: number
  krw_balance: number
  coin_balance: number
}

export interface BacktestMeta {
  market: string
  timeframe: string
  start_date: string
  end_date: string
  bars_processed: number
  last_timestamp: string
  initial_balance: number
  final_balance: number
  position_qty: number
}

export interface BacktestRunResponse {
  summary: BacktestSummary
  candles: BacktestCandle[]
  markers: BacktestMarker[]
  trades: BacktestTrade[]
  meta: BacktestMeta
}

export async function runBacktest(payload: BacktestRunRequest): Promise<BacktestRunResponse> {
  const { data } = await apiClient.post<BacktestRunResponse>('/backtest/run', payload)
  return data
}
