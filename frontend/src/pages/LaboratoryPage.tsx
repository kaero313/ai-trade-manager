import { useEffect, useMemo, useRef, useState } from 'react'

import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'

import { fetchMarkets, type MarketItem } from '../api/markets'
import {
  runBacktest,
  type BacktestRunRequest,
  type BacktestRunResponse,
  type BacktestTimeframe,
} from '../services/backtestService'

const TIMEFRAME_OPTIONS: Array<{ label: string; value: BacktestTimeframe }> = [
  { label: '1시간봉', value: '60m' },
  { label: '4시간봉', value: '240m' },
  { label: '일봉', value: 'days' },
]

interface LaboratoryFormState {
  market: string
  startDate: string
  endDate: string
  timeframe: BacktestTimeframe
  initialBalance: string
  gridUpperBound: string
  gridLowerBound: string
  gridOrderKrw: string
  gridSellPct: string
  gridCooldownSeconds: string
}

function formatDateInput(value: Date): string {
  return value.toISOString().slice(0, 10)
}

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

function formatPercent(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '' : ''
  return `${sign}${value.toFixed(2)}%`
}

function toIsoStart(dateText: string): string {
  return new Date(`${dateText}T00:00:00`).toISOString()
}

function toIsoEnd(dateText: string): string {
  return new Date(`${dateText}T23:59:59`).toISOString()
}

function parsePositiveNumber(raw: string): number | null {
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) {
    return null
  }
  return value
}

function parseErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim().length > 0) {
      return detail
    }
    if (error.message) {
      return error.message
    }
  }
  return fallback
}

function LaboratoryPage() {
  const now = useMemo(() => new Date(), [])
  const oneYearAgo = useMemo(() => {
    const value = new Date(now)
    value.setFullYear(value.getFullYear() - 1)
    return value
  }, [now])

  const [markets, setMarkets] = useState<MarketItem[]>([])
  const [isMarketsLoading, setIsMarketsLoading] = useState(true)
  const [marketsError, setMarketsError] = useState<string | null>(null)

  const [form, setForm] = useState<LaboratoryFormState>({
    market: 'KRW-BTC',
    startDate: formatDateInput(oneYearAgo),
    endDate: formatDateInput(now),
    timeframe: 'days',
    initialBalance: '1000000',
    gridUpperBound: '100000000',
    gridLowerBound: '80000000',
    gridOrderKrw: '10000',
    gridSellPct: '100',
    gridCooldownSeconds: '60',
  })

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<BacktestRunResponse | null>(null)

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
  const markerPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const isSyncingRangeRef = useRef(false)

  useEffect(() => {
    let isMounted = true
    const loadMarkets = async () => {
      setIsMarketsLoading(true)
      setMarketsError(null)
      try {
        const rows = await fetchMarkets()
        if (!isMounted) {
          return
        }
        setMarkets(rows)
        if (rows.length > 0) {
          setForm((prev) => {
            if (rows.some((item) => item.market === prev.market)) {
              return prev
            }
            return { ...prev, market: rows[0].market }
          })
        }
      } catch (error) {
        if (!isMounted) {
          return
        }
        setMarketsError(parseErrorMessage(error, '종목 목록을 불러오지 못했습니다.'))
      } finally {
        if (isMounted) {
          setIsMarketsLoading(false)
        }
      }
    }

    void loadMarkets()
    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    const wrapper = chartsWrapperRef.current
    const mainContainer = mainChartContainerRef.current
    const rsiContainer = rsiChartContainerRef.current
    if (!wrapper || !mainContainer || !rsiContainer || chartRef.current || rsiChartRef.current) {
      return
    }

    const width = wrapper.clientWidth || mainContainer.clientWidth || 900
    const priceScaleWidth = 72

    const chart = createChart(mainContainer, {
      width,
      height: 500,
      layout: {
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#cbd5e1',
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.10)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.10)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(148, 163, 184, 0.25)',
        minimumWidth: priceScaleWidth,
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.25)',
        timeVisible: true,
        visible: false,
      },
      crosshair: {
        vertLine: { color: 'rgba(59, 130, 246, 0.35)' },
        horzLine: { color: 'rgba(59, 130, 246, 0.35)' },
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
      scaleMargins: { top: 0.82, bottom: 0 },
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
        background: { type: ColorType.Solid, color: '#020617' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.08)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.12)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(148, 163, 184, 0.25)',
        minimumWidth: priceScaleWidth,
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.25)',
        timeVisible: true,
        visible: true,
      },
      crosshair: {
        vertLine: { color: 'rgba(148, 163, 184, 0.25)' },
        horzLine: { color: 'rgba(148, 163, 184, 0.25)' },
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

    const markerPlugin = createSeriesMarkers(candleSeries, [])

    chartRef.current = chart
    rsiChartRef.current = rsiChart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    sma20SeriesRef.current = sma20Series
    sma60SeriesRef.current = sma60Series
    bbUpperSeriesRef.current = bbUpperSeries
    bbLowerSeriesRef.current = bbLowerSeries
    rsiSeriesRef.current = rsiSeries
    markerPluginRef.current = markerPlugin

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
      markerPluginRef.current = null
      isSyncingRangeRef.current = false
    }
  }, [])

  useEffect(() => {
    const candleSeries = candleSeriesRef.current
    const volumeSeries = volumeSeriesRef.current
    const sma20Series = sma20SeriesRef.current
    const sma60Series = sma60SeriesRef.current
    const bbUpperSeries = bbUpperSeriesRef.current
    const bbLowerSeries = bbLowerSeriesRef.current
    const rsiSeries = rsiSeriesRef.current
    const markerPlugin = markerPluginRef.current
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
      !markerPlugin ||
      !chart ||
      !rsiChart
    ) {
      return
    }

    if (!result || result.candles.length === 0) {
      candleSeries.setData([])
      volumeSeries.setData([])
      sma20Series.setData([])
      sma60Series.setData([])
      bbUpperSeries.setData([])
      bbLowerSeries.setData([])
      rsiSeries.setData([])
      markerPlugin.setMarkers([])
      return
    }

    const candleData: CandlestickData<Time>[] = result.candles.map((item) => ({
      time: item.time as UTCTimestamp,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }))

    const volumeData: HistogramData<Time>[] = result.candles.map((item) => ({
      time: item.time as UTCTimestamp,
      value: item.volume,
      color: item.close >= item.open ? 'rgba(34, 197, 94, 0.35)' : 'rgba(239, 68, 68, 0.35)',
    }))

    const sma20Data: LineData<Time>[] = []
    const sma60Data: LineData<Time>[] = []
    const bbUpperData: LineData<Time>[] = []
    const bbLowerData: LineData<Time>[] = []
    const rsiData: LineData<Time>[] = []

    for (const item of result.candles) {
      const time = item.time as UTCTimestamp

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

    const markerData: SeriesMarker<Time>[] = result.markers.map((item) => ({
      time: item.time as UTCTimestamp,
      position: item.position,
      shape: item.shape,
      color: item.color,
      text: item.text,
    }))

    candleSeries.setData(candleData)
    volumeSeries.setData(volumeData)
    sma20Series.setData(sma20Data)
    sma60Series.setData(sma60Data)
    bbUpperSeries.setData(bbUpperData)
    bbLowerSeries.setData(bbLowerData)
    rsiSeries.setData(rsiData)
    markerPlugin.setMarkers(markerData)
    chart.timeScale().fitContent()
  }, [result])

  const submitSimulation = async () => {
    setFormError(null)
    setSubmitError(null)

    if (!form.market.trim()) {
      setFormError('종목을 선택해 주세요.')
      return
    }
    if (!form.startDate || !form.endDate) {
      setFormError('기간(시작일/종료일)을 모두 입력해 주세요.')
      return
    }

    const startTime = new Date(`${form.startDate}T00:00:00`).getTime()
    const endTime = new Date(`${form.endDate}T00:00:00`).getTime()
    if (Number.isNaN(startTime) || Number.isNaN(endTime) || startTime > endTime) {
      setFormError('시작일은 종료일보다 이후일 수 없습니다.')
      return
    }

    const initialBalance = parsePositiveNumber(form.initialBalance)
    const gridUpperBound = parsePositiveNumber(form.gridUpperBound)
    const gridLowerBound = parsePositiveNumber(form.gridLowerBound)
    const gridOrderKrw = parsePositiveNumber(form.gridOrderKrw)
    const gridSellPct = parsePositiveNumber(form.gridSellPct)
    const gridCooldownSeconds = parsePositiveNumber(form.gridCooldownSeconds)

    if (
      initialBalance === null ||
      gridUpperBound === null ||
      gridLowerBound === null ||
      gridOrderKrw === null ||
      gridSellPct === null ||
      gridCooldownSeconds === null
    ) {
      setFormError('수치 파라미터는 0보다 큰 값을 입력해 주세요.')
      return
    }
    if (gridUpperBound <= gridLowerBound) {
      setFormError('그리드 상단 가격은 하단 가격보다 커야 합니다.')
      return
    }
    if (gridSellPct > 100) {
      setFormError('매도 비율은 100 이하로 입력해 주세요.')
      return
    }

    const payload: BacktestRunRequest = {
      market: form.market.trim().toUpperCase(),
      start_date: toIsoStart(form.startDate),
      end_date: toIsoEnd(form.endDate),
      timeframe: form.timeframe,
      initial_balance: initialBalance,
      grid_upper_bound: gridUpperBound,
      grid_lower_bound: gridLowerBound,
      grid_order_krw: gridOrderKrw,
      grid_sell_pct: gridSellPct,
      grid_cooldown_seconds: Math.max(1, Math.trunc(gridCooldownSeconds)),
    }

    setIsSubmitting(true)
    try {
      const response = await runBacktest(payload)
      setResult(response)
    } catch (error) {
      setSubmitError(parseErrorMessage(error, '백테스트 실행에 실패했습니다.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  const profitAmount = result ? result.meta.final_balance - result.meta.initial_balance : 0
  const totalReturnPct = result?.summary.total_return_pct ?? 0
  const mddPct = result?.summary.max_drawdown_pct ?? 0
  const winRate = result?.summary.win_rate ?? 0
  const numberOfTrades = result?.summary.number_of_trades ?? 0

  return (
    <div className="space-y-6">
      <section className="rounded-2xl bg-gradient-to-r from-slate-950 via-slate-900 to-slate-800 p-6 text-slate-100 shadow-lg ring-1 ring-slate-800">
        <h1 className="text-2xl font-bold tracking-tight">전략 연구소 (Laboratory)</h1>
        <p className="mt-2 text-sm text-slate-300">
          그리드 전략 파라미터를 조정하고, 백테스트 성과와 타점을 시각적으로 검증하세요.
        </p>
      </section>

      <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="text-lg font-semibold text-slate-900">시뮬레이션 파라미터</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="flex flex-col gap-1 text-sm text-slate-700">
            종목
            <select
              value={form.market}
              disabled={isMarketsLoading}
              onChange={(event) => setForm((prev) => ({ ...prev, market: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-100"
            >
              <option value="">종목 선택</option>
              {markets.map((item) => (
                <option key={item.market} value={item.market}>
                  {item.market} ({item.korean_name || item.english_name || '-'})
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            시작일
            <input
              type="date"
              value={form.startDate}
              onChange={(event) => setForm((prev) => ({ ...prev, startDate: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            종료일
            <input
              type="date"
              value={form.endDate}
              onChange={(event) => setForm((prev) => ({ ...prev, endDate: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            캔들 주기
            <select
              value={form.timeframe}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, timeframe: event.target.value as BacktestTimeframe }))
              }
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            >
              {TIMEFRAME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            그리드 하단 가격
            <input
              type="number"
              value={form.gridLowerBound}
              onChange={(event) => setForm((prev) => ({ ...prev, gridLowerBound: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            그리드 상단 가격
            <input
              type="number"
              value={form.gridUpperBound}
              onChange={(event) => setForm((prev) => ({ ...prev, gridUpperBound: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            1회 매수 금액 (KRW)
            <input
              type="number"
              value={form.gridOrderKrw}
              onChange={(event) => setForm((prev) => ({ ...prev, gridOrderKrw: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            매도 비율 (%)
            <input
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={form.gridSellPct}
              onChange={(event) => setForm((prev) => ({ ...prev, gridSellPct: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            쿨다운 (초)
            <input
              type="number"
              min={1}
              value={form.gridCooldownSeconds}
              onChange={(event) => setForm((prev) => ({ ...prev, gridCooldownSeconds: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-slate-700">
            초기 자본금 (KRW)
            <input
              type="number"
              value={form.initialBalance}
              onChange={(event) => setForm((prev) => ({ ...prev, initialBalance: event.target.value }))}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />
          </label>
        </div>

        {(marketsError || formError || submitError) && (
          <div className="mt-4 space-y-2 text-sm">
            {marketsError && (
              <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-700">{marketsError}</p>
            )}
            {formError && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700">{formError}</p>
            )}
            {submitError && (
              <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-700">{submitError}</p>
            )}
          </div>
        )}

        <div className="mt-5">
          <button
            type="button"
            onClick={() => void submitSimulation()}
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
            시뮬레이션 시작
          </button>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <article className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">최종 수익금</p>
          <p className={`mt-2 text-2xl font-bold ${profitAmount >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
            {result ? formatSignedKrw(profitAmount) : '-'}
          </p>
        </article>

        <article className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">최종 수익률</p>
          <p className={`mt-2 text-2xl font-bold ${totalReturnPct >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
            {result ? formatPercent(totalReturnPct) : '-'}
          </p>
        </article>

        <article className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">MDD</p>
          <p className="mt-2 text-2xl font-bold text-rose-600">{result ? `${mddPct.toFixed(2)}%` : '-'}</p>
        </article>

        <article className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">승률</p>
          <p className="mt-2 text-2xl font-bold text-slate-900">{result ? `${winRate.toFixed(2)}%` : '-'}</p>
        </article>

        <article className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">총 거래 횟수</p>
          <p className="mt-2 text-2xl font-bold text-slate-900">{result ? numberOfTrades : '-'}</p>
        </article>
      </section>

      <section className="rounded-2xl bg-slate-950 p-4 shadow-lg ring-1 ring-slate-800">
        <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">백테스트 타점 차트</h2>
            <p className="mt-1 text-xs text-slate-400">
              매수(빨강) / 매도(파랑) 마커를 차트에 오버레이하여 타점을 확인합니다.
            </p>
          </div>
          {result && (
            <div className="rounded-md bg-slate-900 px-3 py-1.5 text-xs text-slate-300 ring-1 ring-slate-700">
              {result.meta.market} · {result.meta.timeframe} · {result.meta.bars_processed} bars
            </div>
          )}
        </header>

        <div className="relative">
          <div ref={chartsWrapperRef} className="flex flex-col gap-3">
            <div ref={mainChartContainerRef} className="h-[500px] w-full overflow-hidden rounded-xl" />
            <div ref={rsiChartContainerRef} className="h-[150px] w-full overflow-hidden rounded-xl" />
          </div>

          {!result && !isSubmitting && (
            <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/75 text-sm text-slate-400">
              파라미터를 입력하고 시뮬레이션을 실행하면 차트가 표시됩니다.
            </div>
          )}
          {isSubmitting && (
            <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/70 text-sm text-slate-200">
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                백테스트를 실행 중입니다...
              </span>
            </div>
          )}
          {result && result.candles.length === 0 && !isSubmitting && (
            <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/75 text-sm text-slate-400">
              선택한 조건의 캔들 데이터가 없습니다.
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

export default LaboratoryPage
