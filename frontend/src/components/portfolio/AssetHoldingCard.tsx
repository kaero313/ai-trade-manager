import { useState } from 'react'

interface AssetHoldingAiAnalysis {
  decision: string
  confidence: number
  reasoning: string
  created_at: string
}

interface AssetHoldingCardProps {
  currency: string
  balance: number
  avgBuyPrice: number
  currentPrice: number
  totalValue: number
  pnlPercentage: number
  aiAnalysis: AssetHoldingAiAnalysis | null
}

function formatKrw(value: number): string {
  const safeValue = Number.isFinite(value) ? Math.abs(value) : 0
  return `₩${new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: 0,
  }).format(Math.round(safeValue))}`
}

function formatBalance(value: number): string {
  const safeValue = Number.isFinite(value) ? Math.max(0, value) : 0
  return new Intl.NumberFormat('ko-KR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  }).format(safeValue)
}

function formatPnlPercentage(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  const prefix = safeValue > 0 ? '+' : ''
  return `${prefix}${safeValue.toFixed(2)}%`
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function translateDecision(decision: string): string {
  const normalized = decision.trim().toUpperCase()

  if (normalized === 'BUY') {
    return '매수'
  }
  if (normalized === 'SELL') {
    return '매도'
  }
  if (normalized === 'HOLD') {
    return '관망'
  }

  return decision.trim() || '미정'
}

function clampConfidence(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }

  return Math.max(0, Math.min(100, Math.round(value)))
}

function resolvePnlBadgeClassName(pnlPercentage: number): string {
  if (pnlPercentage > 0) {
    return 'border-emerald-200/70 bg-gradient-to-br from-emerald-500 via-emerald-400 to-teal-400 text-white shadow-[0_20px_42px_-28px_rgba(5,150,105,0.9)] dark:border-emerald-300/20 dark:from-emerald-500 dark:via-emerald-400 dark:to-teal-400'
  }
  if (pnlPercentage < 0) {
    return 'border-rose-200/70 bg-gradient-to-br from-rose-500 via-rose-400 to-red-400 text-white shadow-[0_20px_42px_-28px_rgba(225,29,72,0.9)] dark:border-rose-300/20 dark:from-rose-500 dark:via-rose-400 dark:to-red-400'
  }
  return 'border-slate-200/70 bg-gradient-to-br from-slate-200 via-slate-100 to-white text-slate-700 shadow-[0_20px_42px_-28px_rgba(100,116,139,0.55)] dark:border-slate-700/70 dark:from-slate-700 dark:via-slate-800 dark:to-slate-900 dark:text-slate-100'
}

function resolvePnlLabelClassName(pnlPercentage: number): string {
  if (pnlPercentage === 0) {
    return 'text-slate-500 dark:text-slate-300'
  }

  return 'text-white/80'
}

function resolveAiBadgeClassName(confidence: number): string {
  if (confidence >= 70) {
    return 'border border-emerald-200/80 bg-emerald-50 text-emerald-700 shadow-[0_16px_34px_-24px_rgba(5,150,105,0.75)] dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200'
  }
  if (confidence >= 50) {
    return 'border border-amber-200/80 bg-amber-50 text-amber-700 shadow-[0_16px_34px_-24px_rgba(217,119,6,0.7)] dark:border-amber-300/20 dark:bg-amber-500/15 dark:text-amber-200'
  }
  return 'border border-rose-200/80 bg-rose-50 text-rose-700 shadow-[0_16px_34px_-24px_rgba(225,29,72,0.7)] dark:border-rose-300/20 dark:bg-rose-500/15 dark:text-rose-200'
}

function HoldingMetric({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="rounded-2xl border border-white/60 bg-white/55 px-4 py-3 shadow-[0_16px_36px_-30px_rgba(15,23,42,0.7)] backdrop-blur transition-shadow duration-200 hover:shadow-[0_22px_50px_-28px_rgba(15,23,42,0.72)] dark:border-white/10 dark:bg-white/5 dark:shadow-[0_16px_36px_-30px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_22px_50px_-28px_rgba(2,6,23,0.98)]">
      <p className="text-[11px] font-semibold tracking-[0.2em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{value}</p>
    </div>
  )
}

function AssetHoldingCard({
  currency,
  balance,
  avgBuyPrice,
  currentPrice,
  totalValue,
  pnlPercentage,
  aiAnalysis,
}: AssetHoldingCardProps) {
  const [isTooltipHovered, setIsTooltipHovered] = useState(false)
  const [isTooltipPinned, setIsTooltipPinned] = useState(false)

  const safeConfidence = clampConfidence(aiAnalysis?.confidence ?? 0)
  const isTooltipVisible = Boolean(aiAnalysis) && (isTooltipHovered || isTooltipPinned)

  return (
    <section className="group relative overflow-visible rounded-[28px] border border-white/60 bg-white/70 p-5 shadow-[0_28px_80px_-38px_rgba(15,23,42,0.45)] backdrop-blur-xl transition-[box-shadow,transform] duration-200 hover:scale-[1.01] hover:shadow-[0_34px_96px_-40px_rgba(15,23,42,0.5)] dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_80px_-38px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_34px_96px_-40px_rgba(2,6,23,1)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.14),_transparent_36%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.12),_transparent_34%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.14),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.14),_transparent_32%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-5 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3 lg:hidden">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
                  보유 종목
                </p>
                <h3 className="mt-2 break-words text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
                  {currency}
                </h3>
              </div>
              <div
                className={`inline-flex shrink-0 rounded-[22px] border px-4 py-3 text-right ${resolvePnlBadgeClassName(pnlPercentage)}`}
              >
                <div>
                  <p className={`text-[11px] font-semibold tracking-[0.2em] ${resolvePnlLabelClassName(pnlPercentage)}`}>
                    수익률
                  </p>
                  <p className="mt-1 text-xl font-semibold">{formatPnlPercentage(pnlPercentage)}</p>
                </div>
              </div>
            </div>

            <div className="hidden lg:flex lg:items-start lg:justify-between lg:gap-6">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
                  보유 종목
                </p>
                <h3 className="mt-2 break-words text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
                  {currency}
                </h3>
              </div>

              <div
                className={`inline-flex shrink-0 rounded-[24px] border px-5 py-4 text-right ${resolvePnlBadgeClassName(pnlPercentage)}`}
              >
                <div>
                  <p className={`text-[11px] font-semibold tracking-[0.2em] ${resolvePnlLabelClassName(pnlPercentage)}`}>
                    수익률
                  </p>
                  <p className="mt-1 text-2xl font-semibold">{formatPnlPercentage(pnlPercentage)}</p>
                </div>
              </div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <HoldingMetric label="보유 수량" value={`${formatBalance(balance)} ${currency}`} />
              <HoldingMetric label="현재가" value={formatKrw(currentPrice)} />
              <HoldingMetric label="평단가" value={formatKrw(avgBuyPrice)} />
              <HoldingMetric label="평가금액" value={formatKrw(totalValue)} />
            </div>
          </div>
        </div>

        <div className="mt-5 flex items-start justify-between gap-4 border-t border-white/50 pt-4 dark:border-white/10">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.2em] text-slate-500 dark:text-slate-400">
              AI 신뢰도
            </p>
            <div
              className="relative mt-2 inline-flex"
              onMouseEnter={() => setIsTooltipHovered(true)}
              onMouseLeave={() => setIsTooltipHovered(false)}
            >
              {aiAnalysis ? (
                <>
                  <button
                    type="button"
                    onClick={() => setIsTooltipPinned((previous) => !previous)}
                    onFocus={() => setIsTooltipHovered(true)}
                    onBlur={() => {
                      setIsTooltipHovered(false)
                      setIsTooltipPinned(false)
                    }}
                    className={`inline-flex items-center rounded-full px-4 py-2 text-sm font-semibold transition-transform duration-200 hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-sky-400/60 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-slate-900 ${resolveAiBadgeClassName(safeConfidence)}`}
                  >
                    {`AI: ${translateDecision(aiAnalysis.decision)} [${safeConfidence}%]`}
                  </button>

                  {isTooltipVisible ? (
                    <div className="absolute bottom-[calc(100%+12px)] left-0 z-20 w-[min(320px,calc(100vw-64px))] rounded-2xl border border-white/70 bg-white/90 p-4 shadow-[0_28px_70px_-34px_rgba(15,23,42,0.55)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/95 dark:shadow-[0_28px_70px_-34px_rgba(2,6,23,0.95)]">
                      <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                        {aiAnalysis.reasoning}
                      </p>
                      <p className="mt-3 text-[11px] font-semibold tracking-[0.16em] text-slate-500 dark:text-slate-400">
                        최근 분석 {formatUpdatedAt(aiAnalysis.created_at)}
                      </p>
                    </div>
                  ) : null}
                </>
              ) : (
                <span className="inline-flex items-center rounded-full border border-slate-200/80 bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-500 dark:border-slate-700/80 dark:bg-slate-800 dark:text-slate-300">
                  AI 분석 없음
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default AssetHoldingCard
