import { Loader2 } from 'lucide-react'

import { useAIPerformance } from '../../hooks/useAIPerformance'
import {
  PORTFOLIO_BODY_TEXT_CLASS_NAME,
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
} from './portfolioStyles'

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
        'border border-rose-200/80 bg-white text-rose-600 ring-1 ring-rose-100 dark:border-rose-300/20 dark:bg-gray-900 dark:text-rose-200 dark:ring-rose-300/10',
    }
  }

  return {
    emoji: '🟢',
    label: '매수',
    chipClassName:
      'border border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200',
    markerClassName:
      'border border-emerald-200/80 bg-white text-emerald-600 ring-1 ring-emerald-100 dark:border-emerald-300/20 dark:bg-gray-900 dark:text-emerald-200 dark:ring-emerald-300/10',
  }
}

function TimelineLoadingState() {
  return (
    <div className="relative pl-14">
      <div className="absolute bottom-2 left-[23px] top-2 w-px bg-gray-200 dark:bg-gray-700" />

      <div className="space-y-4">
        {Array.from({ length: 3 }, (_, index) => (
          <div
            key={`ai-trade-timeline-skeleton-${index}`}
            className={`${PORTFOLIO_PANEL_CLASS_NAME} relative overflow-hidden p-5`}
          >
            <div className="absolute left-[-52px] top-6 inline-flex h-11 w-11 items-center justify-center rounded-xl border border-emerald-200/80 bg-white text-emerald-500 ring-1 ring-emerald-100 dark:border-emerald-300/20 dark:bg-gray-900 dark:text-emerald-200 dark:ring-emerald-300/10">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>

            <div className="animate-pulse">
              <div className="grid gap-3 xl:grid-cols-[180px_112px_minmax(0,1fr)_140px_120px_140px] xl:items-center">
                <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
                <div className="h-9 rounded-full bg-emerald-100/90 dark:bg-emerald-500/20" />
                <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
                <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
                <div className="h-4 rounded-full bg-gray-200 dark:bg-gray-700" />
                <div className="h-9 rounded-full bg-gray-200 dark:bg-gray-700" />
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
    <div className={`${PORTFOLIO_PANEL_CLASS_NAME} flex min-h-[260px] items-center justify-center px-6 text-center`}>
      <div>
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          아직 AI가 실행한 거래가 없습니다.
        </p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
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
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} h-full overflow-hidden p-6`}>
      <div>
        <header className="mb-5">
          <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
            AI TRADE FLOW
          </p>
          <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>
            🤖 AI 매매 결정 타임라인
          </h2>
          <p className={PORTFOLIO_BODY_TEXT_CLASS_NAME}>
            최근 AI 매매 실행 기록을 시간순으로 확인합니다.
          </p>
        </header>

        {showLoading ? <TimelineLoadingState /> : null}
        {!showLoading && trades.length === 0 ? <EmptyTimelineState /> : null}

        {!showLoading && trades.length > 0 ? (
          <div className="relative pl-14">
            <div className="absolute bottom-4 left-[23px] top-3 w-px bg-gray-200 dark:bg-gray-700" />

            <div className="space-y-4">
              {trades.map((trade, index) => {
                const sideMeta = resolveSideMeta(trade.side)

                return (
                  <article
                    key={`${trade.symbol}-${trade.side}-${trade.executed_at}-${index}`}
                    className="group relative overflow-hidden rounded-xl border border-gray-200 bg-gray-50 p-5 transition-shadow duration-200 hover:shadow-sm dark:border-gray-700 dark:bg-gray-900/60"
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
                        <p className="text-[11px] font-semibold tracking-[0.16em] text-gray-500 dark:text-gray-400">
                          시간
                        </p>
                        <p className="mt-1 text-sm font-medium text-gray-900 dark:text-gray-100">
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
                        <p className="text-[11px] font-semibold tracking-[0.16em] text-gray-500 dark:text-gray-400">
                          종목명
                        </p>
                        <p className="mt-1 truncate text-sm font-semibold text-gray-950 dark:text-white">
                          {trade.symbol}
                        </p>
                      </div>

                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold tracking-[0.16em] text-gray-500 dark:text-gray-400">
                          체결가
                        </p>
                        <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                          {formatKrw(trade.price)}
                        </p>
                      </div>

                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold tracking-[0.16em] text-gray-500 dark:text-gray-400">
                          수량
                        </p>
                        <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                          {formatQty(trade.qty)}
                        </p>
                      </div>

                      <div>
                        <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-100 px-3 py-2 text-sm font-semibold text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200">
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
