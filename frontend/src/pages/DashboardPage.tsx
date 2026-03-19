import { useEffect, useState } from 'react'

import AiCoreStatus from '../components/trading/AiCoreStatus'
import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import BotControlPanel from '../components/trading/BotControlPanel'
import MarketChart from '../components/trading/MarketChart'
import MarketSearchBar from '../components/trading/MarketSearchBar'
import RecentOrders from '../components/trading/RecentOrders'
import WatchlistSidebar from '../components/trading/Watchlist'
import { fetchOrders, getPortfolioSummary } from '../services/portfolioService'
import type { OrderHistoryItem, PortfolioSummary } from '../services/portfolioService'

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

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

  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const totalPnl = portfolio?.total_pnl ?? 0
  const pnlTextColor = totalPnl >= 0 ? 'text-emerald-600' : 'text-rose-600'

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <header className="flex shrink-0 items-center justify-between rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <div className="flex items-center gap-4">
          <AiCoreStatus />
        </div>
        <div className="flex items-center gap-6 text-sm font-semibold">
          <div className="flex flex-col items-end">
            <span className="text-xs text-gray-500 dark:text-gray-400">총 자산</span>
            <span className="text-gray-900 dark:text-gray-100">{isLoading ? '...' : formatKrw(totalNetWorth)}</span>
          </div>
          <div className="flex flex-col items-end">
            <span className="text-xs text-gray-500 dark:text-gray-400">총 손익</span>
            <span className={pnlTextColor}>{isLoading ? '...' : formatSignedKrw(totalPnl)}</span>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-12 lg:overflow-hidden">
        <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
          <AiMarketSentiment />
          <div className="min-h-[320px] lg:min-h-0 lg:flex-1 [&>aside]:h-full">
            <WatchlistSidebar selectedSymbol={selectedSymbol} onSelectSymbol={setSelectedSymbol} />
          </div>
        </div>

        <div className="flex flex-col gap-6 lg:col-span-6 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
          <MarketSearchBar onSelectSymbol={setSelectedSymbol} />
          <div className="min-h-[400px] shrink-0 lg:min-h-0 lg:flex-1">
            <MarketChart symbol={selectedSymbol} />
          </div>
          <div className="shrink-0">
            <AiInsightBriefing symbol={selectedSymbol} />
          </div>
        </div>

        <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-2">
          <BotControlPanel />
          <div className="min-h-[300px] pr-1 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            <RecentOrders orders={orders} isLoading={isOrdersLoading} errorMessage={ordersErrorMessage} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
