import { useQuery } from '@tanstack/react-query'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiClient } from '../../services/api'
import type { MarketSentimentSnapshot } from '../../services/api'
import type { PortfolioSnapshotItem } from '../../services/portfolioService'
import useMeasuredChartWidth from './useMeasuredChartWidth'

interface PortfolioTrendChartProps {
  snapshots: PortfolioSnapshotItem[]
  isLoading: boolean
}

interface TrendDatum {
  created_at: string
  total_net_worth: number
}

interface TooltipPayloadItem {
  value: number
  payload: TrendDatum
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string
}

type SentimentTone = {
  emoji: string
  label: string
  badgeClassName: string
}

function formatKrw(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(safeValue))}`
}

function formatAxisDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function formatTooltipDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function clampScore(score: number): number {
  if (!Number.isFinite(score)) {
    return 0
  }

  return Math.max(0, Math.min(100, Math.round(score)))
}

function resolveSentimentTone(score: number): SentimentTone {
  if (score <= 25) {
    return {
      emoji: '🔴',
      label: '극단적 공포',
      badgeClassName:
        'border border-rose-200/80 bg-rose-50 text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/15 dark:text-rose-200',
    }
  }

  if (score <= 45) {
    return {
      emoji: '🟠',
      label: '공포',
      badgeClassName:
        'border border-orange-200/80 bg-orange-50 text-orange-700 dark:border-orange-300/20 dark:bg-orange-500/15 dark:text-orange-200',
    }
  }

  if (score <= 55) {
    return {
      emoji: '🟡',
      label: '중립',
      badgeClassName:
        'border border-amber-200/80 bg-amber-50 text-amber-700 dark:border-amber-300/20 dark:bg-amber-500/15 dark:text-amber-200',
    }
  }

  if (score <= 75) {
    return {
      emoji: '🟢',
      label: '탐욕',
      badgeClassName:
        'border border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200',
    }
  }

  return {
    emoji: '🔵',
    label: '극단적 탐욕',
    badgeClassName:
      'border border-sky-200/80 bg-sky-50 text-sky-700 dark:border-sky-300/20 dark:bg-sky-500/15 dark:text-sky-200',
  }
}

function buildTrendData(snapshots: PortfolioSnapshotItem[]): TrendDatum[] {
  return [...snapshots]
    .reverse()
    .map((snapshot) => ({
      created_at: snapshot.created_at,
      total_net_worth: Number(snapshot.total_net_worth) || 0,
    }))
}

function TrendLoadingState() {
  return (
    <div className="relative overflow-hidden rounded-[24px] border border-white/55 bg-white/45 p-6 backdrop-blur dark:border-white/10 dark:bg-white/5">
      <div className="animate-pulse">
        <div className="h-3 w-28 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
        <div className="mt-3 h-5 w-52 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />

        <div className="mt-8 h-[360px] rounded-[24px] border border-white/50 bg-white/40 dark:border-white/10 dark:bg-white/5">
          <div className="flex h-full items-end gap-3 px-6 pb-8">
            <div className="h-24 w-full rounded-t-3xl bg-emerald-100/90 dark:bg-emerald-500/20" />
            <div className="h-36 w-full rounded-t-3xl bg-emerald-100/90 dark:bg-emerald-500/20" />
            <div className="h-28 w-full rounded-t-3xl bg-emerald-100/90 dark:bg-emerald-500/20" />
            <div className="h-40 w-full rounded-t-3xl bg-emerald-100/90 dark:bg-emerald-500/20" />
            <div className="h-52 w-full rounded-t-3xl bg-emerald-100/90 dark:bg-emerald-500/20" />
          </div>
        </div>
      </div>
    </div>
  )
}

function TrendEmptyState() {
  return (
    <div className="flex min-h-[420px] items-center justify-center rounded-[24px] border border-white/55 bg-white/45 px-6 text-center backdrop-blur dark:border-white/10 dark:bg-white/5">
      <div>
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          아직 수집된 자산 추이 데이터가 없습니다.
        </p>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
          포트폴리오 스냅샷이 쌓이면 총 자산 추이를 이 영역에서 확인할 수 있습니다.
        </p>
      </div>
    </div>
  )
}

function TrendCanvasPlaceholder() {
  return (
    <div className="flex h-[420px] min-w-[640px] w-full items-center justify-center rounded-[24px] border border-white/55 bg-white/45 px-6 text-center backdrop-blur dark:border-white/10 dark:bg-white/5">
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
        자산 추이 차트를 불러오는 중입니다...
      </p>
    </div>
  )
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) {
    return null
  }

  const item = payload[0]
  return (
    <div className="rounded-2xl border border-white/70 bg-white/90 px-4 py-3 shadow-[0_24px_60px_-30px_rgba(15,23,42,0.45)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/90 dark:shadow-[0_24px_60px_-30px_rgba(2,6,23,0.95)]">
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
        {formatTooltipDate(label ?? item.payload.created_at)}
      </p>
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
        총 자산: {formatKrw(item.value)}
      </p>
    </div>
  )
}

function SentimentOverlay({
  snapshot,
  isError,
}: {
  snapshot: MarketSentimentSnapshot | undefined
  isError: boolean
}) {
  if (!snapshot || isError) {
    return (
      <div className="absolute right-6 top-6 z-10 rounded-2xl border border-slate-200/80 bg-white/85 px-4 py-3 shadow-[0_16px_36px_-28px_rgba(15,23,42,0.5)] backdrop-blur-xl dark:border-slate-700/80 dark:bg-slate-900/85">
        <p className="text-[11px] font-semibold tracking-[0.2em] text-slate-500 dark:text-slate-400">
          AI SENTIMENT
        </p>
        <p className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
          공포/탐욕: -
        </p>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">정보 없음</p>
      </div>
    )
  }

  const score = clampScore(snapshot.score)
  const tone = resolveSentimentTone(score)

  return (
    <div
      className={`absolute right-6 top-6 z-10 rounded-2xl px-4 py-3 shadow-[0_16px_36px_-28px_rgba(15,23,42,0.5)] backdrop-blur-xl ${tone.badgeClassName}`}
    >
      <p className="text-[11px] font-semibold tracking-[0.2em] opacity-80">AI SENTIMENT</p>
      <p className="mt-2 text-sm font-semibold">{`공포/탐욕: ${score}`}</p>
      <p className="mt-1 text-xs">{`${tone.emoji} ${tone.label}`}</p>
    </div>
  )
}

function PortfolioTrendChart({
  snapshots,
  isLoading,
}: PortfolioTrendChartProps) {
  const trendData = buildTrendData(snapshots)
  const hasData = trendData.length > 0
  const { containerRef, width: chartWidth } = useMeasuredChartWidth({ minWidth: 640 })

  const sentimentQuery = useQuery({
    queryKey: ['portfolio-trend-market-sentiment'],
    queryFn: async () => {
      const response = await apiClient.get<MarketSentimentSnapshot>('/markets/sentiment')
      return response.data
    },
    refetchInterval: 1000 * 60 * 5,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  return (
    <section className="relative overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-6 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.5)] backdrop-blur-xl transition-shadow duration-200 hover:shadow-[0_36px_110px_-44px_rgba(15,23,42,0.58)] dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_36px_110px_-44px_rgba(2,6,23,1)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.16),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(59,130,246,0.12),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.18),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(56,189,248,0.14),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative">
        <header className="mb-5 pr-[180px]">
          <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
            PORTFOLIO TREND
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
            총 자산 추이
          </h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            시간에 따른 포트폴리오 총 순자산 변화를 확인합니다.
          </p>
        </header>

        <SentimentOverlay
          snapshot={sentimentQuery.data}
          isError={sentimentQuery.isError && !sentimentQuery.data}
        />

        {isLoading ? <TrendLoadingState /> : null}
        {!isLoading && !hasData ? <TrendEmptyState /> : null}

        {!isLoading && hasData ? (
          <div className="-mx-2 overflow-x-auto px-2">
            <div
              ref={containerRef}
              className="h-[420px] min-w-[640px] w-full rounded-[24px] border border-white/55 bg-white/45 p-4 backdrop-blur dark:border-white/10 dark:bg-white/5"
            >
              {chartWidth > 0 ? (
                <ComposedChart
                  width={Math.max(chartWidth - 32, 608)}
                  height={388}
                  data={trendData}
                  margin={{ top: 20, right: 24, left: 8, bottom: 8 }}
                >
                  <defs>
                    <linearGradient id="portfolioTrendFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#10b981" stopOpacity={0.03} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="rgba(148, 163, 184, 0.26)"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="created_at"
                    tickFormatter={formatAxisDate}
                    tick={{ fill: '#64748b', fontSize: 12 }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={24}
                  />
                  <YAxis
                    yAxisId="left"
                    tickFormatter={formatKrw}
                    tick={{ fill: '#64748b', fontSize: 12 }}
                    tickLine={false}
                    axisLine={false}
                    width={100}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Area
                    yAxisId="left"
                    type="monotone"
                    dataKey="total_net_worth"
                    stroke="none"
                    fill="url(#portfolioTrendFill)"
                  />
                  <Line
                    yAxisId="left"
                    type="monotone"
                    dataKey="total_net_worth"
                    stroke="#10b981"
                    strokeWidth={3}
                    dot={false}
                    activeDot={{ r: 5, fill: '#10b981', stroke: '#ffffff', strokeWidth: 2 }}
                  />
                </ComposedChart>
              ) : (
                <TrendCanvasPlaceholder />
              )}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default PortfolioTrendChart
