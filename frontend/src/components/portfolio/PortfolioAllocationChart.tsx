import { Cell, Legend, Pie, PieChart, Tooltip } from 'recharts'

import type { AssetItem } from '../../services/portfolioService'
import {
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
  PORTFOLIO_TOOLTIP_CLASS_NAME,
} from './portfolioStyles'
import useMeasuredChartWidth from './useMeasuredChartWidth'

interface PortfolioAllocationChartProps {
  items: AssetItem[]
  isLoading: boolean
}

interface ChartDatum {
  name: string
  value: number
  percent: number
  color: string
}

interface TooltipPayloadItem {
  payload: ChartDatum
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
}

const COLORS = [
  '#f59e0b',
  '#3b82f6',
  '#10b981',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#f97316',
  '#ec4899',
  '#a3e635',
  '#64748b',
]

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function buildChartData(items: AssetItem[]): ChartDatum[] {
  const grouped = new Map<string, number>()

  for (const item of items) {
    const currency = String(item.currency || '').trim().toUpperCase() || 'UNKNOWN'
    const value = Number(item.total_value)
    if (!Number.isFinite(value) || value <= 0) {
      continue
    }

    grouped.set(currency, (grouped.get(currency) ?? 0) + value)
  }

  const sorted = Array.from(grouped.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  const total = sorted.reduce((acc, item) => acc + item.value, 0)
  if (total <= 0) {
    return []
  }

  return sorted.map((item, index) => ({
    name: item.name,
    value: item.value,
    percent: (item.value / total) * 100,
    color: COLORS[index % COLORS.length],
  }))
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) {
    return null
  }

  const item = payload[0].payload
  return (
    <div className={`${PORTFOLIO_TOOLTIP_CLASS_NAME} px-4 py-3`}>
      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{item.name}</p>
      <p className="mt-1 text-xs text-gray-600 dark:text-gray-300">
        평가금액: {formatKrw(item.value)}
      </p>
      <p className="text-xs text-gray-600 dark:text-gray-300">
        비중: {item.percent.toFixed(1)}%
      </p>
    </div>
  )
}

function ChartLoadingState() {
  return (
    <div className={`${PORTFOLIO_PANEL_CLASS_NAME} relative overflow-hidden p-6`}>
      <div className="animate-pulse">
        <div className="h-3 w-28 rounded-full bg-gray-200 dark:bg-gray-700" />
        <div className="mt-3 h-5 w-48 rounded-full bg-gray-200 dark:bg-gray-700" />

        <div className="mt-8 flex flex-col items-center justify-center gap-5">
          <div className="h-44 w-44 rounded-full border-[22px] border-gray-200 dark:border-gray-700" />
          <div className="grid w-full max-w-[220px] gap-3">
            <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
          </div>
        </div>
      </div>
    </div>
  )
}

function ChartEmptyState() {
  return (
    <div className={`${PORTFOLIO_PANEL_CLASS_NAME} flex min-h-[320px] items-center justify-center px-6 text-center`}>
      <div>
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          자산 배분 데이터를 표시할 수 없습니다
        </p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          평가금액이 있는 자산이 생기면 포트폴리오 비중 차트가 이 영역에 표시됩니다.
        </p>
      </div>
    </div>
  )
}

function PortfolioAllocationChart({
  items,
  isLoading,
}: PortfolioAllocationChartProps) {
  const chartData = buildChartData(items)
  const hasData = chartData.length > 0
  const { containerRef, width: chartWidth } = useMeasuredChartWidth({ minWidth: 320 })
  const resolvedChartWidth = Math.max(chartWidth || 320, 320)

  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} overflow-hidden p-6`}>
      <div>
        <header className="mb-5">
          <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
            자산배분
          </p>
          <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>
            자산 배분
          </h2>
        </header>

        {isLoading ? <ChartLoadingState /> : null}
        {!isLoading && !hasData ? <ChartEmptyState /> : null}

        {!isLoading && hasData ? (
          <div className="-mx-2 overflow-x-auto px-2">
            <div ref={containerRef} className="h-[320px] min-w-[320px] w-full">
              <PieChart width={resolvedChartWidth} height={320}>
                <Pie
                  data={chartData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="42%"
                  innerRadius={58}
                  outerRadius={98}
                  paddingAngle={2}
                  stroke="#ffffff"
                  strokeWidth={2}
                >
                  {chartData.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
                <Legend
                  layout="horizontal"
                  align="center"
                  verticalAlign="bottom"
                  iconType="circle"
                  wrapperStyle={{ paddingTop: '12px' }}
                  formatter={(value, _entry, index) => {
                    const item = chartData[index]
                    return `${value} (${item.percent.toFixed(1)}%)`
                  }}
                />
              </PieChart>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default PortfolioAllocationChart
