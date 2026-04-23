import { Loader2 } from 'lucide-react'

import { useAIPerformance } from '../../hooks/useAIPerformance'

function formatKrw(value: number): string {
  const safeValue = Number.isFinite(value) ? Math.abs(value) : 0
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(safeValue))}`
}

function formatQty(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return new Intl.NumberFormat('ko-KR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  }).format(safeValue)
}

function formatConfidence(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `${safeValue.toFixed(1)}%`
}

function formatExecutedAt(value: string): string {
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

function resolveSideMeta(side: string): {
  emoji: string
  label: string
  chipClassName: string
  markerClassName: string
} {
  const normalized = side.trim().toUpperCase()

  if (normalized === 'SELL') {
    return {
      emoji: '🔴',
      label: '매도',
      chipClassName:
        'border border-rose-200/80 bg-rose-50 text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/15 dark:text-rose-200',
      markerClassName:
        'border border-rose-200/80 bg-white text-rose-600 shadow-[0_16px_34px_-24px_rgba(225,29,72,0.75)] dark:border-rose-300/20 dark:bg-slate-900/90 dark:text-rose-200',
    }
  }

  return {
    emoji: '🟢',
    label: '매수',
    chipClassName:
      'border border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200',
    markerClassName:
      'border border-emerald-200/80 bg-white text-emerald-600 shadow-[0_16px_34px_-24px_rgba(5,150,105,0.75)] dark:border-emerald-300/20 dark:bg-slate-900/90 dark:text-emerald-200',
  }
}

function TimelineLoadingState() {
  return (
    <div className="relative pl-14">
      <div className="absolute bottom-2 left-[23px] top-2 w-px bg-gradient-to-b from-emerald-300 via-emerald-400 to-teal-500 opacity-80 dark:from-emerald-400 dark:via-emerald-300 dark:to-cyan-400" />

      <div className="space-y-4">
        {Array.from({ length: 3 }, (_, index) => (
          <div
            key={`ai-trade-timeline-skeleton-${index}`}
            className="relative overflow-hidden rounded-[24px] border border-white/55 bg-white/45 p-5 backdrop-blur dark:border-white/10 dark:bg-white/5"
          >
            <div className="absolute left-[-52px] top-6 inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-emerald-200/80 bg-white text-emerald-500 shadow-[0_16px_34px_-24px_rgba(5,150,105,0.75)] dark:border-emerald-300/20 dark:bg-slate-900/90 dark:text-emerald-200">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>

            <div className="animate-pulse">
              <div className="grid gap-3 xl:grid-cols-[180px_112px_minmax(0,1fr)_140px_120px_140px] xl:items-center">
                <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
                <div className="h-9 rounded-full bg-emerald-100/90 dark:bg-emerald-500/20" />
                <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
                <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
                <div className="h-4 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
                <div className="h-9 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function EmptyTimelineState() {
  return (
    <div className="flex min-h-[260px] items-center justify-center rounded-[24px] border border-white/55 bg-white/45 px-6 text-center backdrop-blur dark:border-white/10 dark:bg-white/5">
      <div>
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          아직 AI가 실행한 거래가 없습니다.
        </p>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
          AI 매매가 발생하면 최근 거래 내역이 이 타임라인에 순서대로 쌓입니다.
        </p>
      </div>
    </div>
  )
}

function AiTradeTimeline() {
  const performanceQuery = useAIPerformance()
  const trades = performanceQuery.data?.recent_trades.slice(0, 10) ?? []
  const showLoading = performanceQuery.isLoading && !performanceQuery.data

  return (
    <section className="relative h-full overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-6 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.5)] backdrop-blur-xl transition-shadow duration-200 hover:shadow-[0_36px_110px_-44px_rgba(15,23,42,0.58)] dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_36px_110px_-44px_rgba(2,6,23,1)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.16),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(20,184,166,0.12),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.18),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(34,197,94,0.14),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative">
        <header className="mb-5">
          <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
            AI TRADE FLOW
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
            🤖 AI 매매 결정 타임라인
          </h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            최근 AI 매매 실행 기록을 시간순으로 확인합니다.
          </p>
        </header>

        {showLoading ? <TimelineLoadingState /> : null}
        {!showLoading && trades.length === 0 ? <EmptyTimelineState /> : null}

        {!showLoading && trades.length > 0 ? (
          <div className="relative pl-14">
            <div className="absolute bottom-4 left-[23px] top-3 w-px bg-gradient-to-b from-emerald-300 via-emerald-400 to-teal-500 opacity-90 dark:from-emerald-400 dark:via-emerald-300 dark:to-cyan-400" />

            <div className="space-y-4">
              {trades.map((trade, index) => {
                const sideMeta = resolveSideMeta(trade.side)

                return (
                  <article
                    key={`${trade.symbol}-${trade.side}-${trade.executed_at}-${index}`}
                    className="group relative overflow-hidden rounded-[24px] border border-white/55 bg-white/45 p-5 backdrop-blur transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:scale-[1.01] hover:shadow-lg dark:border-white/10 dark:bg-white/5"
                  >
                    <div
                      className={`absolute left-[-52px] top-6 inline-flex h-11 w-11 items-center justify-center rounded-2xl ${sideMeta.markerClassName}`}
                    >
                      <span className="text-lg" aria-hidden="true">
                        {sideMeta.emoji}
                      </span>
                    </div>

                    <div className="grid gap-3 xl:grid-cols-[180px_112px_minmax(0,1fr)_140px_120px_140px] xl:items-center">
                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500 dark:text-slate-400">
                          시간
                        </p>
                        <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                          {formatExecutedAt(trade.executed_at)}
                        </p>
                      </div>

                      <div>
                        <span
                          className={`inline-flex items-center rounded-full px-3 py-2 text-sm font-semibold ${sideMeta.chipClassName}`}
                        >
                          {`${sideMeta.emoji} ${sideMeta.label}`}
                        </span>
                      </div>

                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500 dark:text-slate-400">
                          종목명
                        </p>
                        <p className="mt-1 truncate text-sm font-semibold text-slate-950 dark:text-white">
                          {trade.symbol}
                        </p>
                      </div>

                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500 dark:text-slate-400">
                          체결가
                        </p>
                        <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {formatKrw(trade.price)}
                        </p>
                      </div>

                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold tracking-[0.18em] text-slate-500 dark:text-slate-400">
                          수량
                        </p>
                        <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {formatQty(trade.qty)}
                        </p>
                      </div>

                      <div>
                        <span className="inline-flex items-center rounded-full border border-slate-200/80 bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-700 dark:border-slate-700/80 dark:bg-slate-800 dark:text-slate-200">
                          {`AI 확신도 ${formatConfidence(trade.confidence)}`}
                        </span>
                      </div>
                    </div>
                  </article>
                )
              })}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default AiTradeTimeline
