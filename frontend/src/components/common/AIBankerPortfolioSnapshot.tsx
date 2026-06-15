import { Loader2, Menu, Wallet } from 'lucide-react'

import { usePortfolioSummary } from '../../hooks/usePortfolioSummary'
import type { AssetItem } from '../../services/portfolioService'

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
  const portfolioQuery = usePortfolioSummary()

  const portfolio = portfolioQuery.data ?? null
  const assets = portfolio?.items ?? []
  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const krwBalance = assets.find(isKrwAsset)?.total_value ?? 0
  const topHoldings = buildTopHoldings(assets)
  const isError = portfolioQuery.isError || Boolean(portfolio?.error)

  return (
    <section className="quantum-card rounded-xl px-5 py-4 text-[#dfe2eb]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#00dbe9]/10 text-[#7df4ff]">
            <Wallet className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#00dbe9]">
              Portfolio
            </p>
            <p className="truncate text-sm font-bold text-[#dfe2eb]">
              내 포트폴리오 요약
            </p>
          </div>
        </div>

        {onOpenSessions ? (
          <button
            type="button"
            onClick={onOpenSessions}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-[#3b494b] text-[#b9cacb] transition hover:border-[#00dbe9]/40 hover:bg-[#00dbe9]/10 hover:text-[#7df4ff] lg:hidden"
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
              className="h-[72px] min-w-[150px] flex-1 animate-pulse rounded-lg border border-[#3b494b]/30 bg-[#0a0e14]/70"
            />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-4 rounded-lg bg-[#eac324]/10 px-3 py-2 text-sm font-medium text-[#ffe179]">
          포트폴리오 요약을 불러오지 못했습니다. 채팅은 계속 사용할 수 있습니다.
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <div className="min-w-[150px] rounded-lg border border-[#3b494b]/30 bg-[#0a0e14]/70 px-4 py-3">
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#00dbe9]">
              총 자산
            </p>
            <p className="mt-1 font-mono text-sm font-bold text-[#dfe2eb]">{formatKrw(totalNetWorth)}</p>
          </div>

          <div className="min-w-[150px] rounded-lg border border-[#3b494b]/30 bg-[#0a0e14]/70 px-4 py-3">
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#00dbe9]">
              KRW 잔고
            </p>
            <p className="mt-1 font-mono text-sm font-bold text-[#dfe2eb]">{formatKrw(krwBalance)}</p>
          </div>

          <div className="min-w-[260px] flex-1 rounded-lg border border-[#3b494b]/30 bg-[#0a0e14]/70 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-[#00dbe9]">
                상위 보유 종목
              </p>
              {portfolioQuery.isFetching ? (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-[#b9cacb]">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  갱신 중
                </span>
              ) : null}
            </div>

            {topHoldings.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                {topHoldings.map((holding) => (
                  <div key={holding.symbol} className="min-w-[96px]">
                    <p className="text-sm font-bold text-[#dfe2eb]">{holding.symbol}</p>
                    <p className="text-xs text-[#b9cacb]">{formatKrw(holding.totalValue)}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-sm text-[#849495]">보유 종목 없음</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

export default AIBankerPortfolioSnapshot
