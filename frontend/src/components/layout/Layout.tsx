import { useEffect, useState, type ReactNode } from 'react'

import AiCoreStatus from '../trading/AiCoreStatus'
import { getPortfolioSummary } from '../../services/portfolioService'
import type { PortfolioSummary } from '../../services/portfolioService'
import Navbar from './Navbar'

interface LayoutProps {
  children: ReactNode
}

function Layout({ children }: LayoutProps) {
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null)
  const [isPortfolioLoading, setIsPortfolioLoading] = useState(true)

  useEffect(() => {
    let isMounted = true
    let isPolling = false
    let pollingIntervalId: number | undefined

    const loadPortfolioInitial = async () => {
      setIsPortfolioLoading(true)

      try {
        const summary = await getPortfolioSummary()
        if (!isMounted) {
          return
        }
        setPortfolioSummary(summary)
      } catch (error) {
        console.warn('[Layout polling] portfolio refresh failed', error)
      } finally {
        if (isMounted) {
          setIsPortfolioLoading(false)
        }
      }
    }

    const refreshPortfolioSilent = async () => {
      if (isPolling) {
        return
      }

      isPolling = true
      try {
        const summary = await getPortfolioSummary()
        if (!isMounted) {
          return
        }
        setPortfolioSummary(summary)
      } catch (error) {
        console.warn('[Layout polling] portfolio refresh failed', error)
      } finally {
        isPolling = false
      }
    }

    const bootstrap = async () => {
      await loadPortfolioInitial()
      if (!isMounted) {
        return
      }

      pollingIntervalId = window.setInterval(() => {
        void refreshPortfolioSilent()
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

  const totalNetWorth = portfolioSummary?.total_net_worth ?? 0
  const totalPnl = portfolioSummary?.total_pnl ?? 0

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-100 text-gray-900 transition-colors dark:bg-gray-900 dark:text-gray-100">
      <Navbar
        aiStatus={<AiCoreStatus />}
        totalNetWorth={totalNetWorth}
        totalPnl={totalPnl}
        isPortfolioLoading={isPortfolioLoading}
      />
      <main className="mx-auto flex-1 min-h-0 w-full max-w-full overflow-y-auto px-4 pb-10 pt-24 sm:px-6 lg:px-8">
        {children}
      </main>
    </div>
  )
}

export default Layout
