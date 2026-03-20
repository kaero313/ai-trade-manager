import { useEffect, useState } from 'react'

import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import BotControlPanel from '../components/trading/BotControlPanel'
import MarketChart from '../components/trading/MarketChart'
import MarketSearchBar from '../components/trading/MarketSearchBar'
import PortfolioChart from '../components/trading/PortfolioChart'
import RecentOrders from '../components/trading/RecentOrders'
import WatchlistSidebar from '../components/trading/Watchlist'
import { fetchOrders, getPortfolioSummary } from '../services/portfolioService'
import type { AssetItem, OrderHistoryItem, PortfolioSummary } from '../services/portfolioService'

function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [orders, setOrders] = useState<OrderHistoryItem[]>([])
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isOrdersLoading, setIsOrdersLoading] = useState(true)
  const [, setErrorMessage] = useState<string | null>(null)
  const [ordersErrorMessage, setOrdersErrorMessage] = useState<string | null>(null)

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
      }
      if (ordersResult.status === 'fulfilled') {
        setOrders(ordersResult.value)
      }

      if (portfolioResult.status === 'rejected') {
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
        } else {
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
        <AiMarketSentiment />
        <div className="min-h-[320px] lg:min-h-0 lg:flex-1 [&>aside]:h-full">
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
        <BotControlPanel />
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
