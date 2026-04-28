import { useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { PortfolioSnapshotItem } from '../../services/portfolioService'
import {
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
  PORTFOLIO_TOOLTIP_CLASS_NAME,
} from './portfolioStyles'
import useMeasuredChartWidth from './useMeasuredChartWidth'

interface PortfolioPeriodPnlChartProps {
  snapshots: PortfolioSnapshotItem[]
  isLoading: boolean
}

type PeriodKey = '1d' | '7d' | '30d' | 'all'

interface PeriodOption {
  key: PeriodKey
  label: string
  days: number | null
}

interface PnlDatum {
  created_at: string
  total_net_worth: number
  pnl_delta: number
}

interface TooltipPayloadItem {
  value: number
  payload: PnlDatum
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string
}

const PERIOD_OPTIONS: PeriodOption[] = [
  { key: '1d', label: '1일', days: 1 },
  { key: '7d', label: '7일', days: 7 },
  { key: '30d', label: '30일', days: 30 },
  { key: 'all', label: '전체', days: null },
]

function formatKrw(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(Math.abs(safeValue)))}`
}

function formatSignedKrw(value: number): string {
  if (value > 0) {
    return `+${formatKrw(value)}`
  }
  if (value < 0) {
    return `-${formatKrw(value)}`
  }
  return formatKrw(value)
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

function resolveToneClassName(value: number): string {
  if (value > 0) {
    return 'text-emerald-600 dark:text-emerald-300'
  }
  if (value < 0) {
    return 'text-rose-600 dark:text-rose-300'
  }
  return 'text-gray-900 dark:text-gray-100'
}

function sortSnapshots(snapshots: PortfolioSnapshotItem[]): PortfolioSnapshotItem[] {
  return [...snapshots].sort((a, b) => {
    const left = new Date(a.created_at).getTime()
    const right = new Date(b.created_at).getTime()
    return left - right
  })
}

function filterSnapshotsByPeriod(
  snapshots: PortfolioSnapshotItem[],
  period: PeriodOption,
): PortfolioSnapshotItem[] {
  if (period.days === null || snapshots.length === 0) {
    return snapshots
  }

  const latestSnapshot = snapshots[snapshots.length - 1]
  const latestTime = new Date(latestSnapshot.created_at).getTime()
  if (Number.isNaN(latestTime)) {
    return snapshots
  }

  const cutoffTime = latestTime - period.days * 24 * 60 * 60 * 1000
  const filtered = snapshots.filter((snapshot) => {
    const snapshotTime = new Date(snapshot.created_at).getTime()
    return Number.isFinite(snapshotTime) && snapshotTime >= cutoffTime
  })

  return filtered.length > 0 ? filtered : [latestSnapshot]
}

function buildPnlData(
  snapshots: PortfolioSnapshotItem[],
  selectedPeriodKey: PeriodKey,
): PnlDatum[] {
  const sortedSnapshots = sortSnapshots(snapshots)
  const period = PERIOD_OPTIONS.find((option) => option.key === selectedPeriodKey) ?? PERIOD_OPTIONS[1]
  const periodSnapshots = filterSnapshotsByPeriod(sortedSnapshots, period)
  const firstSnapshot = periodSnapshots[0]

  if (!firstSnapshot) {
    return []
  }

  const baseNetWorth = Number(firstSnapshot.total_net_worth) || 0

  return periodSnapshots.map((snapshot) => {
    const totalNetWorth = Number(snapshot.total_net_worth) || 0
    return {
      created_at: snapshot.created_at,
      total_net_worth: totalNetWorth,
      pnl_delta: totalNetWorth - baseNetWorth,
    }
  })
}

function ChartLoadingState() {
  return (
    <div className={`${PORTFOLIO_PANEL_CLASS_NAME} h-[340px] animate-pulse p-5`}>
      <div className="h-full rounded-md border border-gray-200 bg-gray-100 dark:border-gray-700 dark:bg-gray-900">
        <div className="flex h-full items-end gap-3 px-5 pb-8">
          <div className="h-20 w-full rounded-t-lg bg-emerald-100 dark:bg-emerald-500/20" />
          <div className="h-32 w-full rounded-t-lg bg-emerald-100 dark:bg-emerald-500/20" />
          <div className="h-24 w-full rounded-t-lg bg-emerald-100 dark:bg-emerald-500/20" />
          <div className="h-40 w-full rounded-t-lg bg-emerald-100 dark:bg-emerald-500/20" />
          <div className="h-28 w-full rounded-t-lg bg-emerald-100 dark:bg-emerald-500/20" />
        </div>
      </div>
    </div>
  )
}

function ChartEmptyState() {
  return (
    <div className={`${PORTFOLIO_PANEL_CLASS_NAME} flex min-h-[300px] items-center justify-center px-6 text-center`}>
      <div>
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          기간 손익 데이터가 아직 없습니다.
        </p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          포트폴리오 스냅샷이 쌓이면 기간별 손익 변화가 표시됩니다.
        </p>
      </div>
    </div>
  )
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) {
    return null
  }

  const item = payload[0]
  return (
    <div className={`${PORTFOLIO_TOOLTIP_CLASS_NAME} px-4 py-3`}>
      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        {formatTooltipDate(label ?? item.payload.created_at)}
      </p>
      <p className={`mt-1 text-xs font-semibold ${resolveToneClassName(item.value)}`}>
        기간 손익: {formatSignedKrw(item.value)}
      </p>
      <p className="mt-1 text-xs text-gray-600 dark:text-gray-300">
        총 자산: {formatKrw(item.payload.total_net_worth)}
      </p>
    </div>
  )
}

function PortfolioPeriodPnlChart({
  snapshots,
  isLoading,
}: PortfolioPeriodPnlChartProps) {
  const [selectedPeriodKey, setSelectedPeriodKey] = useState<PeriodKey>('7d')
  const chartData = buildPnlData(snapshots, selectedPeriodKey)
  const latestDelta = chartData[chartData.length - 1]?.pnl_delta ?? 0
  const hasData = chartData.length > 0
  const { containerRef, width: chartWidth } = useMeasuredChartWidth({ minWidth: 560 })
  const resolvedChartWidth = Math.max((chartWidth || 560) - 32, 528)

  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} overflow-hidden p-6`}>
      <header className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>기간 손익 그래프</p>
          <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>기간 손익</h2>
          <p className={`mt-3 text-2xl font-semibold ${resolveToneClassName(latestDelta)}`}>
            {formatSignedKrw(latestDelta)}
          </p>
        </div>

        <div className="inline-flex w-full rounded-md border border-gray-200 bg-gray-50 p-1 dark:border-gray-700 dark:bg-gray-900 sm:w-auto">
          {PERIOD_OPTIONS.map((option) => {
            const isSelected = option.key === selectedPeriodKey
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => setSelectedPeriodKey(option.key)}
                className={`min-h-9 flex-1 rounded px-3 text-sm font-semibold transition sm:flex-none ${
                  isSelected
                    ? 'bg-white text-gray-950 shadow-sm dark:bg-gray-800 dark:text-white'
                    : 'text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100'
                }`}
              >
                {option.label}
              </button>
            )
          })}
        </div>
      </header>

      {isLoading ? <ChartLoadingState /> : null}
      {!isLoading && !hasData ? <ChartEmptyState /> : null}

      {!isLoading && hasData ? (
        <div className="-mx-2 overflow-x-auto px-2">
          <div
            ref={containerRef}
            className="h-[340px] min-w-[560px] rounded-md border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/60"
          >
            <ComposedChart
              width={resolvedChartWidth}
              height={308}
              data={chartData}
              margin={{ top: 20, right: 24, left: 8, bottom: 8 }}
            >
              <defs>
                <linearGradient id="periodPnlFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.32} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0.02} />
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
                tickFormatter={formatSignedKrw}
                tick={{ fill: '#64748b', fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={100}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine yAxisId="left" y={0} stroke="#94a3b8" strokeDasharray="3 3" />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="pnl_delta"
                stroke="none"
                fill="url(#periodPnlFill)"
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="pnl_delta"
                stroke="#10b981"
                strokeWidth={3}
                dot={false}
                activeDot={{ r: 5, fill: '#10b981', stroke: '#ffffff', strokeWidth: 2 }}
              />
            </ComposedChart>
          </div>
        </div>
      ) : null}
    </section>
  )
}

export default PortfolioPeriodPnlChart
