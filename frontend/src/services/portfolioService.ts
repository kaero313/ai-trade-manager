import { apiClient } from './api'

export interface AssetItem {
  broker: string
  currency: string
  balance: number
  locked: number
  avg_buy_price: number
  current_price: number
  total_value: number
  pnl_percentage: number
}

export interface PortfolioSummary {
  total_net_worth: number
  total_pnl: number
  items: AssetItem[]
}

export interface OrderHistoryItem {
  id: number
  position_id: number
  symbol: string
  side: string
  price: number
  qty: number
  broker: string
  executed_at: string
}

export async function getPortfolioSummary(): Promise<PortfolioSummary> {
  const { data } = await apiClient.get<PortfolioSummary>('/dashboard')
  return data
}

export async function fetchOrders(): Promise<OrderHistoryItem[]> {
  const { data } = await apiClient.get<OrderHistoryItem[]>('/orders/')
  return data
}
