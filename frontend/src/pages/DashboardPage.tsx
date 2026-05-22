import { useQuery } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import AiActivityLiveFlow from '../components/trading/AiActivityLiveFlow'
import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import AiNewsBoard from '../components/trading/AiNewsBoard'
import AiPerformanceWidget from '../components/trading/AiPerformanceWidget'
import BotControlPanel from '../components/trading/BotControlPanel'
import ControlPanel from '../components/trading/ControlPanel'
import MarketChart from '../components/trading/MarketChart'
import PortfolioChart from '../components/trading/PortfolioChart'
import RecentOrders from '../components/trading/RecentOrders'
import WatchlistSidebar from '../components/trading/Watchlist'
import { usePortfolioSummary } from '../hooks/usePortfolioSummary'
import { fetchOrders } from '../services/portfolioService'
import type { AssetItem } from '../services/portfolioService'

function resolveTabClassName(isActive: boolean): string {
  return `quantum-tab ${isActive ? 'quantum-tab-active' : 'quantum-tab-inactive'}`
}

function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [macroTab, setMacroTab] = useState<'sentiment' | 'news'>('sentiment')
  const [rightPanelTab, setRightPanelTab] = useState<'portfolio' | 'performance'>('portfolio')
  const portfolioSummaryQuery = usePortfolioSummary()
  const ordersQuery = useQuery({
    queryKey: ['dashboard-orders'],
    queryFn: fetchOrders,
    refetchInterval: (query) => (query.state.status === 'error' ? 30000 : 15000),
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
    retry: 1,
  })

  const selectedSymbol = searchParams.get('symbol')
  const setSelectedSymbol = (symbol: string) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('symbol', symbol)
    setSearchParams(nextParams, { replace: true })
  }

  const portfolio = portfolioSummaryQuery.data ?? null
  const hasPortfolioRefreshError = portfolioSummaryQuery.isError || portfolioSummaryQuery.isRefetchError
  const portfolioErrorCode =
    hasPortfolioRefreshError && portfolio === null
      ? 'PORTFOLIO_FETCH_FAILED'
      : portfolio?.error ?? (hasPortfolioRefreshError ? 'PORTFOLIO_FETCH_FAILED' : null)
  const portfolioIsStale =
    Boolean(portfolio?.is_stale) || (hasPortfolioRefreshError && portfolio !== null)
  const orders = ordersQuery.data ?? []
  const ordersHasRefreshError = ordersQuery.isError || ordersQuery.isRefetchError
  const ordersUpdatedAt = ordersQuery.dataUpdatedAt > 0 ? ordersQuery.dataUpdatedAt : null
  const ordersErrorMessage =
    ordersHasRefreshError && orders.length === 0 ? '최근 체결 내역을 불러오지 못했습니다.' : null
  const assets: AssetItem[] = portfolio?.items ?? []

  return (
    <div className="dashboard-quantum min-h-full space-y-5">
      <AiActivityLiveFlow />

      <div className="grid min-h-0 gap-5 lg:grid-cols-12">
        <div className="flex min-w-0 flex-col gap-5 lg:col-span-3 lg:min-h-0">
          <div className="flex min-w-0 flex-col gap-3">
            <div className="inline-flex w-fit shrink-0 rounded-xl bg-[#0a0e14] p-1">
              <button
                type="button"
                onClick={() => setMacroTab('sentiment')}
                className={resolveTabClassName(macroTab === 'sentiment')}
              >
                시장 심리
              </button>
              <button
                type="button"
                onClick={() => setMacroTab('news')}
                className={resolveTabClassName(macroTab === 'news')}
              >
                RAG 뉴스
              </button>
            </div>

            <section className="quantum-card macro-panel-shell overflow-hidden rounded-xl">
              {macroTab === 'sentiment' ? (
                <div className="min-w-0">
                  <AiMarketSentiment />
                </div>
              ) : (
                <div className="flex max-h-[520px] min-h-0 flex-col overflow-hidden">
                  <AiNewsBoard />
                </div>
              )}
            </section>
          </div>
          <div className="min-h-[320px] overflow-hidden lg:min-h-0 [&>aside]:flex [&>aside]:h-full [&>aside]:min-h-0 [&>aside]:flex-1">
            <WatchlistSidebar selectedSymbol={selectedSymbol} onSelectSymbol={setSelectedSymbol} />
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-5 lg:col-span-6 lg:min-h-0">
          <div className="h-[420px] lg:h-[380px]">
            <MarketChart symbol={selectedSymbol} />
          </div>
          <div className="min-h-0">
            <AiInsightBriefing symbol={selectedSymbol} />
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-5 lg:col-span-3 lg:min-h-0">
          <div className="flex min-h-[250px] shrink-0 flex-col gap-3">
            <div className="inline-flex w-fit rounded-xl bg-[#0a0e14] p-1">
              <button
                type="button"
                onClick={() => setRightPanelTab('portfolio')}
                className={resolveTabClassName(rightPanelTab === 'portfolio')}
              >
                포트폴리오
              </button>
              <button
                type="button"
                onClick={() => setRightPanelTab('performance')}
                className={resolveTabClassName(rightPanelTab === 'performance')}
              >
                AI 성과
              </button>
            </div>
            <div className="min-h-[250px]">
              {rightPanelTab === 'portfolio' ? (
                <PortfolioChart
                  items={assets}
                  isLoading={portfolioSummaryQuery.isLoading}
                  source={portfolio?.source ?? null}
                  isStale={portfolioIsStale}
                  updatedAt={portfolio?.updated_at ?? null}
                  errorCode={portfolioErrorCode}
                  totalNetWorth={portfolio?.total_net_worth ?? 0}
                  totalPnl={portfolio?.total_pnl ?? 0}
                />
              ) : (
                <AiPerformanceWidget />
              )}
            </div>
          </div>
          <div className="min-h-[200px] pr-1 lg:min-h-0 lg:flex-1">
            <RecentOrders
              orders={orders}
              isLoading={ordersQuery.isLoading}
              errorMessage={ordersErrorMessage}
              isStale={ordersHasRefreshError && orders.length > 0}
              updatedAt={ordersUpdatedAt}
            />
          </div>
          <div className="flex flex-col gap-4">
            <ControlPanel />
            <BotControlPanel portfolioError={portfolioErrorCode} />
          </div>
        </div>
      </div>

      <Link
        to="/chat"
        aria-label="AI 뱅커 열기"
        title="AI 뱅커 열기"
        className="group fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full border border-[#7df4ff]/30 bg-[#00dbe9] text-[#00363a] transition-transform hover:scale-105 active:scale-95 sm:bottom-8 sm:right-8"
      >
        <span className="absolute inset-1 rounded-full bg-[#7df4ff]/20 opacity-0 transition-opacity group-hover:opacity-100" />
        <Sparkles className="relative h-6 w-6 text-[#00363a]" aria-hidden="true" />
        <span className="sr-only">AI 뱅커 열기</span>
      </Link>
    </div>
  )
}

export default DashboardPage
