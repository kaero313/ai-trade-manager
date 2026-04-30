import { AlertTriangle } from 'lucide-react'
import { useEffect, useMemo, useRef, type ReactNode } from 'react'

import { useSystemConfigs } from '../../hooks/useSystemConfigs'
import { usePortfolioSummary } from '../../hooks/usePortfolioSummary'
import AiCoreStatus from '../trading/AiCoreStatus'
import Navbar from './Navbar'

interface LayoutProps {
  children: ReactNode
}

const TRADING_MODE_KEY = 'trading_mode'

function Layout({ children }: LayoutProps) {
  const systemConfigsQuery = useSystemConfigs()
  const portfolioSummaryQuery = usePortfolioSummary()
  const lastPortfolioWarningRef = useRef<string | null>(null)

  useEffect(() => {
    const warningKey = portfolioSummaryQuery.isError
      ? portfolioSummaryQuery.error instanceof Error
        ? portfolioSummaryQuery.error.message
        : 'PORTFOLIO_FETCH_FAILED'
      : portfolioSummaryQuery.data?.is_stale && portfolioSummaryQuery.data.error
        ? portfolioSummaryQuery.data.error
        : null

    if (warningKey === null) {
      lastPortfolioWarningRef.current = null
      return
    }

    if (lastPortfolioWarningRef.current !== warningKey) {
      console.warn('[Layout polling] portfolio refresh degraded', warningKey)
      lastPortfolioWarningRef.current = warningKey
    }
  }, [
    portfolioSummaryQuery.data?.error,
    portfolioSummaryQuery.data?.is_stale,
    portfolioSummaryQuery.error,
    portfolioSummaryQuery.isError,
  ])

  const portfolioSummary = portfolioSummaryQuery.data ?? null
  const totalNetWorth = portfolioSummary?.total_net_worth ?? 0
  const totalPnl = portfolioSummary?.total_pnl ?? 0
  const isPortfolioLoading = portfolioSummaryQuery.isLoading
  const portfolioErrorCode =
    portfolioSummaryQuery.isError && portfolioSummary === null
      ? 'PORTFOLIO_FETCH_FAILED'
      : portfolioSummary?.error ?? null
  const isPortfolioStale =
    Boolean(portfolioSummary?.is_stale) ||
    (portfolioSummaryQuery.isError && portfolioSummary !== null)
  const portfolioUpdatedAt = portfolioSummary?.updated_at ?? null
  const portfolioSource = portfolioSummary?.source ?? null
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
        portfolioIsStale={isPortfolioStale}
        portfolioUpdatedAt={portfolioUpdatedAt}
        portfolioSource={portfolioSource}
      />
      <main className="mx-auto flex-1 min-h-0 w-full max-w-full overflow-y-auto px-4 pb-10 pt-28 sm:px-6 lg:px-8 lg:pt-24">
        {isPaperTradingMode && (
          <div className="sticky top-24 z-40 -mx-4 mb-6 border-b border-amber-300 bg-amber-100/95 px-4 py-3 shadow-sm backdrop-blur sm:-mx-6 sm:px-6 lg:top-16 lg:-mx-8 lg:px-8 dark:border-amber-400/30 dark:bg-amber-500/20">
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
