import { AlertTriangle } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { useSystemConfigs } from '../../hooks/useSystemConfigs'
import AiCoreStatus from '../trading/AiCoreStatus'
import { getPortfolioSummary } from '../../services/portfolioService'
import type { PortfolioSummary } from '../../services/portfolioService'
import Navbar from './Navbar'

interface LayoutProps {
  children: ReactNode
}

const TRADING_MODE_KEY = 'trading_mode'

function Layout({ children }: LayoutProps) {
  const systemConfigsQuery = useSystemConfigs()
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null)
  const [portfolioErrorCode, setPortfolioErrorCode] = useState<string | null>(null)
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
        setPortfolioErrorCode(summary.error ?? null)
      } catch (error) {
        console.warn('[Layout polling] portfolio refresh failed', error)
        if (!isMounted) {
          return
        }
        setPortfolioErrorCode('PORTFOLIO_FETCH_FAILED')
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
        setPortfolioErrorCode(summary.error ?? null)
      } catch (error) {
        console.warn('[Layout polling] portfolio refresh failed', error)
        if (!isMounted) {
          return
        }
        setPortfolioErrorCode('PORTFOLIO_FETCH_FAILED')
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
  const isPaperTradingMode = useMemo(() => {
    const tradingModeValue =
      systemConfigsQuery.data?.find((item) => item.config_key === TRADING_MODE_KEY)?.config_value ?? 'live'

    return tradingModeValue.trim().toLowerCase() === 'paper'
  }, [systemConfigsQuery.data])

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-100 text-gray-900 transition-colors dark:bg-gray-900 dark:text-gray-100">
      <Navbar
        aiStatus={<AiCoreStatus />}
        totalNetWorth={totalNetWorth}
        totalPnl={totalPnl}
        isPortfolioLoading={isPortfolioLoading}
        portfolioError={portfolioErrorCode}
      />
      <main className="mx-auto flex-1 min-h-0 w-full max-w-full overflow-y-auto px-4 pb-10 pt-24 sm:px-6 lg:px-8">
        {isPaperTradingMode && (
          <div className="sticky top-16 z-40 -mx-4 mb-6 border-b border-amber-300 bg-amber-100/95 px-4 py-3 shadow-sm backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8 dark:border-amber-400/30 dark:bg-amber-500/20">
            <div className="mx-auto flex w-full max-w-full items-start gap-3 text-sm font-semibold leading-6 text-amber-950 dark:text-amber-50">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <p>
                현재 가짜 머니를 사용하는 <span className="font-extrabold">[가상 모의투자 모드]</span>로
                봇이 작동 중입니다. 매매가 체결되어도 실제 자산에 영향을 주지 않습니다.
              </p>
            </div>
          </div>
        )}
        {children}
      </main>
    </div>
  )
}

export default Layout
