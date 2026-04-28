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
    return 'text-emerald-600 dark:text-emerald-300'
  }
  if (value < 0) {
    return 'text-rose-600 dark:text-rose-300'
  }
  return 'text-gray-700 dark:text-gray-200'
}

function resolveDecisionMeta(decision: AIAnalysisItem['decision']): DecisionMeta {
  if (decision === 'BUY') {
    return {
      label: '매수',
      className:
        'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200',
    }
  }
  if (decision === 'SELL') {
    return {
      label: '매도',
      className:
        'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/15 dark:text-rose-200',
    }
  }
  return {
    label: '관망',
    className:
      'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-300/20 dark:bg-amber-500/15 dark:text-amber-200',
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
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          보유 중인 코인이 없습니다.
        </p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
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
              <tr className="text-xs font-semibold text-gray-500 dark:text-gray-400">
                <th className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">종목</th>
                <th className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">평가금액</th>
                <th className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">수익률</th>
                <th className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">보유수량</th>
                <th className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">AI 판단</th>
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
                    className="text-sm text-gray-800 transition-colors hover:bg-gray-50 dark:text-gray-100 dark:hover:bg-gray-900/60"
                  >
                    <td className="border-b border-gray-100 px-4 py-4 font-semibold dark:border-gray-700/70">
                      {currency}
                    </td>
                    <td className="border-b border-gray-100 px-4 py-4 font-medium dark:border-gray-700/70">
                      {formatKrw(item.total_value)}
                    </td>
                    <td
                      className={`border-b border-gray-100 px-4 py-4 font-semibold dark:border-gray-700/70 ${resolvePnlClassName(
                        item.pnl_percentage,
                      )}`}
                    >
                      {formatSignedPercent(item.pnl_percentage)}
                    </td>
                    <td className="border-b border-gray-100 px-4 py-4 text-gray-600 dark:border-gray-700/70 dark:text-gray-300">
                      {formatQuantity(item.balance, currency)}
                    </td>
                    <td className="border-b border-gray-100 px-4 py-4 dark:border-gray-700/70">
                      {analysis && decisionMeta ? (
                        <span
                          className={`inline-flex items-center rounded-md border px-3 py-1.5 text-xs font-semibold ${decisionMeta.className}`}
                        >
                          {`${decisionMeta.label} · ${formatConfidence(analysis.confidence)}`}
                        </span>
                      ) : (
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
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
