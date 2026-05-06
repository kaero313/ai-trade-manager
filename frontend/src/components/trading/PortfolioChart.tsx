import { useEffect, useRef, useState } from 'react'
import { Cell, Legend, Pie, PieChart, Tooltip } from 'recharts'

import type { AssetItem, PortfolioSummary } from '../../services/portfolioService'

interface PortfolioChartProps {
  items: AssetItem[]
  isLoading: boolean
  source: PortfolioSummary['source'] | null
  isStale: boolean
  updatedAt: string | null
  errorCode?: string | null
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

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral'

interface PortfolioStatusView {
  label: string
  tone: StatusTone
  description: string
  notice: string | null
}

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

function formatUpdatedAt(value: string | null): string | null {
  if (!value) {
    return null
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }

  return date.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function resolveErrorMessage(errorCode?: string | null): string {
  if (errorCode === 'PORTFOLIO_FETCH_TIMEOUT') {
    return '실시간 자산 조회가 지연되어 마지막 스냅샷을 표시하고 있습니다.'
  }
  if (errorCode === 'UPBIT_KEY_MISSING') {
    return 'Upbit API 키가 없어 실시간 자산을 조회할 수 없습니다.'
  }
  if (errorCode) {
    return '실시간 자산 조회에 실패해 마지막 정상값을 유지하고 있습니다.'
  }
  return '최신 자산 조회가 지연되어 마지막 정상값을 유지하고 있습니다.'
}

function resolveStatusClassName(tone: StatusTone): string {
  if (tone === 'success') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
  }
  if (tone === 'warning') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'
  }
  if (tone === 'danger') {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'
  }
  return 'border-gray-200 bg-gray-50 text-gray-600 dark:border-gray-600 dark:bg-gray-700/40 dark:text-gray-300'
}

function resolvePortfolioStatus({
  source,
  isStale,
  updatedAt,
  errorCode,
}: {
  source: PortfolioSummary['source'] | null
  isStale: boolean
  updatedAt: string | null
  errorCode?: string | null
}): PortfolioStatusView {
  const updatedAtLabel = formatUpdatedAt(updatedAt)
  const suffix = updatedAtLabel ? ` 마지막 갱신 ${updatedAtLabel}` : ' 마지막 갱신 없음'

  if (source === 'live' && !isStale) {
    return {
      label: '실시간',
      tone: 'success',
      description: `실시간 자산 기준입니다.${suffix}`,
      notice: null,
    }
  }

  if (source === 'snapshot') {
    return {
      label: '스냅샷',
      tone: 'warning',
      description: `저장된 마지막 자산 스냅샷 기준입니다.${suffix}`,
      notice: resolveErrorMessage(errorCode),
    }
  }

  if (source === 'empty') {
    return {
      label: '조회 불가',
      tone: 'danger',
      description: '실시간 자산과 스냅샷을 모두 불러오지 못했습니다.',
      notice: resolveErrorMessage(errorCode),
    }
  }

  if (isStale) {
    return {
      label: '지연',
      tone: 'warning',
      description: `마지막 정상 조회값을 표시하고 있습니다.${suffix}`,
      notice: resolveErrorMessage(errorCode),
    }
  }

  return {
    label: '대기',
    tone: 'neutral',
    description: '자산 조회를 준비하고 있습니다.',
    notice: null,
  }
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

function PortfolioChart({
  items,
  isLoading,
  source,
  isStale,
  updatedAt,
  errorCode = null,
}: PortfolioChartProps) {
  const chartData = buildChartData(items)
  const hasData = chartData.length > 0
  const [chartContainerRef, measuredWidth] = useMeasuredWidth()
  const chartWidth = measuredWidth > 0 ? Math.max(MIN_CHART_WIDTH, measuredWidth) : 0
  const status = resolvePortfolioStatus({ source, isStale, updatedAt, errorCode })

  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">자산 배분</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">{status.description}</p>
        </div>
        <span
          className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${resolveStatusClassName(
            status.tone,
          )}`}
        >
          {status.label}
        </span>
      </header>

      {status.notice && (
        <div
          className={`mb-4 rounded-xl border px-3 py-2.5 text-sm font-medium ${resolveStatusClassName(
            status.tone,
          )}`}
        >
          {status.notice}
        </div>
      )}

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
