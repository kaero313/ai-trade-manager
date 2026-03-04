import { apiClient } from '../services/api'

export interface MarketItem {
  market: string
  korean_name: string
  english_name: string
}

export interface FavoriteItem {
  id: number
  symbol: string
  broker: string
  created_at: string
}

export interface TickerItem {
  symbol: string
  current_price: number
  signed_change_rate: number
  acc_trade_price_24h: number
}

export async function fetchMarkets(): Promise<MarketItem[]> {
  const { data } = await apiClient.get<MarketItem[]>('/markets/')
  return data
}

export async function fetchFavorites(): Promise<FavoriteItem[]> {
  const { data } = await apiClient.get<FavoriteItem[]>('/favorites/')
  return data
}

export async function addFavorite(symbol: string, broker = 'UPBIT'): Promise<FavoriteItem> {
  const normalized = String(symbol).trim().toUpperCase()
  const { data } = await apiClient.post<FavoriteItem>('/favorites/', {
    symbol: normalized,
    broker,
  })
  return data
}

export async function removeFavorite(symbol: string): Promise<void> {
  const normalized = String(symbol).trim().toUpperCase()
  await apiClient.delete(`/favorites/${encodeURIComponent(normalized)}`)
}

export async function fetchTickers(symbols: string[]): Promise<TickerItem[]> {
  const normalized = symbols.map((symbol) => String(symbol).trim().toUpperCase()).filter(Boolean)
  if (normalized.length === 0) {
    return []
  }

  const params = new URLSearchParams({ symbols: normalized.join(',') })
  const { data } = await apiClient.get<TickerItem[]>(`/markets/tickers?${params.toString()}`)
  return data
}
