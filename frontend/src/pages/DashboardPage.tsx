import { useEffect, useState } from 'react'

import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import AiCoreStatus from '../components/trading/AiCoreStatus'
import BotControlPanel from '../components/trading/BotControlPanel'
import ControlPanel from '../components/trading/ControlPanel'
import MarketChart from '../components/trading/MarketChart'
import MarketSearchBar from '../components/trading/MarketSearchBar'
import PortfolioChart from '../components/trading/PortfolioChart'
import RecentOrders from '../components/trading/RecentOrders'
import SentimentWidget from '../components/trading/SentimentWidget'
import Watchlist from '../components/trading/Watchlist'
import { fetchOrders, getPortfolioSummary } from '../services/portfolioService'
import type { AssetItem, OrderHistoryItem, PortfolioSummary } from '../services/portfolioService'

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

function formatPercent(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '' : ''
  return `${sign}${value.toFixed(2)}%`
}

function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [orders, setOrders] = useState<OrderHistoryItem[]>([])
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isOrdersLoading, setIsOrdersLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
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
  const assets: AssetItem[] = portfolio?.items ?? []
  const pnlTextColor = totalPnl >= 0 ? 'text-emerald-600' : 'text-rose-600'

  return (
    <div className="grid h-full min-h-0 gap-6 lg:grid-cols-10 lg:overflow-hidden">
      <div className="flex flex-col gap-6 lg:col-span-7 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-2">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.95fr)]">
          <AiInsightBriefing symbol={selectedSymbol} />
          <AiMarketSentiment />
        </div>

        <div className="min-h-[560px] shrink-0">
          <MarketChart symbol={selectedSymbol} />
        </div>

        <div className="space-y-6 lg:max-h-[35vh] lg:flex-none lg:overflow-y-auto lg:pr-1">

        {errorMessage && (
          <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {errorMessage}
          </section>
        )}

        <PortfolioChart items={assets} isLoading={isLoading} />

        <section className="rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <header className="border-b border-gray-200 px-5 py-4 dark:border-gray-700">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Assets</h2>
          </header>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
              <thead className="bg-gray-100 text-left text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                <tr>
                  <th className="px-5 py-3 font-semibold">종목명</th>
                  <th className="px-5 py-3 font-semibold">현재가</th>
                  <th className="px-5 py-3 font-semibold">평균단가</th>
                  <th className="px-5 py-3 font-semibold">수익률</th>
                  <th className="px-5 py-3 font-semibold">추정금액</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-700 dark:bg-gray-800">
                {isLoading && (
                  <tr>
                    <td colSpan={5} className="px-5 py-8 text-center text-gray-500 dark:text-gray-300">
                      자산 데이터를 불러오는 중입니다.
                    </td>
                  </tr>
                )}

                {!isLoading && assets.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-5 py-8 text-center text-gray-500 dark:text-gray-300">
                      보유 중인 자산이 없습니다.
                    </td>
                  </tr>
                )}

                {!isLoading &&
                  assets.map((item) => {
                    const assetPnlClass = item.pnl_percentage >= 0 ? 'text-emerald-600' : 'text-rose-600'

                    return (
                      <tr key={`${item.broker}-${item.currency}`} className="text-gray-700 dark:text-gray-200">
                        <td className="px-5 py-3 font-medium text-gray-900 dark:text-gray-100">
                          {item.currency}
                          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-300">{item.broker}</p>
                        </td>
                        <td className="px-5 py-3">{formatKrw(item.current_price)}</td>
                        <td className="px-5 py-3">{formatKrw(item.avg_buy_price)}</td>
                        <td className={`px-5 py-3 font-semibold ${assetPnlClass}`}>
                          {formatPercent(item.pnl_percentage)}
                        </td>
                        <td className="px-5 py-3 font-semibold text-gray-900 dark:text-gray-100">{formatKrw(item.total_value)}</td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          </div>
        </section>

        <RecentOrders orders={orders} isLoading={isOrdersLoading} errorMessage={ordersErrorMessage} />
        </div>
      </div>

      <div className="flex flex-col lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-hidden">
        <div className="space-y-6 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overscroll-contain lg:pr-1">
          <MarketSearchBar onSelectSymbol={setSelectedSymbol} />
          <AiCoreStatus />

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
            <article className="rounded-2xl bg-white p-6 text-gray-900 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:ring-gray-700">
              <p className="text-sm font-medium text-gray-500 dark:text-gray-300">총 자산</p>
              <p className="mt-2 text-3xl font-bold sm:text-4xl lg:text-3xl">{isLoading ? '불러오는 중...' : formatKrw(totalNetWorth)}</p>
            </article>

            <article className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
              <p className="text-sm font-medium text-gray-500 dark:text-gray-300">총 손익</p>
              <p className={`mt-2 text-3xl font-bold sm:text-4xl lg:text-3xl ${pnlTextColor}`}>
                {isLoading ? '불러오는 중...' : formatSignedKrw(totalPnl)}
              </p>
            </article>
          </section>

          <BotControlPanel />
          <Watchlist selectedSymbol={selectedSymbol} onSelectSymbol={setSelectedSymbol} />
          <ControlPanel />
          <SentimentWidget />
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
