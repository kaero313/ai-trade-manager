import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'

import { fetchCandles, type CandleItem, type MarketTimeframe } from '../../api/markets'

interface MarketChartProps {
  symbol: string | null
}

const TIMEFRAME_OPTIONS: ReadonlyArray<{ label: string; value: MarketTimeframe }> = [
  { label: '1H', value: '60m' },
  { label: '4H', value: '240m' },
  { label: '1D', value: 'days' },
]

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

function toChartTime(raw: CandleItem['time']): Time {
  if (typeof raw === 'number') {
    return raw as UTCTimestamp
  }
  return raw
}

function MarketChart({ symbol }: MarketChartProps) {
  const normalizedSymbol = useMemo(() => (symbol ? symbol.trim().toUpperCase() : ''), [symbol])
  const [timeframe, setTimeframe] = useState<MarketTimeframe>('60m')

  const chartContainerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram', Time> | null>(null)

  const candlesQuery = useQuery({
    queryKey: ['market-candles', normalizedSymbol, timeframe],
    queryFn: () => fetchCandles(normalizedSymbol, timeframe, 200),
    enabled: normalizedSymbol.length > 0,
  })

  useEffect(() => {
    const container = chartContainerRef.current
    if (!container || chartRef.current) {
      return
    }

    const chart = createChart(container, {
      width: container.clientWidth || 800,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#cbd5e1',
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.10)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.10)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(148, 163, 184, 0.35)',
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.35)',
        timeVisible: true,
      },
      crosshair: {
        vertLine: { color: 'rgba(34, 197, 94, 0.35)' },
        horzLine: { color: 'rgba(34, 197, 94, 0.35)' },
      },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      borderVisible: false,
      priceLineVisible: true,
      lastValueVisible: true,
    })

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.80,
        bottom: 0,
      },
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry || !chartRef.current) {
        return
      }
      chartRef.current.applyOptions({
        width: Math.max(320, Math.floor(entry.contentRect.width)),
      })
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chartRef.current?.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
    }
  }, [])

  useEffect(() => {
    const candleSeries = candleSeriesRef.current
    const volumeSeries = volumeSeriesRef.current
    const chart = chartRef.current

    if (!candleSeries || !volumeSeries || !chart) {
      return
    }

    if (!normalizedSymbol) {
      candleSeries.setData([])
      volumeSeries.setData([])
      return
    }

    if (!candlesQuery.data) {
      return
    }

    const candleData: CandlestickData<Time>[] = candlesQuery.data.map((item) => ({
      time: toChartTime(item.time),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }))

    const volumeData: HistogramData<Time>[] = candlesQuery.data.map((item) => ({
      time: toChartTime(item.time),
      value: item.volume,
      color: item.close >= item.open ? 'rgba(34, 197, 94, 0.45)' : 'rgba(239, 68, 68, 0.45)',
    }))

    candleSeries.setData(candleData)
    volumeSeries.setData(volumeData)
    chart.timeScale().fitContent()
  }, [normalizedSymbol, candlesQuery.data])

  const isEmpty = !candlesQuery.isLoading && !candlesQuery.isError && (candlesQuery.data?.length ?? 0) === 0

  return (
    <section className="rounded-2xl bg-slate-950 p-4 shadow-lg ring-1 ring-slate-800">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Trading Chart</h2>
          <p className="mt-1 text-xs text-slate-400">
            {normalizedSymbol ? normalizedSymbol : '종목을 선택하면 차트가 표시됩니다.'}
          </p>
        </div>

        <div className="inline-flex rounded-lg bg-slate-900 p-1 ring-1 ring-slate-700">
          {TIMEFRAME_OPTIONS.map((option) => {
            const active = option.value === timeframe
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => setTimeframe(option.value)}
                disabled={!normalizedSymbol}
                className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                  active
                    ? 'bg-emerald-500 text-white'
                    : 'text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40'
                }`}
              >
                {option.label}
              </button>
            )
          })}
        </div>
      </header>

      <div className="relative">
        <div ref={chartContainerRef} className="h-[420px] w-full overflow-hidden rounded-xl" />

        {!normalizedSymbol && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/80 text-sm text-slate-400">
            검색창 또는 Watchlist에서 종목을 선택해 주세요.
          </div>
        )}
        {normalizedSymbol && candlesQuery.isLoading && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/70 text-sm text-slate-300">
            캔들 데이터를 불러오는 중입니다...
          </div>
        )}
        {normalizedSymbol && candlesQuery.isError && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/70 px-4 text-center text-sm text-rose-300">
            {resolveErrorMessage(candlesQuery.error, '캔들 데이터를 불러오지 못했습니다.')}
          </div>
        )}
        {normalizedSymbol && isEmpty && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/70 text-sm text-slate-400">
            표시할 캔들 데이터가 없습니다.
          </div>
        )}
      </div>
    </section>
  )
}

export default MarketChart
