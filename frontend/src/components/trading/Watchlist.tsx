import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2, Star } from 'lucide-react'
import { useMemo, useState } from 'react'

import { fetchFavorites, fetchTickers, removeFavorite, type TickerItem } from '../../api/markets'

interface WatchlistProps {
  selectedSymbol?: string | null
  onSelectSymbol?: (symbol: string) => void
}

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (error.message) {
      return error.message
    }
  }
  return fallback
}

function formatPrice(value: number): string {
  return `${new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: 0,
  }).format(value)}원`
}

function formatSignedPercent(rate: number): string {
  const percent = rate * 100
  const sign = percent > 0 ? '+' : ''
  return `${sign}${percent.toFixed(2)}%`
}

function formatTradeAmount(value: number): string {
  return `${new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: 0,
  }).format(value)}원`
}

function Watchlist({ selectedSymbol = null, onSelectSymbol }: WatchlistProps) {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingSymbol, setPendingSymbol] = useState<string | null>(null)

  const favoritesQuery = useQuery({
    queryKey: ['favorites'],
    queryFn: fetchFavorites,
  })

  const symbols = useMemo(() => {
    return (favoritesQuery.data ?? []).map((item) => item.symbol.toUpperCase())
  }, [favoritesQuery.data])

  const tickerQueryKey = useMemo(() => ['watchlist-tickers', symbols.join(',')], [symbols])

  const tickersQuery = useQuery({
    queryKey: tickerQueryKey,
    queryFn: () => fetchTickers(symbols),
    enabled: symbols.length > 0,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => removeFavorite(symbol),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['favorites'] })
      await queryClient.invalidateQueries({ queryKey: ['watchlist-tickers'] })
    },
  })

  const tickerMap = useMemo(() => {
    const map = new Map<string, TickerItem>()
    for (const row of tickersQuery.data ?? []) {
      map.set(row.symbol.toUpperCase(), row)
    }
    return map
  }, [tickersQuery.data])

  const selected = selectedSymbol?.toUpperCase() ?? null

  const handleRemove = async (symbol: string) => {
    setActionError(null)
    setPendingSymbol(symbol)
    try {
      await removeMutation.mutateAsync(symbol)
    } catch (error) {
      setActionError(resolveErrorMessage(error, '관심 종목을 삭제하지 못했습니다.'))
    } finally {
      setPendingSymbol(null)
    }
  }

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="mb-4 flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">Watchlist</h2>
        <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          LIVE 3s
        </span>
      </header>

      {favoritesQuery.isLoading && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          관심 종목을 불러오는 중입니다.
        </div>
      )}

      {favoritesQuery.isError && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {resolveErrorMessage(favoritesQuery.error, '관심 종목 목록을 불러오지 못했습니다.')}
        </p>
      )}

      {!favoritesQuery.isLoading && !favoritesQuery.isError && symbols.length === 0 && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
          아직 등록된 관심 종목이 없습니다. 검색창에서 별표를 눌러 추가해 주세요.
        </p>
      )}

      {!favoritesQuery.isLoading && !favoritesQuery.isError && symbols.length > 0 && (
        <div className="space-y-2">
          {(favoritesQuery.data ?? []).map((favorite) => {
            const symbol = favorite.symbol.toUpperCase()
            const ticker = tickerMap.get(symbol)
            const changeRate = ticker?.signed_change_rate ?? 0
            const changeClass =
              changeRate > 0
                ? 'text-rose-600'
                : changeRate < 0
                  ? 'text-blue-600'
                  : 'text-slate-600'
            const isPending = pendingSymbol === symbol
            const isSelected = selected === symbol

            return (
              <article
                key={favorite.id}
                onClick={() => onSelectSymbol?.(symbol)}
                className={`cursor-pointer rounded-xl border px-3 py-2.5 transition ${
                  isSelected
                    ? 'border-emerald-300 bg-emerald-50/60 ring-1 ring-emerald-200'
                    : 'border-slate-200 bg-slate-50/60 hover:border-slate-300 hover:bg-slate-100/70'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">{symbol}</p>
                    {ticker ? (
                      <>
                        <p className="mt-0.5 text-sm text-slate-700">{formatPrice(ticker.current_price)}</p>
                        <p className={`text-xs font-semibold ${changeClass}`}>{formatSignedPercent(changeRate)}</p>
                      </>
                    ) : (
                      <p className="mt-1 text-xs text-slate-500">
                        {tickersQuery.isLoading ? '시세 로딩 중...' : '시세를 아직 가져오지 못했습니다.'}
                      </p>
                    )}
                  </div>

                  <button
                    type="button"
                    aria-label="관심 종목 삭제"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      void handleRemove(symbol)
                    }}
                    disabled={removeMutation.isPending && !isPending}
                    className="rounded-md p-1 text-amber-500 transition hover:bg-amber-50 hover:text-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
                    ) : (
                      <Star className="h-4 w-4 fill-amber-400 text-amber-500" />
                    )}
                  </button>
                </div>

                {ticker && (
                  <p className="mt-2 text-[11px] text-slate-500">24h 거래대금: {formatTradeAmount(ticker.acc_trade_price_24h)}</p>
                )}
              </article>
            )
          })}
        </div>
      )}

      {tickersQuery.isError && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {resolveErrorMessage(tickersQuery.error, '티커 시세를 불러오지 못했습니다.')}
        </p>
      )}
      {actionError && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {actionError}
        </p>
      )}
    </aside>
  )
}

export default Watchlist
