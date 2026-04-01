import { Loader2 } from 'lucide-react'

import { useAIPerformance } from '../../hooks/useAIPerformance'

function formatKrw(value: number): string {
  const rounded = Math.round(Math.abs(value))
  return `₩${new Intl.NumberFormat('ko-KR').format(rounded)}`
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

function formatCount(value: number): string {
  return `${new Intl.NumberFormat('ko-KR').format(Math.round(value))}건`
}

function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`
}

function formatQty(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  }).format(value)
}

function formatExecutedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

function resolveWinRateTone(winRate: number): string {
  if (winRate >= 50) {
    return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
  }
  return 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300'
}

function resolvePnlTone(totalRealizedPnlKrw: number): string {
  if (totalRealizedPnlKrw > 0) {
    return 'text-emerald-600 dark:text-emerald-300'
  }
  if (totalRealizedPnlKrw < 0) {
    return 'text-rose-600 dark:text-rose-300'
  }
  return 'text-gray-900 dark:text-gray-100'
}

function resolveSideStyle(side: string): { label: string; className: string } {
  const normalized = side.toUpperCase()
  if (normalized === 'BUY') {
    return {
      label: 'BUY',
      className: 'bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
    }
  }
  if (normalized === 'SELL') {
    return {
      label: 'SELL',
      className: 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300',
    }
  }
  return {
    label: normalized,
    className: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  }
}

function KpiCard({
  title,
  value,
  hint,
  valueClassName = 'text-gray-900 dark:text-gray-100',
  badge,
}: {
  title: string
  value: string
  hint: string
  valueClassName?: string
  badge?: { label: string; className: string }
}) {
  return (
    <article className="rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/60">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {title}
          </p>
          <p className={`mt-3 text-2xl font-semibold ${valueClassName}`}>{value}</p>
        </div>
        {badge && (
          <span
            className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ${badge.className}`}
          >
            {badge.label}
          </span>
        )}
      </div>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{hint}</p>
    </article>
  )
}

function AiPerformanceWidget() {
  const performanceQuery = useAIPerformance()
  const performance = performanceQuery.data
  const hasData = performance !== undefined

  if (performanceQuery.isLoading && !hasData) {
    return (
      <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <header className="border-b border-gray-200 px-5 py-4 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">AI Performance</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">AI 자율 체결 성과 요약</p>
        </header>
        <div className="flex h-80 items-center justify-center gap-3 px-5 py-8 text-sm text-gray-500 dark:text-gray-300">
          <Loader2 className="h-5 w-5 animate-spin" />
          AI 매매 성과를 불러오는 중입니다.
        </div>
      </section>
    )
  }

  if (performanceQuery.isError && !hasData) {
    return (
      <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <header className="border-b border-gray-200 px-5 py-4 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">AI Performance</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">AI 자율 체결 성과 요약</p>
        </header>
        <div className="p-5">
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            AI 매매 성과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </div>
        </div>
      </section>
    )
  }

  const summary = performance ?? {
    total_trades: 0,
    winning_trades: 0,
    losing_trades: 0,
    win_rate: 0,
    total_realized_pnl_krw: 0,
    avg_confidence: 0,
    recent_trades: [],
  }

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="border-b border-gray-200 px-5 py-4 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">AI Performance</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">AI 자율 체결 성과 요약</p>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-5 p-5">
        {performanceQuery.isError && hasData && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">
            최신 성과 데이터를 다시 가져오지 못했습니다. 최근 캐시 기준으로 표시합니다.
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <KpiCard title="총 거래 건수" value={formatCount(summary.total_trades)} hint="AI 체결 완료 건수" />
          <KpiCard
            title="승률"
            value={formatPercentage(summary.win_rate)}
            hint={`${summary.winning_trades}승 / ${summary.losing_trades}패`}
            badge={{
              label: summary.win_rate >= 50 ? '양호' : '주의',
              className: resolveWinRateTone(summary.win_rate),
            }}
          />
          <KpiCard
            title="총 실현 손익"
            value={formatSignedKrw(summary.total_realized_pnl_krw)}
            hint="닫힌 포지션 기준 누적 손익"
            valueClassName={resolvePnlTone(summary.total_realized_pnl_krw)}
          />
          <KpiCard
            title="평균 확신도"
            value={formatPercentage(summary.avg_confidence)}
            hint="AI 지시 confidence 평균"
          />
        </div>

        <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/50">
          <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">최근 AI 체결</h3>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">최근 20건 기준 체결 로그</p>
          </div>

          <div className="max-h-[320px] overflow-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
              <thead className="bg-gray-100 text-left text-gray-600 dark:bg-gray-800 dark:text-gray-300">
                <tr>
                  <th className="px-4 py-3 font-semibold">종목</th>
                  <th className="px-4 py-3 font-semibold">방향</th>
                  <th className="px-4 py-3 font-semibold">체결가</th>
                  <th className="px-4 py-3 font-semibold">수량</th>
                  <th className="px-4 py-3 font-semibold">AI 확신도</th>
                  <th className="px-4 py-3 font-semibold">시각</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-700 dark:bg-gray-800">
                {summary.recent_trades.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-500 dark:text-gray-300">
                      최근 AI 체결 내역이 없습니다.
                    </td>
                  </tr>
                )}

                {summary.recent_trades.map((trade, index) => {
                  const sideStyle = resolveSideStyle(trade.side)
                  return (
                    <tr
                      key={`${trade.symbol}-${trade.side}-${trade.executed_at}-${index}`}
                      className="text-gray-700 dark:text-gray-200"
                    >
                      <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">{trade.symbol}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex min-w-14 items-center justify-center rounded-full px-2.5 py-1 text-xs font-semibold ${sideStyle.className}`}
                        >
                          {sideStyle.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-semibold text-gray-900 dark:text-gray-100">
                        {formatKrw(trade.price)}
                      </td>
                      <td className="px-4 py-3">{formatQty(trade.qty)}</td>
                      <td className="px-4 py-3">{formatPercentage(trade.confidence)}</td>
                      <td className="px-4 py-3 whitespace-nowrap">{formatExecutedAt(trade.executed_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  )
}

export default AiPerformanceWidget
