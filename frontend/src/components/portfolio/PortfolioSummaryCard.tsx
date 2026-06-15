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
    return 'text-[#7df4ff]'
  }
  if (totalPnl < 0) {
    return 'text-[#ffb4ab]'
  }
  return 'text-[#dfe2eb]'
}

function SummaryMetric({
  label,
  value,
  valueClassName = 'text-[#dfe2eb]',
}: {
  label: string
  value: string
  valueClassName?: string
}) {
  return (
    <div className={`${PORTFOLIO_PANEL_INTERACTIVE_CLASS_NAME} px-4 py-4`}>
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
            <div className="h-3 w-24 rounded-full bg-[#262a31]" />
            <div className="mt-5 h-12 w-56 rounded-lg bg-[#262a31]" />

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-4 py-4`}>
                <div className="h-3 w-20 rounded-full bg-[#00dbe9]/15" />
                <div className="mt-3 h-7 w-28 rounded-lg bg-[#00dbe9]/15" />
              </div>
              <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-4 py-4`}>
                <div className="h-3 w-16 rounded-full bg-[#262a31]" />
                <div className="mt-3 h-7 w-24 rounded-lg bg-[#262a31]" />
              </div>
              <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-4 py-4`}>
                <div className="h-3 w-16 rounded-full bg-[#262a31]" />
                <div className="mt-3 h-7 w-20 rounded-lg bg-[#262a31]" />
              </div>
            </div>
          </div>
        ) : (
          <>
            <div>
              <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
                총 자산
              </p>
              <p className="mt-4 break-words font-mono text-4xl font-bold text-[#dfe2eb] sm:text-5xl">
                {formatKrw(totalNetWorth)}
              </p>
            </div>

            <div className="mt-8 grid gap-3">
              <SummaryMetric
                label="총 손익"
                value={formatSignedKrw(totalPnl)}
                valueClassName={resolvePnlTone(totalPnl)}
              />
              <SummaryMetric label="현금 잔고" value={formatKrw(krwBalance)} />
              <SummaryMetric label="보유 종목" value={formatCoinCount(coinCount)} />
            </div>
          </>
        )}
      </div>
    </section>
  )
}

export default PortfolioSummaryCard
