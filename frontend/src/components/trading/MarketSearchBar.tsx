import { Combobox, ComboboxInput, ComboboxOption, ComboboxOptions } from '@headlessui/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Check, Loader2, Search, Star } from 'lucide-react'
import { useMemo, useState } from 'react'

import { addFavorite, fetchFavorites, fetchMarkets, removeFavorite, type MarketItem } from '../../api/markets'

interface MarketSearchBarProps {
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

function MarketSearchBar({ onSelectSymbol }: MarketSearchBarProps) {
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
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">종목 검색</h2>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
          관심 종목 {favoritesSet.size}개
        </span>
      </header>

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
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-slate-400" />
          <ComboboxInput
            placeholder="KRW-BTC, 비트코인, Ethereum"
            className="w-full rounded-xl border border-slate-300 bg-white py-2.5 pl-9 pr-3 text-sm text-slate-800 outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            displayValue={(item: MarketItem | null) => item?.market ?? query}
            onChange={(event) => setQuery(event.target.value)}
          />

          <ComboboxOptions className="absolute z-20 mt-2 max-h-80 w-full overflow-y-auto rounded-xl border border-slate-200 bg-white p-1 shadow-lg">
            {marketsQuery.isLoading && (
              <div className="flex items-center gap-2 px-3 py-3 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                종목 목록을 불러오는 중입니다.
              </div>
            )}

            {!marketsQuery.isLoading && filteredMarkets.length === 0 && (
              <div className="px-3 py-3 text-sm text-slate-500">검색 결과가 없습니다.</div>
            )}

            {!marketsQuery.isLoading &&
              filteredMarkets.map((item) => {
                const isFavorite = favoritesSet.has(item.market)
                const isPending = pendingSymbol === item.market

                return (
                  <ComboboxOption
                    key={item.market}
                    value={item}
                    className={({ focus }) => `rounded-lg px-3 py-2 ${focus ? 'bg-slate-100' : ''}`}
                  >
                    {({ selected }) => (
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-slate-900">{item.market}</p>
                          <p className="truncate text-xs text-slate-500">
                            {item.korean_name || '-'} / {item.english_name || '-'}
                          </p>
                        </div>

                        <div className="flex items-center gap-1">
                          {selected && <Check className="h-4 w-4 text-emerald-600" />}
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
                            className="rounded-md p-1 text-slate-500 transition hover:bg-slate-200 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Star
                                className={`h-4 w-4 ${isFavorite ? 'fill-amber-400 text-amber-500' : 'text-slate-400'}`}
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

      {marketsQuery.isError && (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {resolveErrorMessage(marketsQuery.error, '종목 목록을 불러오지 못했습니다.')}
        </p>
      )}
      {favoritesQuery.isError && (
        <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {resolveErrorMessage(favoritesQuery.error, '관심 종목 목록을 불러오지 못했습니다.')}
        </p>
      )}
      {actionError && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {actionError}
        </p>
      )}
    </section>
  )
}

export default MarketSearchBar
