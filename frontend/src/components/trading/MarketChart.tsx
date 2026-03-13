import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'

import { fetchCandles, type CandleItem, type MarketTimeframe } from '../../api/markets'
import { useTheme } from '../../contexts/useTheme'

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
  const { theme } = useTheme()
  const isDarkMode = theme === 'dark'
  const normalizedSymbol = useMemo(() => (symbol ? symbol.trim().toUpperCase() : ''), [symbol])
  const [timeframe, setTimeframe] = useState<MarketTimeframe>('60m')

  const chartsWrapperRef = useRef<HTMLDivElement | null>(null)
  const mainChartContainerRef = useRef<HTMLDivElement | null>(null)
  const rsiChartContainerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const rsiChartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick', Time> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram', Time> | null>(null)
  const sma20SeriesRef = useRef<ISeriesApi<'Line', Time> | null>(null)
  const sma60SeriesRef = useRef<ISeriesApi<'Line', Time> | null>(null)
  const bbUpperSeriesRef = useRef<ISeriesApi<'Line', Time> | null>(null)
  const bbLowerSeriesRef = useRef<ISeriesApi<'Line', Time> | null>(null)
  const rsiSeriesRef = useRef<ISeriesApi<'Line', Time> | null>(null)
  const isSyncingRangeRef = useRef(false)

  const candlesQuery = useQuery({
    queryKey: ['market-candles', normalizedSymbol, timeframe],
    queryFn: () => fetchCandles(normalizedSymbol, timeframe, 200),
    enabled: normalizedSymbol.length > 0,
  })

  useEffect(() => {
    const wrapper = chartsWrapperRef.current
    const mainContainer = mainChartContainerRef.current
    const rsiContainer = rsiChartContainerRef.current
    if (!wrapper || !mainContainer || !rsiContainer || chartRef.current || rsiChartRef.current) {
      return
    }

    const width = wrapper.clientWidth || mainContainer.clientWidth || 800
    const priceScaleWidth = 72

    const chartBgColor = isDarkMode ? '#1f2937' : '#ffffff'
    const chartTextColor = isDarkMode ? '#9ca3af' : '#4b5563'
    const gridColor = isDarkMode ? 'rgba(75, 85, 99, 0.2)' : 'rgba(229, 231, 235, 0.6)'
    const crosshairColor = isDarkMode ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.4)'
    const borderColor = isDarkMode ? 'rgba(75, 85, 99, 0.4)' : 'rgba(229, 231, 235, 1)'

    const chart = createChart(mainContainer, {
      width,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: chartBgColor },
        attributionLogo: false,
        textColor: chartTextColor,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      rightPriceScale: {
        borderColor: borderColor,
        minimumWidth: priceScaleWidth,
      },
      timeScale: {
        borderColor: borderColor,
        timeVisible: true,
        visible: false,
      },
      crosshair: {
        vertLine: { color: crosshairColor },
        horzLine: { color: crosshairColor },
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

    const sma20Series = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    const sma60Series = chart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    const bbUpperSeries = chart.addSeries(LineSeries, {
      color: 'rgba(244, 114, 182, 0.9)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    const bbLowerSeries = chart.addSeries(LineSeries, {
      color: 'rgba(45, 212, 191, 0.9)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    const rsiChart = createChart(rsiContainer, {
      width,
      height: 150,
      layout: {
        background: { type: ColorType.Solid, color: chartBgColor },
        attributionLogo: false,
        textColor: chartTextColor,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      rightPriceScale: {
        borderColor: borderColor,
        minimumWidth: priceScaleWidth,
      },
      timeScale: {
        borderColor: borderColor,
        timeVisible: true,
        visible: true,
      },
      crosshair: {
        vertLine: { color: crosshairColor },
        horzLine: { color: crosshairColor },
      },
    })

    const rsiSeries = rsiChart.addSeries(LineSeries, {
      color: '#a78bfa',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: () => ({
        priceRange: {
          minValue: 0,
          maxValue: 100,
        },
      }),
    })

    rsiSeries.createPriceLine({
      price: 70,
      color: 'rgba(248, 113, 113, 0.75)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: false,
      title: '70',
    })
    rsiSeries.createPriceLine({
      price: 30,
      color: 'rgba(45, 212, 191, 0.75)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: false,
      title: '30',
    })

    chartRef.current = chart
    rsiChartRef.current = rsiChart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    sma20SeriesRef.current = sma20Series
    sma60SeriesRef.current = sma60Series
    bbUpperSeriesRef.current = bbUpperSeries
    bbLowerSeriesRef.current = bbLowerSeries
    rsiSeriesRef.current = rsiSeries

    const syncMainToRsi = (range: { from: number; to: number } | null) => {
      if (!range || !rsiChartRef.current || isSyncingRangeRef.current) {
        return
      }
      isSyncingRangeRef.current = true
      try {
        rsiChartRef.current.timeScale().setVisibleLogicalRange(range)
      } finally {
        isSyncingRangeRef.current = false
      }
    }

    const syncRsiToMain = (range: { from: number; to: number } | null) => {
      if (!range || !chartRef.current || isSyncingRangeRef.current) {
        return
      }
      isSyncingRangeRef.current = true
      try {
        chartRef.current.timeScale().setVisibleLogicalRange(range)
      } finally {
        isSyncingRangeRef.current = false
      }
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(syncMainToRsi)
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange(syncRsiToMain)

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry || !chartRef.current || !rsiChartRef.current) {
        return
      }
      const nextWidth = Math.max(320, Math.floor(entry.contentRect.width))
      chartRef.current.applyOptions({ width: nextWidth })
      rsiChartRef.current.applyOptions({ width: nextWidth })
    })
    resizeObserver.observe(wrapper)

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncMainToRsi)
      rsiChart.timeScale().unsubscribeVisibleLogicalRangeChange(syncRsiToMain)
      resizeObserver.disconnect()
      chartRef.current?.remove()
      rsiChartRef.current?.remove()
      chartRef.current = null
      rsiChartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
      sma20SeriesRef.current = null
      sma60SeriesRef.current = null
      bbUpperSeriesRef.current = null
      bbLowerSeriesRef.current = null
      rsiSeriesRef.current = null
      isSyncingRangeRef.current = false
    }
  }, [isDarkMode])

  useEffect(() => {
    const candleSeries = candleSeriesRef.current
    const volumeSeries = volumeSeriesRef.current
    const sma20Series = sma20SeriesRef.current
    const sma60Series = sma60SeriesRef.current
    const bbUpperSeries = bbUpperSeriesRef.current
    const bbLowerSeries = bbLowerSeriesRef.current
    const rsiSeries = rsiSeriesRef.current
    const chart = chartRef.current
    const rsiChart = rsiChartRef.current

    if (
      !candleSeries ||
      !volumeSeries ||
      !sma20Series ||
      !sma60Series ||
      !bbUpperSeries ||
      !bbLowerSeries ||
      !rsiSeries ||
      !chart ||
      !rsiChart
    ) {
      return
    }

    if (!normalizedSymbol) {
      candleSeries.setData([])
      volumeSeries.setData([])
      sma20Series.setData([])
      sma60Series.setData([])
      bbUpperSeries.setData([])
      bbLowerSeries.setData([])
      rsiSeries.setData([])
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

    const sma20Data: LineData<Time>[] = []
    const sma60Data: LineData<Time>[] = []
    const bbUpperData: LineData<Time>[] = []
    const bbLowerData: LineData<Time>[] = []
    const rsiData: LineData<Time>[] = []

    for (const item of candlesQuery.data) {
      const time = toChartTime(item.time)

      if (typeof item.sma_20 === 'number' && Number.isFinite(item.sma_20)) {
        sma20Data.push({
          time,
          value: item.sma_20,
        })
      }

      if (typeof item.sma_60 === 'number' && Number.isFinite(item.sma_60)) {
        sma60Data.push({
          time,
          value: item.sma_60,
        })
      }

      if (typeof item.bb_upper_20_2 === 'number' && Number.isFinite(item.bb_upper_20_2)) {
        bbUpperData.push({
          time,
          value: item.bb_upper_20_2,
        })
      }

      if (typeof item.bb_lower_20_2 === 'number' && Number.isFinite(item.bb_lower_20_2)) {
        bbLowerData.push({
          time,
          value: item.bb_lower_20_2,
        })
      }

      if (typeof item.rsi_14 === 'number' && Number.isFinite(item.rsi_14)) {
        rsiData.push({
          time,
          value: item.rsi_14,
        })
      }
    }

    candleSeries.setData(candleData)
    volumeSeries.setData(volumeData)
    sma20Series.setData(sma20Data)
    sma60Series.setData(sma60Data)
    bbUpperSeries.setData(bbUpperData)
    bbLowerSeries.setData(bbLowerData)
    rsiSeries.setData(rsiData)
    chart.timeScale().fitContent()
  }, [normalizedSymbol, candlesQuery.data])

  const isEmpty = !candlesQuery.isLoading && !candlesQuery.isError && (candlesQuery.data?.length ?? 0) === 0

  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Trading Chart</h2>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {normalizedSymbol ? normalizedSymbol : '종목을 선택하면 차트가 표시됩니다.'}
          </p>
        </div>

        <div className="inline-flex rounded-lg bg-gray-100 p-1 ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-700">
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
                    ? 'bg-blue-500 text-white shadow-sm dark:bg-blue-600'
                    : 'text-gray-500 hover:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-400 dark:hover:bg-gray-800'
                }`}
              >
                {option.label}
              </button>
            )
          })}
        </div>
      </header>

      <div className="relative">
        <div ref={chartsWrapperRef} className="flex flex-col gap-3">
          <div ref={mainChartContainerRef} className="h-[420px] w-full overflow-hidden rounded-xl" />
          <div ref={rsiChartContainerRef} className="h-[150px] w-full overflow-hidden rounded-xl" />
        </div>

        {!normalizedSymbol && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-white/80 text-sm text-gray-500 backdrop-blur-sm dark:bg-gray-900/80 dark:text-gray-400">
            검색창 또는 Watchlist에서 종목을 선택해 주세요.
          </div>
        )}
        {normalizedSymbol && candlesQuery.isLoading && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-white/70 text-sm text-gray-900 backdrop-blur-sm dark:bg-gray-900/70 dark:text-gray-100">
            캔들 데이터를 불러오는 중입니다...
          </div>
        )}
        {normalizedSymbol && candlesQuery.isError && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-white/70 px-4 text-center text-sm text-rose-600 backdrop-blur-sm dark:bg-gray-900/70 dark:text-rose-400">
            {resolveErrorMessage(candlesQuery.error, '캔들 데이터를 불러오지 못했습니다.')}
          </div>
        )}
        {normalizedSymbol && isEmpty && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-white/70 text-sm text-gray-500 backdrop-blur-sm dark:bg-gray-900/70 dark:text-gray-400">
            표시할 캔들 데이터가 없습니다.
          </div>
        )}
      </div>

      <div className="mt-3 flex justify-end">
        <a
          href="https://www.tradingview.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-gray-400 transition hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
        >
          Charts by TradingView
        </a>
      </div>
    </section>
  )
}

export default MarketChart
