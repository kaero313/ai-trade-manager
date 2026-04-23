import {
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_PANEL_INTERACTIVE_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
} from './portfolioStyles'

interface PortfolioSummaryCardProps {
  totalNetWorth: number
  totalPnl: number
  krwBalance: number
  coinCount: number
  isLoading: boolean
}

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(Math.abs(value)))}`
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

function formatCoinCount(value: number): string {
  return `${new Intl.NumberFormat('ko-KR').format(Math.max(0, Math.round(value)))}개`
}

function resolvePnlTone(totalPnl: number): string {
  if (totalPnl > 0) {
    return 'text-emerald-600 dark:text-emerald-300'
  }
  if (totalPnl < 0) {
    return 'text-rose-600 dark:text-rose-300'
  }
  return 'text-gray-900 dark:text-gray-100'
}

function SummaryMetric({
  label,
  value,
  valueClassName = 'text-gray-900 dark:text-gray-100',
}: {
  label: string
  value: string
  valueClassName?: string
}) {
  return (
    <div className={`${PORTFOLIO_PANEL_INTERACTIVE_CLASS_NAME} px-4 py-4 md:px-5`}>
      <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
        {label}
      </p>
      <p className={`mt-3 text-lg font-semibold ${valueClassName}`}>{value}</p>
    </div>
  )
}

function PortfolioSummaryCard({
  totalNetWorth,
  totalPnl,
  krwBalance,
  coinCount,
  isLoading,
}: PortfolioSummaryCardProps) {
  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} overflow-hidden p-6`}>
      <div>
        {isLoading ? (
          <div className="animate-pulse">
            <div className="h-3 w-24 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="mt-5 h-12 w-56 rounded-2xl bg-gray-200 dark:bg-gray-700" />

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-4 py-4`}>
                <div className="h-3 w-20 rounded-full bg-emerald-100 dark:bg-emerald-500/20" />
                <div className="mt-3 h-7 w-28 rounded-xl bg-emerald-100 dark:bg-emerald-500/20" />
              </div>
              <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-4 py-4`}>
                <div className="h-3 w-16 rounded-full bg-gray-200 dark:bg-gray-700" />
                <div className="mt-3 h-7 w-24 rounded-xl bg-gray-200 dark:bg-gray-700" />
              </div>
              <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-4 py-4`}>
                <div className="h-3 w-16 rounded-full bg-gray-200 dark:bg-gray-700" />
                <div className="mt-3 h-7 w-20 rounded-xl bg-gray-200 dark:bg-gray-700" />
              </div>
            </div>
          </div>
        ) : (
          <>
            <div>
              <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
                총 순자산
              </p>
              <p className="mt-4 text-4xl font-semibold tracking-tight text-gray-950 sm:text-5xl dark:text-white">
                {formatKrw(totalNetWorth)}
              </p>
            </div>

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <SummaryMetric
                label="총 평가손익"
                value={formatSignedKrw(totalPnl)}
                valueClassName={resolvePnlTone(totalPnl)}
              />
              <SummaryMetric label="KRW 잔고" value={formatKrw(krwBalance)} />
              <SummaryMetric label="보유 코인 수" value={formatCoinCount(coinCount)} />
            </div>
          </>
        )}
      </div>
    </section>
  )
}

export default PortfolioSummaryCard
