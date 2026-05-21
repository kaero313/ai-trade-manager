import { Combobox, ComboboxInput, ComboboxOption, ComboboxOptions } from '@headlessui/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Check, Loader2, Search, Star } from 'lucide-react'
import { useMemo, useState } from 'react'

import { addFavorite, fetchFavorites, fetchMarkets, removeFavorite, type MarketItem } from '../../api/markets'

interface MarketSearchBarProps {
  onSelectSymbol?: (symbol: string) => void
  compact?: boolean
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

function MarketSearchBar({ onSelectSymbol, compact = false }: MarketSearchBarProps) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [selectedMarket, setSelectedMarket] = useState<MarketItem | null>(null)
  const [pendingSymbol, setPendingSymbol] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const marketsQuery = useQuery({
    queryKey: ['markets'],
    queryFn: fetchMarkets,
    staleTime: 5 * 60 * 1000,
  })

  const favoritesQuery = useQuery({
    queryKey: ['favorites'],
    queryFn: fetchFavorites,
  })

  const addFavoriteMutation = useMutation({
    mutationFn: (symbol: string) => addFavorite(symbol),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['favorites'] })
      await queryClient.invalidateQueries({ queryKey: ['watchlist-tickers'] })
    },
  })

  const removeFavoriteMutation = useMutation({
    mutationFn: (symbol: string) => removeFavorite(symbol),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['favorites'] })
      await queryClient.invalidateQueries({ queryKey: ['watchlist-tickers'] })
    },
  })

  const favoritesSet = useMemo(() => {
    const values = favoritesQuery.data ?? []
    return new Set(values.map((item) => item.symbol.toUpperCase()))
  }, [favoritesQuery.data])

  const filteredMarkets = useMemo(() => {
    const rows = marketsQuery.data ?? []
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) {
      return rows.slice(0, 20)
    }

    return rows
      .filter((item) => {
        const symbol = item.market.toLowerCase()
        const korean = item.korean_name.toLowerCase()
        const english = item.english_name.toLowerCase()
        return (
          symbol.includes(normalizedQuery) ||
          korean.includes(normalizedQuery) ||
          english.includes(normalizedQuery)
        )
      })
      .slice(0, 20)
  }, [marketsQuery.data, query])

  const isToggling = addFavoriteMutation.isPending || removeFavoriteMutation.isPending

  const handleToggleFavorite = async (symbol: string) => {
    setActionError(null)
    setPendingSymbol(symbol)

    try {
      if (favoritesSet.has(symbol)) {
        await removeFavoriteMutation.mutateAsync(symbol)
      } else {
        await addFavoriteMutation.mutateAsync(symbol)
      }
    } catch (error) {
      setActionError(resolveErrorMessage(error, '관심 종목 상태를 변경하지 못했습니다.'))
    } finally {
      setPendingSymbol(null)
    }
  }

  return (
    <section className={compact ? 'relative min-w-0' : 'quantum-card rounded-xl px-4 py-2'}>
      <div className={compact ? 'flex min-w-0 items-center' : 'flex min-w-0 flex-col gap-2 md:flex-row md:items-center'}>
        {!compact && (
          <header className="flex shrink-0 items-center justify-between gap-3 md:min-w-[128px]">
            <h2 className="text-sm font-bold text-[#dfe2eb]">종목 검색</h2>
            <span className="rounded-md bg-[#262a31] px-2 py-1 text-[11px] font-bold text-[#b9cacb]">
              관심 {favoritesSet.size}개
            </span>
          </header>
        )}

        <Combobox
          value={selectedMarket}
          onChange={(market) => {
            setSelectedMarket(market)
            if (market) {
              setQuery(market.market)
              onSelectSymbol?.(market.market)
            }
          }}
        >
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#849495]" />
            <ComboboxInput
              placeholder="KRW-BTC, 비트코인, Ethereum"
              className={`w-full rounded-lg border border-[#3b494b]/80 bg-[#0a0e14]/75 pl-9 pr-3 text-sm text-[#dfe2eb] outline-none transition placeholder:text-[#849495] focus:border-[#00dbe9]/50 focus:ring-0 ${
                compact ? 'h-9 py-0' : 'py-1.5'
              }`}
              displayValue={(item: MarketItem | null) => item?.market ?? query}
              onChange={(event) => setQuery(event.target.value)}
            />

            <ComboboxOptions className="absolute z-50 mt-2 max-h-80 w-full overflow-y-auto rounded-lg border border-[#3b494b]/80 bg-[#0a0e14] p-1">
              {marketsQuery.isLoading && (
                <div className="flex items-center gap-2 px-3 py-3 text-sm text-[#849495]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  종목 목록을 불러오는 중입니다.
                </div>
              )}

              {!marketsQuery.isLoading && filteredMarkets.length === 0 && (
                <div className="px-3 py-3 text-sm text-[#849495]">검색 결과가 없습니다.</div>
              )}

              {!marketsQuery.isLoading &&
                filteredMarkets.map((item) => {
                  const isFavorite = favoritesSet.has(item.market)
                  const isPending = pendingSymbol === item.market

                  return (
                    <ComboboxOption
                      key={item.market}
                      value={item}
                      className={({ focus }) => `rounded-lg px-3 py-2 ${focus ? 'bg-[#181c22]' : ''}`}
                    >
                      {({ selected }) => (
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-bold text-[#dfe2eb]">{item.market}</p>
                            <p className="truncate text-xs text-[#849495]">
                              {item.korean_name || '-'} / {item.english_name || '-'}
                            </p>
                          </div>

                          <div className="flex items-center gap-1">
                            {selected && <Check className="h-4 w-4 text-[#00dbe9]" />}
                            <button
                              type="button"
                              aria-label={isFavorite ? '관심 종목 해제' : '관심 종목 추가'}
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                void handleToggleFavorite(item.market)
                              }}
                              disabled={isToggling && !isPending}
                              className="rounded-md p-1 text-[#849495] transition hover:bg-[#262a31] hover:text-[#dfe2eb] disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {isPending ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Star
                                  className={`h-4 w-4 ${isFavorite ? 'fill-[#ffe179] text-[#ffe179]' : 'text-[#849495]'}`}
                                />
                              )}
                            </button>
                          </div>
                        </div>
                      )}
                    </ComboboxOption>
                  )
                })}
            </ComboboxOptions>
          </div>
        </Combobox>
      </div>

      {!compact && marketsQuery.isError && (
        <p className="mt-3 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffb4ab]">
          {resolveErrorMessage(marketsQuery.error, '종목 목록을 불러오지 못했습니다.')}
        </p>
      )}
      {!compact && favoritesQuery.isError && (
        <p className="mt-3 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffb4ab]">
          {resolveErrorMessage(favoritesQuery.error, '관심 종목 목록을 불러오지 못했습니다.')}
        </p>
      )}
      {!compact && actionError && (
        <p className="mt-3 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffe179]">
          {actionError}
        </p>
      )}
    </section>
  )
}

export default MarketSearchBar
