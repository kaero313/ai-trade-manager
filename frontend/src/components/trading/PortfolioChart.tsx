import { useEffect, useRef, useState } from 'react'
import { Cell, Legend, Pie, PieChart, Tooltip } from 'recharts'

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
  '#f59e0b', // 황금 (KRW: 현금)
  '#3b82f6', // 하늘 파랑 (BTC)
  '#10b981', // 에메랄드 초록
  '#ef4444', // 선명한 빨강
  '#8b5cf6', // 보라
  '#06b6d4', // 시안
  '#f97316', // 주황
  '#ec4899', // 핫핑크
  '#a3e635', // 라임 초록
  '#64748b', // 슬레이트 회색
]

const CHART_HEIGHT = 320
const MIN_CHART_WIDTH = 240

function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const node = ref.current
    if (!node) {
      return
    }

    let frameId = 0
    const measure = () => {
      window.cancelAnimationFrame(frameId)
      frameId = window.requestAnimationFrame(() => {
        const nextWidth = Math.floor(node.getBoundingClientRect().width)
        setWidth((previousWidth) => (previousWidth === nextWidth ? previousWidth : nextWidth))
      })
    }

    measure()
    const resizeObserver = new ResizeObserver(measure)
    resizeObserver.observe(node)

    return () => {
      window.cancelAnimationFrame(frameId)
      resizeObserver.disconnect()
    }
  }, [])

  return [ref, width] as const
}

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
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-md dark:border-gray-700 dark:bg-gray-800">
      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{item.name}</p>
      <p className="mt-1 text-xs text-gray-600 dark:text-gray-300">평가금액: {formatKrw(item.value)}</p>
      <p className="text-xs text-gray-600 dark:text-gray-300">비중: {item.percent.toFixed(1)}%</p>
    </div>
  )
}

function PortfolioChart({ items, isLoading }: PortfolioChartProps) {
  const chartData = buildChartData(items)
  const hasData = chartData.length > 0
  const [chartContainerRef, measuredWidth] = useMeasuredWidth()
  const chartWidth = measuredWidth > 0 ? Math.max(MIN_CHART_WIDTH, measuredWidth) : 0

  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Portfolio Allocation</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">보유 자산 평가금액 비중</p>
      </header>

      {isLoading && (
        <div className="flex h-72 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-700/40 dark:text-gray-300">
          자산 비중 차트를 불러오는 중입니다.
        </div>
      )}

      {!isLoading && !hasData && (
        <div className="flex h-72 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-700/40 dark:text-gray-300">
          비중 데이터를 표시할 수 없습니다.
        </div>
      )}

      {!isLoading && hasData && (
        <div ref={chartContainerRef} className="h-80 w-full">
          {chartWidth > 0 && (
            <PieChart width={chartWidth} height={CHART_HEIGHT}>
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
          )}
        </div>
      )}
    </section>
  )
}

export default PortfolioChart
