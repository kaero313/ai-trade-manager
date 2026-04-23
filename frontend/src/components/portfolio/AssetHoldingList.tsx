import AssetHoldingCard from './AssetHoldingCard'

import type { AIAnalysisItem, AssetItem } from '../../services/portfolioService'
import {
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
} from './portfolioStyles'

interface AssetHoldingListProps {
  items: AssetItem[]
  aiAnalysisMap: Record<string, AIAnalysisItem | null>
  isLoading: boolean
}

function HoldingSkeletonCard() {
  return (
    <div className={`${PORTFOLIO_CARD_CLASS_NAME} overflow-hidden p-5`}>
      <div className="animate-pulse">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="h-3 w-20 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="mt-3 h-8 w-24 rounded-2xl bg-gray-200 dark:bg-gray-700" />
          </div>
          <div className="h-16 w-24 rounded-xl bg-gray-200 dark:bg-gray-700" />
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className={`${PORTFOLIO_PANEL_CLASS_NAME} h-20`} />
          <div className={`${PORTFOLIO_PANEL_CLASS_NAME} h-20`} />
          <div className={`${PORTFOLIO_PANEL_CLASS_NAME} h-20`} />
          <div className={`${PORTFOLIO_PANEL_CLASS_NAME} h-20`} />
        </div>

        <div className="mt-5 border-t border-gray-200 pt-4 dark:border-gray-700">
          <div className="h-3 w-24 rounded-full bg-gray-200 dark:bg-gray-700" />
          <div className="mt-3 h-10 w-40 rounded-full bg-gray-200 dark:bg-gray-700" />
        </div>
      </div>
    </div>
  )
}

function EmptyHoldingState() {
  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} px-6 py-10 text-center`}>
      <div>
        <span className="inline-flex items-center rounded-full border border-sky-200/80 bg-sky-50 px-3 py-1 text-xs font-semibold tracking-[0.2em] text-sky-700 dark:border-sky-300/20 dark:bg-sky-500/15 dark:text-sky-200">
          PORTFOLIO
        </span>
        <h3 className="mt-4 text-xl font-semibold text-gray-950 dark:text-white">
          보유 중인 코인이 없습니다
        </h3>
        <p className="mt-3 text-sm leading-6 text-gray-600 dark:text-gray-300">
          현재 포트폴리오에는 KRW 외 코인 자산이 없습니다. 자산이 생기면 이 영역에 종목별
          카드와 AI 신뢰도 배지가 표시됩니다.
        </p>
      </div>
    </section>
  )
}

function AssetHoldingList({
  items,
  aiAnalysisMap,
  isLoading,
}: AssetHoldingListProps) {
  const coinItems = items.filter((item) => item.currency.trim().toUpperCase() !== 'KRW')

  if (isLoading) {
    return (
      <div className="grid gap-4">
        {Array.from({ length: 3 }, (_, index) => (
          <HoldingSkeletonCard key={`holding-skeleton-${index}`} />
        ))}
      </div>
    )
  }

  if (coinItems.length === 0) {
    return <EmptyHoldingState />
  }

  return (
    <div className="grid gap-4">
      {coinItems.map((item) => (
        <AssetHoldingCard
          key={item.currency}
          currency={item.currency}
          balance={item.balance}
          avgBuyPrice={item.avg_buy_price}
          currentPrice={item.current_price}
          totalValue={item.total_value}
          pnlPercentage={item.pnl_percentage}
          aiAnalysis={aiAnalysisMap[`KRW-${item.currency}`] ?? null}
        />
      ))}
    </div>
  )
}

export default AssetHoldingList
