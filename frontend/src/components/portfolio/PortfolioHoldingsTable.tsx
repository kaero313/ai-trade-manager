import type { AIAnalysisItem, AssetItem } from '../../services/portfolioService'
import {
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
} from './portfolioStyles'

interface PortfolioHoldingsTableProps {
  items: AssetItem[]
  aiAnalysisMap: Record<string, AIAnalysisItem | null>
  isLoading: boolean
}

type DecisionMeta = {
  label: string
  className: string
}

function formatKrw(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(Math.abs(safeValue)))}`
}

function formatSignedPercent(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  const sign = safeValue > 0 ? '+' : ''
  return `${sign}${safeValue.toFixed(2)}%`
}

function formatQuantity(value: number, currency: string): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `${new Intl.NumberFormat('ko-KR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  }).format(safeValue)} ${currency}`
}

function formatConfidence(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `${Math.round(safeValue)}%`
}

function resolvePnlClassName(value: number): string {
  if (value > 0) {
    return 'text-[#7df4ff]'
  }
  if (value < 0) {
    return 'text-[#ffb4ab]'
  }
  return 'text-[#b9cacb]'
}

function resolveDecisionMeta(decision: AIAnalysisItem['decision']): DecisionMeta {
  if (decision === 'BUY') {
    return {
      label: '매수',
      className: 'border-[#00dbe9]/30 bg-[#00dbe9]/10 text-[#7df4ff]',
    }
  }
  if (decision === 'SELL') {
    return {
      label: '매도',
      className: 'border-[#ffb4ab]/30 bg-[#ffb4ab]/10 text-[#ffb4ab]',
    }
  }
  return {
    label: '관망',
    className: 'border-[#eac324]/30 bg-[#eac324]/10 text-[#ffe179]',
  }
}

function LoadingState() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }, (_, index) => (
        <div
          key={`portfolio-holding-table-skeleton-${index}`}
          className={`${PORTFOLIO_PANEL_CLASS_NAME} h-14 animate-pulse`}
        />
      ))}
    </div>
  )
}

function EmptyState() {
  return (
    <div className={`${PORTFOLIO_PANEL_CLASS_NAME} flex min-h-[220px] items-center justify-center px-6 text-center`}>
      <div>
        <p className="text-sm font-semibold text-[#dfe2eb]">
          보유 중인 코인이 없습니다.
        </p>
        <p className="mt-2 text-sm text-[#b9cacb]">
          KRW 외 보유 자산이 생기면 종목별 수익이 여기에 표시됩니다.
        </p>
      </div>
    </div>
  )
}

function PortfolioHoldingsTable({
  items,
  aiAnalysisMap,
  isLoading,
}: PortfolioHoldingsTableProps) {
  const coinItems = items
    .filter((item) => item.currency.trim().toUpperCase() !== 'KRW')
    .sort((a, b) => b.total_value - a.total_value)

  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} overflow-hidden p-6`}>
      <header className="mb-5">
        <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>종목별 수익</p>
        <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>보유 종목</h2>
      </header>

      {isLoading ? <LoadingState /> : null}
      {!isLoading && coinItems.length === 0 ? <EmptyState /> : null}

      {!isLoading && coinItems.length > 0 ? (
        <div className="-mx-2 overflow-x-auto px-2">
          <table className="min-w-[720px] w-full border-separate border-spacing-0 text-left">
            <thead>
              <tr className="text-xs font-semibold text-[#849495]">
                <th className="border-b border-[#3b494b]/40 px-4 py-3">종목</th>
                <th className="border-b border-[#3b494b]/40 px-4 py-3">평가금액</th>
                <th className="border-b border-[#3b494b]/40 px-4 py-3">수익률</th>
                <th className="border-b border-[#3b494b]/40 px-4 py-3">보유수량</th>
                <th className="border-b border-[#3b494b]/40 px-4 py-3">AI 판단</th>
              </tr>
            </thead>
            <tbody>
              {coinItems.map((item) => {
                const currency = item.currency.trim().toUpperCase()
                const analysis = aiAnalysisMap[`KRW-${currency}`] ?? null
                const decisionMeta = analysis ? resolveDecisionMeta(analysis.decision) : null

                return (
                  <tr
                    key={currency}
                    className="text-sm text-[#dfe2eb] transition-colors hover:bg-[#00dbe9]/5"
                  >
                    <td className="border-b border-[#3b494b]/25 px-4 py-4 font-semibold">
                      {currency}
                    </td>
                    <td className="border-b border-[#3b494b]/25 px-4 py-4 font-medium">
                      {formatKrw(item.total_value)}
                    </td>
                    <td
                      className={`border-b border-[#3b494b]/25 px-4 py-4 font-semibold ${resolvePnlClassName(
                        item.pnl_percentage,
                      )}`}
                    >
                      {formatSignedPercent(item.pnl_percentage)}
                    </td>
                    <td className="border-b border-[#3b494b]/25 px-4 py-4 text-[#b9cacb]">
                      {formatQuantity(item.balance, currency)}
                    </td>
                    <td className="border-b border-[#3b494b]/25 px-4 py-4">
                      {analysis && decisionMeta ? (
                        <span
                          className={`inline-flex items-center rounded-md border px-3 py-1.5 text-xs font-semibold ${decisionMeta.className}`}
                        >
                          {`${decisionMeta.label} · ${formatConfidence(analysis.confidence)}`}
                        </span>
                      ) : (
                        <span className="text-xs font-medium text-[#849495]">
                          분석 없음
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  )
}

export default PortfolioHoldingsTable
