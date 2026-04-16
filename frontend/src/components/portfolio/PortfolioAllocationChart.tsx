import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import type { AssetItem } from '../../services/portfolioService'

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
    <div className="rounded-2xl border border-white/70 bg-white/90 px-4 py-3 shadow-[0_24px_60px_-30px_rgba(15,23,42,0.45)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/90 dark:shadow-[0_24px_60px_-30px_rgba(2,6,23,0.95)]">
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{item.name}</p>
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
        평가금액: {formatKrw(item.value)}
      </p>
      <p className="text-xs text-slate-600 dark:text-slate-300">
        비중: {item.percent.toFixed(1)}%
      </p>
    </div>
  )
}

function ChartLoadingState() {
  return (
    <div className="relative overflow-hidden rounded-[24px] border border-white/55 bg-white/45 p-6 backdrop-blur dark:border-white/10 dark:bg-white/5">
      <div className="animate-pulse">
        <div className="h-3 w-28 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
        <div className="mt-3 h-5 w-48 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />

        <div className="mt-8 flex flex-col items-center justify-center gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="h-64 w-64 rounded-full border-[28px] border-slate-200/90 dark:border-slate-700/80" />
          <div className="grid w-full max-w-[180px] gap-3">
            <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
            <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
            <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
            <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
          </div>
        </div>
      </div>
    </div>
  )
}

function ChartEmptyState() {
  return (
    <div className="flex min-h-[420px] items-center justify-center rounded-[24px] border border-white/55 bg-white/45 px-6 text-center backdrop-blur dark:border-white/10 dark:bg-white/5">
      <div>
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          자산 배분 데이터를 표시할 수 없습니다
        </p>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
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

  return (
    <section className="relative overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-6 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.5)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.12),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.12),_transparent_32%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.14),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.14),_transparent_32%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative">
        <header className="mb-5">
          <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
            PORTFOLIO MIX
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
            자산 배분
          </h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            평가금액 기준으로 현재 포트폴리오 비중을 확인합니다.
          </p>
        </header>

        {isLoading ? <ChartLoadingState /> : null}
        {!isLoading && !hasData ? <ChartEmptyState /> : null}

        {!isLoading && hasData ? (
          <div className="-mx-2 overflow-x-auto px-2">
            <div className="h-[420px] min-w-[560px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={chartData}
                    dataKey="value"
                    nameKey="name"
                    cx="34%"
                    cy="50%"
                    innerRadius={80}
                    outerRadius={140}
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
                    layout="vertical"
                    align="right"
                    verticalAlign="middle"
                    iconType="circle"
                    wrapperStyle={{ paddingLeft: '20px' }}
                    formatter={(value, _entry, index) => {
                      const item = chartData[index]
                      return `${value} (${item.percent.toFixed(1)}%)`
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default PortfolioAllocationChart
