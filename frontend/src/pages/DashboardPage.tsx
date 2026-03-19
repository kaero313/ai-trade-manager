import { useEffect, useState } from 'react'

import { fetchOrders, getPortfolioSummary } from '../services/portfolioService'
import type { OrderHistoryItem, PortfolioSummary } from '../services/portfolioService'

function DashboardPage() {
  const [, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [, setOrders] = useState<OrderHistoryItem[]>([])
  const [, setIsLoading] = useState(true)
  const [, setIsOrdersLoading] = useState(true)
  const [, setErrorMessage] = useState<string | null>(null)
  const [, setOrdersErrorMessage] = useState<string | null>(null)

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

  return (
    <div className="grid h-full min-h-0 gap-6 lg:grid-cols-12 lg:overflow-hidden">
      <div className="flex flex-col gap-6 lg:col-span-6 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-2"></div>
      <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-2"></div>
      <div className="flex flex-col gap-6 lg:col-span-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-2"></div>
    </div>
  )
}

export default DashboardPage
