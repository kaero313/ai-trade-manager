import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { isAxiosError } from 'axios'
import {
  Activity,
  BarChart3,
  Bot,
  Brain,
  LineChart as LineChartIcon,
  Loader2,
  Play,
  ShieldCheck,
  SlidersHorizontal,
  Table2,
} from 'lucide-react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { fetchMarkets, type MarketItem } from '../api/markets'
import { useTheme } from '../contexts/useTheme'
import { getBotConfig, getSystemConfigs } from '../services/api'
import {
  runBacktest,
  type BacktestRunRequest,
  type BacktestRunResponse,
  type BacktestTimeframe,
} from '../services/backtestService'

const TIMEFRAME_OPTIONS: Array<{ label: string; value: BacktestTimeframe }> = [
  { label: '1시간', value: '60m' },
  { label: '4시간', value: '240m' },
  { label: '일봉', value: 'days' },
]

const POLICY_PRESETS = {
  conservative: {
    label: '보수',
    description: '신호를 엄격하게 보고 비중을 낮춥니다.',
    minConfidence: '80',
    maxAllocationPct: '20',
    takeProfitPct: '4',
    stopLossPct: '-2',
    cooldownMinutes: '120',
  },
  balanced: {
    label: '균형',
    description: '기본값으로 수익과 방어를 균형 있게 봅니다.',
    minConfidence: '70',
    maxAllocationPct: '30',
    takeProfitPct: '5',
    stopLossPct: '-3',
    cooldownMinutes: '60',
  },
  aggressive: {
    label: '공격',
    description: '신호 기준을 낮추고 더 큰 비중을 허용합니다.',
    minConfidence: '60',
    maxAllocationPct: '50',
    takeProfitPct: '8',
    stopLossPct: '-5',
    cooldownMinutes: '30',
  },
} as const

type PolicyPresetKey = keyof typeof POLICY_PRESETS
type ResultTab = 'price' | 'equity' | 'drawdown' | 'trades'

interface LaboratoryFormState {
  market: string
  startDate: string
  endDate: string
  timeframe: BacktestTimeframe
  initialBalance: string
  emaFast: string
  emaSlow: string
  rsiPeriod: string
  rsiMin: string
  trailingStopPct: string
  minConfidence: string
  maxAllocationPct: string
  takeProfitPct: string
  stopLossPct: string
  cooldownMinutes: string
}

function formatDateInput(value: Date): string {
  return value.toISOString().slice(0, 10)
}

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatCompactKrw(value: number): string {
  if (Math.abs(value) >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(1)}억`
  }
  if (Math.abs(value) >= 10_000) {
    return `${(value / 10_000).toFixed(0)}만`
  }
  return `${Math.round(value)}`
}

function formatPercent(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '' : ''
  return `${sign}${value.toFixed(2)}%`
}

function formatDateLabel(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
  })
}

function toIsoStart(dateText: string): string {
  return new Date(`${dateText}T00:00:00`).toISOString()
}

function toIsoEnd(dateText: string): string {
  return new Date(`${dateText}T23:59:59`).toISOString()
}

function parseNumber(raw: string): number | null {
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

function parsePositiveNumber(raw: string): number | null {
  const value = parseNumber(raw)
  if (value === null || value <= 0) {
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
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function buildDefaultForm(): LaboratoryFormState {
  const now = new Date()
  const oneYearAgo = new Date(now)
  oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1)

  return {
    market: 'KRW-BTC',
    startDate: formatDateInput(oneYearAgo),
    endDate: formatDateInput(now),
    timeframe: 'days',
    initialBalance: '1000000',
    emaFast: '12',
    emaSlow: '26',
    rsiPeriod: '14',
    rsiMin: '50',
    trailingStopPct: '3',
    minConfidence: '70',
    maxAllocationPct: '30',
    takeProfitPct: '5',
    stopLossPct: '-3',
    cooldownMinutes: '60',
  }
}

function marketLabel(market: MarketItem): string {
  const names = [market.korean_name, market.english_name].filter(Boolean).join(' / ')
  return names ? `${market.market} · ${names}` : market.market
}

function NumberInput({
  label,
  value,
  onChange,
  suffix,
  min,
  step,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  suffix?: string
  min?: number
  step?: number
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
        {label}
      </span>
      <div className="flex rounded-md border border-gray-300 bg-white focus-within:border-emerald-500 focus-within:ring-2 focus-within:ring-emerald-500 dark:border-gray-700 dark:bg-gray-900">
        <input
          type="number"
          value={value}
          min={min}
          step={step}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-0 flex-1 rounded-md bg-transparent px-3 py-2 text-sm text-gray-900 outline-none dark:text-gray-100"
        />
        {suffix && (
          <span className="flex items-center border-l border-gray-200 px-3 text-xs font-semibold text-gray-500 dark:border-gray-700 dark:text-gray-400">
            {suffix}
          </span>
        )}
      </div>
    </label>
  )
}

function PriceChart({
  result,
  isDarkMode,
}: {
  result: BacktestRunResponse
  isDarkMode: boolean
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || result.candles.length === 0) {
      return
    }

    const chart = createChart(container, {
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: isDarkMode ? '#111827' : '#ffffff' },
        textColor: isDarkMode ? '#d1d5db' : '#374151',
      },
      grid: {
        vertLines: { color: isDarkMode ? 'rgba(75, 85, 99, 0.28)' : 'rgba(229, 231, 235, 0.8)' },
        horzLines: { color: isDarkMode ? 'rgba(75, 85, 99, 0.28)' : 'rgba(229, 231, 235, 0.8)' },
      },
      rightPriceScale: {
        borderColor: isDarkMode ? '#374151' : '#e5e7eb',
      },
      timeScale: {
        borderColor: isDarkMode ? '#374151' : '#e5e7eb',
        timeVisible: true,
      },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    })

    const candleData: CandlestickData<Time>[] = result.candles.map((item) => ({
      time: item.time as UTCTimestamp,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }))
    candleSeries.setData(candleData)

    const markerData: SeriesMarker<Time>[] = result.markers.map((marker) => ({
      time: marker.time as UTCTimestamp,
      position: marker.position,
      shape: marker.shape,
      color: marker.color,
      text: marker.text,
    }))
    createSeriesMarkers(candleSeries, markerData)
    chart.timeScale().fitContent()

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        chart.applyOptions({ width: Math.floor(entry.contentRect.width) })
      }
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [isDarkMode, result])

  return <div ref={containerRef} className="h-[420px] w-full" />
}

function CurveChart({
  data,
  mode,
  isDarkMode,
}: {
  data: Array<{ time: number; value: number }>
  mode: 'equity' | 'drawdown'
  isDarkMode: boolean
}) {
  const stroke = mode === 'equity' ? '#10b981' : '#ef4444'
  const tickColor = isDarkMode ? '#9ca3af' : '#6b7280'

  if (data.length === 0) {
    return (
      <div className="flex h-[360px] items-center justify-center text-sm text-gray-500 dark:text-gray-400">
        표시할 곡선 데이터가 없습니다.
      </div>
    )
  }

  if (mode === 'drawdown') {
    return (
      <div className="h-[360px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={isDarkMode ? '#374151' : '#e5e7eb'} />
            <XAxis
              dataKey="time"
              tickFormatter={formatDateLabel}
              tick={{ fill: tickColor, fontSize: 12 }}
            />
            <YAxis
              tickFormatter={(value) => `${Number(value).toFixed(1)}%`}
              tick={{ fill: tickColor, fontSize: 12 }}
            />
            <Tooltip
              labelFormatter={(value) => formatDateLabel(Number(value))}
              formatter={(value) => [`${Number(value).toFixed(2)}%`, '드로다운']}
            />
            <Area type="monotone" dataKey="value" stroke={stroke} fill="#fee2e2" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <div className="h-[360px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke={isDarkMode ? '#374151' : '#e5e7eb'} />
          <XAxis
            dataKey="time"
            tickFormatter={formatDateLabel}
            tick={{ fill: tickColor, fontSize: 12 }}
          />
          <YAxis
            tickFormatter={(value) => formatCompactKrw(Number(value))}
            tick={{ fill: tickColor, fontSize: 12 }}
          />
          <Tooltip
            labelFormatter={(value) => formatDateLabel(Number(value))}
            formatter={(value) => [formatKrw(Number(value)), '자산']}
          />
          <Line type="monotone" dataKey="value" stroke={stroke} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function LaboratoryPage() {
  const { theme } = useTheme()
  const isDarkMode = theme === 'dark'
  const [markets, setMarkets] = useState<MarketItem[]>([])
  const [marketsError, setMarketsError] = useState<string | null>(null)
  const [form, setForm] = useState<LaboratoryFormState>(() => buildDefaultForm())
  const [result, setResult] = useState<BacktestRunResponse | null>(null)
  const [activeTab, setActiveTab] = useState<ResultTab>('price')
  const [selectedPreset, setSelectedPreset] = useState<PolicyPresetKey | 'custom'>('balanced')
  const [showAdvancedPolicy, setShowAdvancedPolicy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [isBootstrapping, setIsBootstrapping] = useState(true)

  useEffect(() => {
    let isMounted = true

    async function loadInitialData() {
      setIsBootstrapping(true)
      const [marketsResult, botConfigResult, configsResult] = await Promise.allSettled([
        fetchMarkets(),
        getBotConfig(),
        getSystemConfigs(),
      ])

      if (!isMounted) {
        return
      }

      if (marketsResult.status === 'fulfilled') {
        setMarkets(marketsResult.value)
      } else {
        setMarketsError('마켓 목록을 불러오지 못했습니다.')
      }

      const nextForm: Partial<LaboratoryFormState> = {}
      if (botConfigResult.status === 'fulfilled') {
        const config = botConfigResult.value
        const firstSymbol = config.symbols?.[0]
        if (firstSymbol) {
          nextForm.market = firstSymbol
        }
        if (config.strategy) {
          nextForm.emaFast = String(config.strategy.ema_fast)
          nextForm.emaSlow = String(config.strategy.ema_slow)
          nextForm.rsiPeriod = String(config.strategy.rsi)
          nextForm.rsiMin = String(config.strategy.rsi_min)
          nextForm.trailingStopPct = String(config.strategy.trailing_stop_pct * 100)
        }
        if (config.risk) {
          nextForm.cooldownMinutes = String(config.risk.cooldown_minutes)
        }
      }

      if (configsResult.status === 'fulfilled') {
        const configs = new Map(
          configsResult.value.map((item) => [item.config_key, item.config_value]),
        )
        nextForm.minConfidence = configs.get('ai_min_confidence_trade') ?? nextForm.minConfidence
        nextForm.maxAllocationPct = configs.get('max_allocation_pct') ?? nextForm.maxAllocationPct
        nextForm.takeProfitPct = configs.get('hard_take_profit_pct') ?? nextForm.takeProfitPct
        nextForm.stopLossPct = configs.get('hard_stop_loss_pct') ?? nextForm.stopLossPct
      }

      setForm((current) => ({ ...current, ...nextForm }))
      setIsBootstrapping(false)
    }

    void loadInitialData()
    return () => {
      isMounted = false
    }
  }, [])

  const filteredMarkets = useMemo(() => {
    const query = form.market.trim().toLowerCase()
    if (!query) {
      return markets.slice(0, 80)
    }
    return markets
      .filter((market) => marketLabel(market).toLowerCase().includes(query))
      .slice(0, 80)
  }, [form.market, markets])

  const selectedMarket = useMemo(
    () => markets.find((market) => market.market === form.market.trim().toUpperCase()),
    [form.market, markets],
  )

  const equityData = useMemo(
    () =>
      (result?.equity_curve ?? []).map((point) => ({
        time: point.time,
        value: point.equity,
      })) ?? [],
    [result],
  )

  const drawdownData = useMemo(
    () =>
      (result?.drawdown_curve ?? []).map((point) => ({
        time: point.time,
        value: point.drawdown_pct,
      })) ?? [],
    [result],
  )

  const handlePreset = (presetKey: PolicyPresetKey) => {
    const preset = POLICY_PRESETS[presetKey]
    setSelectedPreset(presetKey)
    setForm((current) => ({
      ...current,
      minConfidence: preset.minConfidence,
      maxAllocationPct: preset.maxAllocationPct,
      takeProfitPct: preset.takeProfitPct,
      stopLossPct: preset.stopLossPct,
      cooldownMinutes: preset.cooldownMinutes,
    }))
  }

  const updatePolicyField = (field: keyof LaboratoryFormState, value: string) => {
    setSelectedPreset('custom')
    setForm((current) => ({ ...current, [field]: value }))
  }

  const buildPayload = (): BacktestRunRequest | null => {
    const initialBalance = parsePositiveNumber(form.initialBalance)
    const emaFast = parsePositiveNumber(form.emaFast)
    const emaSlow = parsePositiveNumber(form.emaSlow)
    const rsiPeriod = parsePositiveNumber(form.rsiPeriod)
    const rsiMin = parsePositiveNumber(form.rsiMin)
    const trailingStopPct = parseNumber(form.trailingStopPct)
    const minConfidence = parseNumber(form.minConfidence)
    const maxAllocationPct = parseNumber(form.maxAllocationPct)
    const takeProfitPct = parseNumber(form.takeProfitPct)
    const stopLossPct = parseNumber(form.stopLossPct)
    const cooldownMinutes = parseNumber(form.cooldownMinutes)

    if (
      initialBalance === null ||
      emaFast === null ||
      emaSlow === null ||
      rsiPeriod === null ||
      rsiMin === null ||
      trailingStopPct === null ||
      minConfidence === null ||
      maxAllocationPct === null ||
      takeProfitPct === null ||
      stopLossPct === null ||
      cooldownMinutes === null
    ) {
      setError('모든 정책 값은 숫자로 입력해야 합니다.')
      return null
    }

    if (emaFast >= emaSlow) {
      setError('빠른 EMA는 느린 EMA보다 작아야 합니다.')
      return null
    }

    if (minConfidence < 0 || minConfidence > 100 || maxAllocationPct < 0 || maxAllocationPct > 100) {
      setError('신뢰도와 최대 비중은 0~100 범위여야 합니다.')
      return null
    }

    if (stopLossPct > 0) {
      setError('손절 기준은 0 이하 값으로 입력해야 합니다.')
      return null
    }

    return {
      market: form.market.trim().toUpperCase(),
      start_date: toIsoStart(form.startDate),
      end_date: toIsoEnd(form.endDate),
      timeframe: form.timeframe,
      initial_balance: initialBalance,
      strategy: {
        ema_fast: Math.trunc(emaFast),
        ema_slow: Math.trunc(emaSlow),
        rsi_period: Math.trunc(rsiPeriod),
        rsi_min: Math.trunc(rsiMin),
        trailing_stop_pct: Math.max(trailingStopPct, 0) / 100,
      },
      policy: {
        min_confidence: Math.trunc(minConfidence),
        max_allocation_pct: maxAllocationPct,
        take_profit_pct: Math.max(takeProfitPct, 0),
        stop_loss_pct: Math.min(stopLossPct, 0),
        cooldown_minutes: Math.max(0, Math.trunc(cooldownMinutes)),
      },
    }
  }

  const handleRun = async () => {
    setError(null)
    const payload = buildPayload()
    if (!payload) {
      return
    }

    try {
      setIsRunning(true)
      const response = await runBacktest(payload)
      setResult(response)
      setActiveTab('price')
    } catch (runError) {
      setError(parseErrorMessage(runError, '백테스트를 실행하지 못했습니다.'))
    } finally {
      setIsRunning(false)
    }
  }

  const finalPnl = result ? result.meta.final_balance - result.meta.initial_balance : 0

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-6 text-gray-950 dark:bg-gray-950 dark:text-gray-50 sm:px-6 lg:px-8">
      <div className="mx-auto grid max-w-[1600px] gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                  AI Policy Lab
                </p>
                <h1 className="mt-2 text-2xl font-bold">AI 매매 정책 검증실</h1>
              </div>
              <Brain className="mt-1 h-6 w-6 text-emerald-500" />
            </div>
          </section>

          <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <div className="mb-4 flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-gray-500" />
              <h2 className="text-sm font-semibold">실험 조건</h2>
            </div>

            <div className="space-y-4">
              <label className="block">
                <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
                  종목
                </span>
                <input
                  list="laboratory-market-options"
                  value={form.market}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, market: event.target.value.toUpperCase() }))
                  }
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
                />
                <datalist id="laboratory-market-options">
                  {filteredMarkets.map((market) => (
                    <option key={market.market} value={market.market}>
                      {marketLabel(market)}
                    </option>
                  ))}
                </datalist>
                {selectedMarket && (
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {selectedMarket.korean_name} · {selectedMarket.english_name}
                  </p>
                )}
                {marketsError && (
                  <p className="mt-1 text-xs text-amber-600 dark:text-amber-300">{marketsError}</p>
                )}
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
                    시작일
                  </span>
                  <input
                    type="date"
                    value={form.startDate}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, startDate: event.target.value }))
                    }
                    className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
                    종료일
                  </span>
                  <input
                    type="date"
                    value={form.endDate}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, endDate: event.target.value }))
                    }
                    className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
                  />
                </label>
              </div>

              <div className="grid grid-cols-3 gap-2 rounded-md border border-gray-200 bg-gray-50 p-1 dark:border-gray-800 dark:bg-gray-950">
                {TIMEFRAME_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() =>
                      setForm((current) => ({ ...current, timeframe: option.value }))
                    }
                    className={`rounded px-3 py-2 text-sm font-semibold transition ${
                      form.timeframe === option.value
                        ? 'bg-white text-emerald-700 shadow-sm dark:bg-gray-800 dark:text-emerald-300'
                        : 'text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100'
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <NumberInput
                label="초기 자본"
                value={form.initialBalance}
                onChange={(value) => setForm((current) => ({ ...current, initialBalance: value }))}
                suffix="KRW"
                min={1}
                step={10000}
              />
            </div>
          </section>

          <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <div className="mb-4 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-gray-500" />
              <h2 className="text-sm font-semibold">AI 정책</h2>
            </div>

            <div className="mb-4 grid grid-cols-3 gap-2">
              {(Object.keys(POLICY_PRESETS) as PolicyPresetKey[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => handlePreset(key)}
                  className={`rounded-md border px-3 py-3 text-left transition ${
                    selectedPreset === key
                      ? 'border-emerald-500 bg-emerald-50 text-emerald-800 dark:border-emerald-500 dark:bg-emerald-500/10 dark:text-emerald-200'
                      : 'border-gray-200 text-gray-700 hover:border-emerald-400 hover:text-emerald-700 dark:border-gray-700 dark:text-gray-200 dark:hover:border-emerald-500 dark:hover:text-emerald-300'
                  }`}
                >
                  <span className="block text-sm font-semibold">{POLICY_PRESETS[key].label}</span>
                  <span className="mt-1 block text-xs leading-5 text-gray-500 dark:text-gray-400">
                    {POLICY_PRESETS[key].description}
                  </span>
                </button>
              ))}
            </div>

            <div className="mb-4 rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-300">
              <div className="grid grid-cols-2 gap-2">
                <span>신뢰도 {form.minConfidence}% 이상</span>
                <span>최대 비중 {form.maxAllocationPct}%</span>
                <span>익절 {form.takeProfitPct}%</span>
                <span>손절 {form.stopLossPct}%</span>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setShowAdvancedPolicy((current) => !current)}
              className="mb-4 inline-flex w-full items-center justify-center gap-2 rounded-md border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-700 transition hover:border-emerald-400 hover:text-emerald-700 dark:border-gray-700 dark:text-gray-200 dark:hover:border-emerald-500 dark:hover:text-emerald-300"
            >
              <SlidersHorizontal className="h-4 w-4" />
              {showAdvancedPolicy ? '고급 설정 닫기' : '고급 설정 열기'}
            </button>

            {showAdvancedPolicy && (
              <div className="grid grid-cols-2 gap-3">
              <NumberInput
                label="빠른 EMA"
                value={form.emaFast}
                onChange={(value) => updatePolicyField('emaFast', value)}
                min={2}
                step={1}
              />
              <NumberInput
                label="느린 EMA"
                value={form.emaSlow}
                onChange={(value) => updatePolicyField('emaSlow', value)}
                min={3}
                step={1}
              />
              <NumberInput
                label="RSI 기간"
                value={form.rsiPeriod}
                onChange={(value) => updatePolicyField('rsiPeriod', value)}
                min={2}
                step={1}
              />
              <NumberInput
                label="RSI 기준"
                value={form.rsiMin}
                onChange={(value) => updatePolicyField('rsiMin', value)}
                min={1}
                step={1}
              />
              <NumberInput
                label="트레일링 스탑"
                value={form.trailingStopPct}
                onChange={(value) =>
                  updatePolicyField('trailingStopPct', value)
                }
                suffix="%"
                min={0}
                step={0.1}
              />
              <NumberInput
                label="최소 신뢰도"
                value={form.minConfidence}
                onChange={(value) =>
                  updatePolicyField('minConfidence', value)
                }
                suffix="%"
                min={0}
                step={1}
              />
              <NumberInput
                label="최대 비중"
                value={form.maxAllocationPct}
                onChange={(value) =>
                  updatePolicyField('maxAllocationPct', value)
                }
                suffix="%"
                min={0}
                step={1}
              />
              <NumberInput
                label="익절"
                value={form.takeProfitPct}
                onChange={(value) =>
                  updatePolicyField('takeProfitPct', value)
                }
                suffix="%"
                min={0}
                step={0.1}
              />
              <NumberInput
                label="손절"
                value={form.stopLossPct}
                onChange={(value) => updatePolicyField('stopLossPct', value)}
                suffix="%"
                step={0.1}
              />
              <NumberInput
                label="쿨다운"
                value={form.cooldownMinutes}
                onChange={(value) =>
                  updatePolicyField('cooldownMinutes', value)
                }
                suffix="분"
                min={0}
                step={1}
              />
              </div>
            )}

            {error && (
              <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
                {error}
              </div>
            )}

            <button
              type="button"
              onClick={() => void handleRun()}
              disabled={isRunning || isBootstrapping}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-md bg-emerald-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {isRunning ? '검증 중...' : '정책 백테스트 실행'}
            </button>
          </section>
        </aside>

        <main className="min-w-0 space-y-6">
          <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                  <Bot className="h-4 w-4" />
                  AI 분석
                </p>
                <h2 className="mt-2 text-2xl font-bold">백테스트 브리핑</h2>
              </div>
              {result?.ai_briefing?.fallback && (
                <span className="inline-flex w-fit rounded-md border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
                  로컬 요약
                </span>
              )}
            </div>

            <div className="mt-5 rounded-md border border-gray-200 bg-gray-50 p-4 text-sm leading-7 text-gray-700 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-200">
              {result?.ai_briefing?.content ??
                '정책 백테스트를 실행하면 AI가 성과, 리스크, 다음 조정 포인트를 요약합니다.'}
            </div>
          </section>

          {result ? (
            <>
              <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
                <KpiCard
                  label="총 수익률"
                  value={formatPercent(result.summary.total_return_pct)}
                  tone={result.summary.total_return_pct >= 0 ? 'positive' : 'negative'}
                />
                <KpiCard
                  label="최종 자산"
                  value={formatKrw(result.meta.final_balance)}
                  tone={finalPnl >= 0 ? 'positive' : 'negative'}
                />
                <KpiCard
                  label="손익"
                  value={`${finalPnl >= 0 ? '+' : '-'}${formatKrw(Math.abs(finalPnl))}`}
                  tone={finalPnl >= 0 ? 'positive' : 'negative'}
                />
                <KpiCard
                  label="최대 낙폭"
                  value={formatPercent(-result.summary.max_drawdown_pct)}
                  tone={result.summary.max_drawdown_pct <= 10 ? 'neutral' : 'negative'}
                />
                <KpiCard label="거래 수" value={`${result.summary.number_of_trades}회`} tone="neutral" />
              </section>

              <section className="rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-gray-900">
                <div className="flex flex-col gap-3 border-b border-gray-200 p-4 dark:border-gray-800 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <h2 className="text-lg font-bold">{result.meta.market}</h2>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      {new Date(result.meta.start_date).toLocaleDateString('ko-KR')} -{' '}
                      {new Date(result.meta.end_date).toLocaleDateString('ko-KR')} ·{' '}
                      {result.meta.timeframe}
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:flex">
                    <ResultTabButton
                      active={activeTab === 'price'}
                      icon={<BarChart3 className="h-4 w-4" />}
                      label="가격"
                      onClick={() => setActiveTab('price')}
                    />
                    <ResultTabButton
                      active={activeTab === 'equity'}
                      icon={<LineChartIcon className="h-4 w-4" />}
                      label="자산"
                      onClick={() => setActiveTab('equity')}
                    />
                    <ResultTabButton
                      active={activeTab === 'drawdown'}
                      icon={<Activity className="h-4 w-4" />}
                      label="낙폭"
                      onClick={() => setActiveTab('drawdown')}
                    />
                    <ResultTabButton
                      active={activeTab === 'trades'}
                      icon={<Table2 className="h-4 w-4" />}
                      label="거래"
                      onClick={() => setActiveTab('trades')}
                    />
                  </div>
                </div>

                <div className="p-4">
                  {activeTab === 'price' && <PriceChart result={result} isDarkMode={isDarkMode} />}
                  {activeTab === 'equity' && (
                    <CurveChart data={equityData} mode="equity" isDarkMode={isDarkMode} />
                  )}
                  {activeTab === 'drawdown' && (
                    <CurveChart data={drawdownData} mode="drawdown" isDarkMode={isDarkMode} />
                  )}
                  {activeTab === 'trades' && <TradeTable result={result} />}
                </div>
              </section>
            </>
          ) : (
            <section className="flex min-h-[520px] items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center dark:border-gray-700 dark:bg-gray-900">
              <div>
                <Brain className="mx-auto h-10 w-10 text-emerald-500" />
                <h2 className="mt-4 text-xl font-bold">검증 결과 없음</h2>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  좌측 정책을 조정한 뒤 백테스트를 실행하세요.
                </p>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  )
}

function KpiCard({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone: 'positive' | 'negative' | 'neutral'
}) {
  const colorClass =
    tone === 'positive'
      ? 'text-emerald-600 dark:text-emerald-300'
      : tone === 'negative'
        ? 'text-rose-600 dark:text-rose-300'
        : 'text-gray-900 dark:text-gray-100'

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">{label}</p>
      <p className={`mt-2 text-2xl font-bold ${colorClass}`}>{value}</p>
    </div>
  )
}

function ResultTabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean
  icon: ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition ${
        active
          ? 'bg-emerald-600 text-white'
          : 'border border-gray-200 text-gray-600 hover:border-emerald-400 hover:text-emerald-700 dark:border-gray-700 dark:text-gray-300 dark:hover:border-emerald-500 dark:hover:text-emerald-300'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

function TradeTable({ result }: { result: BacktestRunResponse }) {
  if (result.trades.length === 0) {
    return (
      <div className="flex min-h-[320px] items-center justify-center text-sm text-gray-500 dark:text-gray-400">
        체결된 거래가 없습니다.
      </div>
    )
  }

  return (
    <div className="max-h-[460px] overflow-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
        <thead className="sticky top-0 bg-gray-50 text-xs uppercase text-gray-500 dark:bg-gray-950 dark:text-gray-400">
          <tr>
            <th className="px-3 py-3 text-left">시간</th>
            <th className="px-3 py-3 text-left">구분</th>
            <th className="px-3 py-3 text-right">가격</th>
            <th className="px-3 py-3 text-right">수량</th>
            <th className="px-3 py-3 text-right">신뢰도</th>
            <th className="px-3 py-3 text-left">사유</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
          {result.trades.map((trade) => (
            <tr key={`${trade.index}-${trade.timestamp}`} className="hover:bg-gray-50 dark:hover:bg-gray-800/60">
              <td className="whitespace-nowrap px-3 py-3 text-gray-600 dark:text-gray-300">
                {new Date(trade.timestamp).toLocaleString('ko-KR')}
              </td>
              <td className="px-3 py-3">
                <span
                  className={`rounded px-2 py-1 text-xs font-semibold ${
                    trade.side === 'buy'
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
                      : 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'
                  }`}
                >
                  {trade.side.toUpperCase()}
                </span>
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-right">{formatKrw(trade.price)}</td>
              <td className="whitespace-nowrap px-3 py-3 text-right">
                {trade.qty.toFixed(8)}
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-right">
                {trade.confidence ?? '-'}
              </td>
              <td className="min-w-40 px-3 py-3 text-gray-600 dark:text-gray-300">
                {trade.reason ?? '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default LaboratoryPage
