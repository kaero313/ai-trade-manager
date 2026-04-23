import { useState } from 'react'
import {
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_INTERACTIVE_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TOOLTIP_CLASS_NAME,
} from './portfolioStyles'

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
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200'
  }
  if (pnlPercentage < 0) {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/15 dark:text-rose-200'
  }
  return 'border-gray-200 bg-gray-100 text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100'
}

function resolvePnlLabelClassName(pnlPercentage: number): string {
  if (pnlPercentage > 0) {
    return 'text-emerald-600 dark:text-emerald-200'
  }
  if (pnlPercentage < 0) {
    return 'text-rose-600 dark:text-rose-200'
  }
  return 'text-gray-500 dark:text-gray-300'
}

function resolveAiBadgeClassName(confidence: number): string {
  if (confidence >= 70) {
    return 'border border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200'
  }
  if (confidence >= 50) {
    return 'border border-amber-200/80 bg-amber-50 text-amber-700 dark:border-amber-300/20 dark:bg-amber-500/15 dark:text-amber-200'
  }
  return 'border border-rose-200/80 bg-rose-50 text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/15 dark:text-rose-200'
}

function HoldingMetric({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className={`${PORTFOLIO_PANEL_INTERACTIVE_CLASS_NAME} px-4 py-3`}>
      <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
        {label}
      </p>
      <p className="mt-2 text-sm font-semibold text-gray-900 dark:text-gray-100">{value}</p>
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
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} group overflow-visible p-5`}>
      <div>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3 lg:hidden">
              <div className="min-w-0">
                <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
                  보유 종목
                </p>
                <h3 className="mt-2 break-words text-2xl font-semibold tracking-tight text-gray-950 dark:text-white">
                  {currency}
                </h3>
              </div>
              <div
                className={`inline-flex shrink-0 rounded-xl border px-4 py-3 text-right ${resolvePnlBadgeClassName(pnlPercentage)}`}
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
                <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
                  보유 종목
                </p>
                <h3 className="mt-2 break-words text-2xl font-semibold tracking-tight text-gray-950 dark:text-white">
                  {currency}
                </h3>
              </div>

              <div
                className={`inline-flex shrink-0 rounded-xl border px-5 py-4 text-right ${resolvePnlBadgeClassName(pnlPercentage)}`}
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

        <div className="mt-5 flex items-start justify-between gap-4 border-t border-gray-200 pt-4 dark:border-gray-700">
          <div>
            <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
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
                    className={`inline-flex items-center rounded-full px-4 py-2 text-sm font-semibold transition-colors duration-200 hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-sky-400/60 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-slate-900 ${resolveAiBadgeClassName(safeConfidence)}`}
                  >
                    {`AI: ${translateDecision(aiAnalysis.decision)} [${safeConfidence}%]`}
                  </button>

                  {isTooltipVisible ? (
                    <div className={`absolute bottom-[calc(100%+12px)] left-0 z-20 w-[min(320px,calc(100vw-64px))] ${PORTFOLIO_TOOLTIP_CLASS_NAME} p-4`}>
                      <p className="text-sm leading-6 text-gray-700 dark:text-gray-200">
                        {aiAnalysis.reasoning}
                      </p>
                      <p className="mt-3 text-[11px] font-semibold tracking-[0.14em] text-gray-500 dark:text-gray-400">
                        최근 분석 {formatUpdatedAt(aiAnalysis.created_at)}
                      </p>
                    </div>
                  ) : null}
                </>
              ) : (
                <span className="inline-flex items-center rounded-full border border-gray-200 bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
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
