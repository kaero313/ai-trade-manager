import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2, X } from 'lucide-react'
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
    <aside className="quantum-card flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-xl p-5">
      <header className="mb-4 shrink-0 flex items-center justify-between gap-2">
        <h2 className="text-lg font-bold text-[#dfe2eb]">관심 종목</h2>
        <span className="inline-flex items-center gap-2 rounded-md bg-[#00dbe9]/10 px-2.5 py-1 text-xs font-bold text-[#00dbe9]">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#00dbe9] opacity-70" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#00dbe9]" />
          </span>
          LIVE 3s
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {favoritesQuery.isLoading && (
        <div className="rounded-lg bg-[#0a0e14]/80 px-3 py-3 text-sm text-[#849495]">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="ml-2">관심 종목을 불러오는 중입니다.</span>
        </div>
      )}

      {favoritesQuery.isError && (
        <p className="rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffb4ab]">
          {resolveErrorMessage(favoritesQuery.error, '관심 종목 목록을 불러오지 못했습니다.')}
        </p>
      )}

      {!favoritesQuery.isLoading && !favoritesQuery.isError && symbols.length === 0 && (
        <p className="rounded-lg bg-[#0a0e14]/75 px-3 py-3 text-sm leading-6 text-[#849495]">
          아직 등록된 관심 종목이 없습니다. 검색창에서 별표를 눌러 추가해 주세요.
        </p>
      )}

      {!favoritesQuery.isLoading && !favoritesQuery.isError && symbols.length > 0 && (
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <div className="grid grid-cols-2 gap-2">
          {(favoritesQuery.data ?? []).map((favorite) => {
            const symbol = favorite.symbol.toUpperCase()
            const ticker = tickerMap.get(symbol)
            const changeRate = ticker?.signed_change_rate ?? 0
            const changeClass =
              changeRate > 0
                ? 'bg-[#ffb4ab]/12 text-[#ffb4ab]'
                : changeRate < 0
                  ? 'bg-[#7df4ff]/12 text-[#7df4ff]'
                  : 'bg-[#262a31] text-[#849495]'
            const isPending = pendingSymbol === symbol
            const isSelected = selected === symbol

            return (
              <article
                key={favorite.id}
                onClick={() => onSelectSymbol?.(symbol)}
                className={`min-w-0 cursor-pointer rounded-lg p-3 transition-colors ${
                  isSelected
                    ? 'bg-[#00363a]/65 text-[#dfe2eb]'
                    : 'bg-[#262a31]/50 hover:bg-[#262a31]/80'
                }`}
              >
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-bold text-[#dfe2eb]">{symbol}</p>
                  <button
                    type="button"
                    aria-label={`${symbol} 관심 종목 삭제`}
                    title="관심 종목 삭제"
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      void handleRemove(symbol)
                    }}
                    disabled={removeMutation.isPending && !isPending}
                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[#3b494b]/80 bg-[#0a0e14]/80 text-[#849495] transition hover:border-[#ffb4ab]/55 hover:bg-[#ffb4ab]/10 hover:text-[#ffb4ab] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    ) : (
                      <X className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                  </button>
                </div>

                {ticker ? (
                  <div className="mt-3 min-w-0">
                    <p className="truncate font-mono text-sm font-semibold text-[#b9cacb]">
                      {formatPrice(ticker.current_price)}
                    </p>
                    <span
                      className={`mt-2 inline-flex rounded px-2 py-1 font-mono text-[10px] font-bold ${changeClass}`}
                    >
                      {formatSignedPercent(changeRate)}
                    </span>
                  </div>
                ) : (
                  <p className="mt-3 text-xs leading-5 text-[#849495]">
                    {tickersQuery.isLoading ? '시세 로딩 중...' : '시세 대기'}
                  </p>
                )}
              </article>
            )
          })}
          </div>
        </div>
      )}

      {tickersQuery.isError && (
        <p className="mt-3 shrink-0 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffe179]">
          {resolveErrorMessage(tickersQuery.error, '티커 시세를 불러오지 못했습니다.')}
        </p>
      )}
      {actionError && (
        <p className="mt-3 shrink-0 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffe179]">
          {actionError}
        </p>
      )}
      </div>
    </aside>
  )
}

export default Watchlist
