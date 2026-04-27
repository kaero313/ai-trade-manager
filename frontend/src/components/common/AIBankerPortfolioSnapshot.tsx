import { useQuery } from '@tanstack/react-query'
import { Loader2, Menu, Wallet } from 'lucide-react'

import { getPortfolioSummary, type AssetItem } from '../../services/portfolioService'

const PORTFOLIO_SNAPSHOT_QUERY_KEY = ['portfolio-summary', 'ai-banker-top-bar'] as const

interface TopHoldingItem {
  symbol: string
  totalValue: number
}

interface AIBankerPortfolioSnapshotProps {
  onOpenSessions?: () => void
}

function formatKrw(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(Math.max(0, Math.round(value)))
}

function isKrwAsset(item: AssetItem): boolean {
  return String(item.currency || '').trim().toUpperCase() === 'KRW'
}

function getAssetSymbol(item: AssetItem): string {
  return String(item.currency || '').trim().toUpperCase() || '-'
}

function buildTopHoldings(items: AssetItem[]): TopHoldingItem[] {
  return items
    .filter((item) => !isKrwAsset(item))
    .sort((left, right) => right.total_value - left.total_value)
    .slice(0, 3)
    .map((item) => ({
      symbol: getAssetSymbol(item),
      totalValue: item.total_value,
    }))
}

function AIBankerPortfolioSnapshot({ onOpenSessions }: AIBankerPortfolioSnapshotProps) {
  const portfolioQuery = useQuery({
    queryKey: PORTFOLIO_SNAPSHOT_QUERY_KEY,
    queryFn: getPortfolioSummary,
  })

  const portfolio = portfolioQuery.data ?? null
  const assets = portfolio?.items ?? []
  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const krwBalance = assets.find(isKrwAsset)?.total_value ?? 0
  const topHoldings = buildTopHoldings(assets)
  const isError = portfolioQuery.isError || Boolean(portfolio?.error)

  return (
    <section className="rounded-2xl bg-white px-5 py-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-200">
            <Wallet className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-gray-500 dark:text-gray-400">
              Portfolio
            </p>
            <p className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
              내 포트폴리오 요약
            </p>
          </div>
        </div>

        {onOpenSessions ? (
          <button
            type="button"
            onClick={onOpenSessions}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-gray-200 text-gray-700 transition hover:bg-gray-100 hover:text-gray-900 lg:hidden dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-700 dark:hover:text-white"
            aria-label="세션 목록 열기"
          >
            <Menu className="h-5 w-5" />
          </button>
        ) : null}
      </div>

      {portfolioQuery.isLoading ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="h-[72px] min-w-[150px] flex-1 animate-pulse rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/40"
            />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100">
          포트폴리오 요약을 불러오지 못했습니다. 채팅은 계속 사용할 수 있습니다.
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <div className="min-w-[150px] rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              총 자산
            </p>
            <p className="mt-1 text-sm font-semibold text-gray-950 dark:text-white">{formatKrw(totalNetWorth)}</p>
          </div>

          <div className="min-w-[150px] rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-900/40">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              KRW 잔고
            </p>
            <p className="mt-1 text-sm font-semibold text-gray-950 dark:text-white">{formatKrw(krwBalance)}</p>
          </div>

          <div className="min-w-[260px] flex-1 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-900/40">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                상위 보유 종목
              </p>
              {portfolioQuery.isFetching ? (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  갱신 중
                </span>
              ) : null}
            </div>

            {topHoldings.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                {topHoldings.map((holding) => (
                  <div key={holding.symbol} className="min-w-[96px]">
                    <p className="text-sm font-semibold text-gray-950 dark:text-white">{holding.symbol}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{formatKrw(holding.totalValue)}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">보유 종목 없음</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

export default AIBankerPortfolioSnapshot
