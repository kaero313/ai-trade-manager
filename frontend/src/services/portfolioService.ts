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
  error?: string | null
  source: 'live' | 'snapshot' | 'empty'
  is_stale: boolean
  updated_at: string | null
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

export interface PortfolioSnapshotDataItem {
  currency: string
  balance: number
  current_price: number
  total_value: number
  pnl_percentage: number
}

export interface PortfolioSnapshotItem {
  id: number
  total_net_worth: number
  total_pnl: number
  snapshot_data: PortfolioSnapshotDataItem[]
  created_at: string
}

export interface PortfolioBriefingResponse {
  provider: string
  model: string
  report: string
  fallback: boolean
  error?: string | null
}

export interface AIAnalysisItem {
  symbol: string
  decision: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  reasoning: string
  created_at: string
}

interface PortfolioSnapshotListResponse {
  snapshots: PortfolioSnapshotItem[]
}

export async function getPortfolioSummary(): Promise<PortfolioSummary> {
  const { data } = await apiClient.get<PortfolioSummary>('/dashboard', {
    timeout: 6000,
  })
  return data
}

export async function fetchOrders(): Promise<OrderHistoryItem[]> {
  const { data } = await apiClient.get<OrderHistoryItem[]>('/orders/')
  return data
}

export async function fetchPortfolioSnapshots(limit?: number): Promise<PortfolioSnapshotItem[]> {
  const response = await apiClient.get<PortfolioSnapshotListResponse>('/portfolio/snapshots', {
    params: { limit },
  })
  return response.data.snapshots
}

export async function fetchPortfolioBriefing(): Promise<PortfolioBriefingResponse> {
  const response = await apiClient.get<PortfolioBriefingResponse>('/portfolio/briefing', {
    timeout: 60000,
  })
  return response.data
}

export async function fetchLatestAnalysisBatch(
  symbols: string[],
): Promise<Record<string, AIAnalysisItem | null>> {
  const response = await apiClient.get<Record<string, AIAnalysisItem | null>>(
    '/ai/latest-analysis-batch',
    {
      params: { symbols: symbols.join(',') },
    },
  )
  return response.data
}
