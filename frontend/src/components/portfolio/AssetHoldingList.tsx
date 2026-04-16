import AssetHoldingCard from './AssetHoldingCard'

import type { AIAnalysisItem, AssetItem } from '../../services/portfolioService'

interface AssetHoldingListProps {
  items: AssetItem[]
  aiAnalysisMap: Record<string, AIAnalysisItem | null>
  isLoading: boolean
}

function HoldingSkeletonCard() {
  return (
    <div className="relative overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-5 shadow-[0_28px_80px_-38px_rgba(15,23,42,0.45)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_80px_-38px_rgba(2,6,23,0.95)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.12),_transparent_36%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.1),_transparent_34%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.14),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.14),_transparent_32%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="relative animate-pulse">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="h-3 w-20 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
            <div className="mt-3 h-8 w-24 rounded-2xl bg-slate-200/90 dark:bg-slate-700/80" />
          </div>
          <div className="h-16 w-24 rounded-[24px] bg-slate-200/90 dark:bg-slate-700/80" />
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="h-20 rounded-2xl border border-white/50 bg-white/45 dark:border-white/10 dark:bg-white/5" />
          <div className="h-20 rounded-2xl border border-white/50 bg-white/45 dark:border-white/10 dark:bg-white/5" />
          <div className="h-20 rounded-2xl border border-white/50 bg-white/45 dark:border-white/10 dark:bg-white/5" />
          <div className="h-20 rounded-2xl border border-white/50 bg-white/45 dark:border-white/10 dark:bg-white/5" />
        </div>

        <div className="mt-5 border-t border-white/50 pt-4 dark:border-white/10">
          <div className="h-3 w-24 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
          <div className="mt-3 h-10 w-40 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
        </div>
      </div>
    </div>
  )
}

function EmptyHoldingState() {
  return (
    <section className="relative overflow-hidden rounded-[28px] border border-white/60 bg-white/70 px-6 py-10 text-center shadow-[0_28px_80px_-38px_rgba(15,23,42,0.42)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_80px_-38px_rgba(2,6,23,0.95)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(125,211,252,0.16),_transparent_36%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.1),_transparent_34%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.14),_transparent_32%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="relative">
        <span className="inline-flex items-center rounded-full border border-sky-200/80 bg-sky-50 px-3 py-1 text-xs font-semibold tracking-[0.2em] text-sky-700 dark:border-sky-300/20 dark:bg-sky-500/15 dark:text-sky-200">
          PORTFOLIO
        </span>
        <h3 className="mt-4 text-xl font-semibold text-slate-950 dark:text-white">
          보유 중인 코인이 없습니다
        </h3>
        <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
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
