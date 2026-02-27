import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import type { AssetItem } from '../../services/portfolioService'

interface PortfolioChartProps {
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
  '#0f172a',
  '#1d4ed8',
  '#0f766e',
  '#16a34a',
  '#d97706',
  '#dc2626',
  '#9333ea',
  '#0891b2',
  '#4f46e5',
  '#475569',
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
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-md">
      <p className="text-sm font-semibold text-slate-900">{item.name}</p>
      <p className="mt-1 text-xs text-slate-600">평가금액: {formatKrw(item.value)}</p>
      <p className="text-xs text-slate-600">비중: {item.percent.toFixed(1)}%</p>
    </div>
  )
}

function PortfolioChart({ items, isLoading }: PortfolioChartProps) {
  const chartData = buildChartData(items)
  const hasData = chartData.length > 0

  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Portfolio Allocation</h2>
        <p className="mt-1 text-sm text-slate-500">보유 자산 평가금액 비중</p>
      </header>

      {isLoading && (
        <div className="flex h-72 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-500">
          자산 비중 차트를 불러오는 중입니다.
        </div>
      )}

      {!isLoading && !hasData && (
        <div className="flex h-72 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-500">
          비중 데이터를 표시할 수 없습니다.
        </div>
      )}

      {!isLoading && hasData && (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="45%"
                innerRadius={68}
                outerRadius={112}
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
                verticalAlign="bottom"
                align="center"
                formatter={(value, _entry, index) => {
                  const item = chartData[index]
                  return `${value} (${item.percent.toFixed(1)}%)`
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}

export default PortfolioChart
