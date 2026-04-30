import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import AiNewsBoard from '../components/trading/AiNewsBoard'
import AiPerformanceWidget from '../components/trading/AiPerformanceWidget'
import BotControlPanel from '../components/trading/BotControlPanel'
import ControlPanel from '../components/trading/ControlPanel'
import MarketChart from '../components/trading/MarketChart'
import MarketSearchBar from '../components/trading/MarketSearchBar'
import PortfolioChart from '../components/trading/PortfolioChart'
import RecentOrders from '../components/trading/RecentOrders'
import WatchlistSidebar from '../components/trading/Watchlist'
import { usePortfolioSummary } from '../hooks/usePortfolioSummary'
import { fetchOrders } from '../services/portfolioService'
import type { AssetItem } from '../services/portfolioService'

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
  const portfolioErrorCode =
    portfolioSummaryQuery.isError && portfolio === null
      ? 'PORTFOLIO_FETCH_FAILED'
      : portfolio?.error ?? null
  const orders = ordersQuery.data ?? []
  const ordersErrorMessage =
    ordersQuery.isError && orders.length === 0 ? '최근 체결 내역을 불러오지 못했습니다.' : null
  const assets: AssetItem[] = portfolio?.items ?? []

  return (
    <div className="grid h-full min-h-0 gap-6 lg:grid-cols-12 lg:overflow-hidden">
      <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
        <div className="flex flex-col gap-3 lg:min-h-0 lg:flex-[5]">
          <div className="inline-flex rounded-xl bg-white p-1 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <button
              type="button"
              onClick={() => setMacroTab('sentiment')}
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                macroTab === 'sentiment'
                  ? 'bg-emerald-500 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
              }`}
            >
              시장 심리(Sentiment)
            </button>
            <button
              type="button"
              onClick={() => setMacroTab('news')}
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                macroTab === 'news'
                  ? 'bg-emerald-500 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
              }`}
            >
              글로벌 시황 뉴스(News)
            </button>
          </div>

          <div className="flex min-h-[460px] flex-1 flex-col overflow-hidden lg:min-h-0">
            {macroTab === 'sentiment' ? (
              <div className="flex h-full min-h-0 flex-1 flex-col overflow-y-auto pr-1">
                <AiMarketSentiment />
              </div>
            ) : (
              <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
                <AiNewsBoard />
              </div>
            )}
          </div>
        </div>
        <div className="min-h-[320px] overflow-hidden lg:min-h-0 lg:flex-[4] [&>aside]:flex [&>aside]:h-full [&>aside]:min-h-0 [&>aside]:flex-1">
          <WatchlistSidebar selectedSymbol={selectedSymbol} onSelectSymbol={setSelectedSymbol} />
        </div>
      </div>

      <div className="flex flex-col gap-6 lg:col-span-6 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
        <MarketSearchBar onSelectSymbol={setSelectedSymbol} />
        <div className="min-h-0 flex-1">
          <MarketChart symbol={selectedSymbol} />
        </div>
        <div className="min-h-0">
          <AiInsightBriefing symbol={selectedSymbol} />
        </div>
      </div>

      <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
        <div className="flex flex-col gap-4">
          <ControlPanel />
          <BotControlPanel portfolioError={portfolioErrorCode} />
        </div>
        <div className="flex min-h-[250px] shrink-0 flex-col gap-3">
          <div className="inline-flex rounded-xl bg-white p-1 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <button
              type="button"
              onClick={() => setRightPanelTab('portfolio')}
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                rightPanelTab === 'portfolio'
                  ? 'bg-emerald-500 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
              }`}
            >
              📊 포트폴리오
            </button>
            <button
              type="button"
              onClick={() => setRightPanelTab('performance')}
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                rightPanelTab === 'performance'
                  ? 'bg-emerald-500 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
              }`}
            >
              📈 AI 성과
            </button>
          </div>
          <div className="min-h-[250px]">
            {rightPanelTab === 'portfolio' ? (
              <PortfolioChart items={assets} isLoading={portfolioSummaryQuery.isLoading} />
            ) : (
              <AiPerformanceWidget />
            )}
          </div>
        </div>
        <div className="min-h-[200px] pr-1 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <RecentOrders
            orders={orders}
            isLoading={ordersQuery.isLoading}
            errorMessage={ordersErrorMessage}
          />
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
