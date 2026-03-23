import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import AiNewsBoard from '../components/trading/AiNewsBoard'
import BotControlPanel from '../components/trading/BotControlPanel'
import ControlPanel from '../components/trading/ControlPanel'
import MarketChart from '../components/trading/MarketChart'
import MarketSearchBar from '../components/trading/MarketSearchBar'
import PortfolioChart from '../components/trading/PortfolioChart'
import RecentOrders from '../components/trading/RecentOrders'
import WatchlistSidebar from '../components/trading/Watchlist'
import { fetchOrders, getPortfolioSummary } from '../services/portfolioService'
import type { AssetItem, OrderHistoryItem, PortfolioSummary } from '../services/portfolioService'

function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [macroTab, setMacroTab] = useState<'sentiment' | 'news'>('sentiment')
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [portfolioErrorCode, setPortfolioErrorCode] = useState<string | null>(null)
  const [orders, setOrders] = useState<OrderHistoryItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isOrdersLoading, setIsOrdersLoading] = useState(true)
  const [, setErrorMessage] = useState<string | null>(null)
  const [ordersErrorMessage, setOrdersErrorMessage] = useState<string | null>(null)

  const selectedSymbol = searchParams.get('symbol')
  const setSelectedSymbol = (symbol: string) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('symbol', symbol)
    setSearchParams(nextParams, { replace: true })
  }

  useEffect(() => {
    let isMounted = true
    let isPolling = false
    let pollingIntervalId: number | undefined

    const loadDashboardInitial = async () => {
      setIsLoading(true)
      setIsOrdersLoading(true)
      setErrorMessage(null)
      setOrdersErrorMessage(null)

      const [portfolioResult, ordersResult] = await Promise.allSettled([
        getPortfolioSummary(),
        fetchOrders(),
      ])

      if (!isMounted) {
        return
      }

      if (portfolioResult.status === 'fulfilled') {
        setPortfolio(portfolioResult.value)
        setPortfolioErrorCode(portfolioResult.value.error ?? null)
      }
      if (ordersResult.status === 'fulfilled') {
        setOrders(ordersResult.value)
      }

      if (portfolioResult.status === 'rejected') {
        setPortfolioErrorCode('PORTFOLIO_FETCH_FAILED')
        setErrorMessage('대시보드 데이터를 불러오지 못했습니다.')
      }

      if (ordersResult.status === 'rejected') {
        setOrdersErrorMessage('최근 체결 내역을 불러오지 못했습니다.')
      }

      setIsLoading(false)
      setIsOrdersLoading(false)
    }

    const refreshDashboardSilent = async () => {
      if (isPolling) {
        return
      }

      isPolling = true
      try {
        const [portfolioResult, ordersResult] = await Promise.allSettled([
          getPortfolioSummary(),
          fetchOrders(),
        ])

        if (!isMounted) {
          return
        }

        if (portfolioResult.status === 'fulfilled') {
          setPortfolio(portfolioResult.value)
          setPortfolioErrorCode(portfolioResult.value.error ?? null)
        } else {
          setPortfolioErrorCode('PORTFOLIO_FETCH_FAILED')
          console.warn('[Dashboard polling] portfolio refresh failed', portfolioResult.reason)
        }

        if (ordersResult.status === 'fulfilled') {
          setOrders(ordersResult.value)
        } else {
          console.warn('[Dashboard polling] orders refresh failed', ordersResult.reason)
        }
      } finally {
        isPolling = false
      }
    }

    const bootstrap = async () => {
      await loadDashboardInitial()
      if (!isMounted) {
        return
      }

      pollingIntervalId = window.setInterval(() => {
        void refreshDashboardSilent()
      }, 10000)
    }

    void bootstrap()

    return () => {
      isMounted = false
      if (pollingIntervalId !== undefined) {
        window.clearInterval(pollingIntervalId)
      }
    }
  }, [])

  const assets: AssetItem[] = portfolio?.items ?? []

  return (
    <div className="grid h-full min-h-0 gap-6 lg:grid-cols-12 lg:overflow-hidden">
      <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
        <div className="flex shrink-0 flex-col gap-3">
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

          <div className="flex h-[340px] min-h-[320px] max-h-[340px] flex-col overflow-hidden">
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
        <div className="min-h-[320px] overflow-hidden lg:min-h-0 lg:flex-1 [&>aside]:flex [&>aside]:h-full [&>aside]:min-h-0 [&>aside]:flex-1">
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
        <div className="min-h-[250px] shrink-0">
          <PortfolioChart items={assets} isLoading={isLoading} />
        </div>
        <div className="min-h-[200px] pr-1 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <RecentOrders orders={orders} isLoading={isOrdersLoading} errorMessage={ordersErrorMessage} />
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
