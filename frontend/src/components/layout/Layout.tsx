import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, type ReactNode } from 'react'

import { usePortfolioSummary } from '../../hooks/usePortfolioSummary'
import { resolvePortfolioDataState } from '../../pages/portfolioDataState'
import {
  getBotStatus,
  type LiveOrderMode,
  type TradingMode,
} from '../../services/api'
import AppShell from './AppShell'
import type { RuntimeStatus } from './ModeBanner'

interface LayoutProps {
  children: ReactNode
}

const LIVE_ORDER_MODES = new Set<LiveOrderMode>(['ARMED', 'EXIT_ONLY', 'BLOCK_ALL'])

function Layout({ children }: LayoutProps) {
  const portfolioSummaryQuery = usePortfolioSummary()
  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })
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

  const portfolioState = resolvePortfolioDataState({
    data: portfolioSummaryQuery.data,
    error: portfolioSummaryQuery.error,
    isError: portfolioSummaryQuery.isError,
    isLoading: portfolioSummaryQuery.isLoading,
    isRefetchError: portfolioSummaryQuery.isRefetchError,
  })
  const portfolioSummary = portfolioState.portfolio
  const totalNetWorth = portfolioSummary?.total_net_worth ?? 0
  const totalPnl = portfolioSummary?.total_pnl ?? 0
  const isPortfolioLoading = portfolioState.kind === 'loading'
  const portfolioErrorCode = portfolioState.errorCode
  const isPortfolioStale = portfolioState.isStale
  const portfolioUpdatedAt = portfolioState.updatedAt
  const portfolioSource = portfolioState.source

  const botStatus = botStatusQuery.data
  const botStatusAvailable = !botStatusQuery.isError && botStatus !== undefined
  const rawTradingMode = botStatus?.trading_mode
  const tradingModeAvailable =
    botStatusAvailable &&
    (rawTradingMode === 'paper' || rawTradingMode === 'live') &&
    Number.isInteger(botStatus.trading_mode_version) &&
    botStatus.trading_mode_version >= 1 &&
    botStatus.trading_mode_state_available === true &&
    botStatus.trading_mode_mirror_consistent === true
  const tradingMode: TradingMode | null = tradingModeAvailable ? rawTradingMode : null
  const runtimeStatus: RuntimeStatus =
    !botStatusAvailable || typeof botStatus.running !== 'boolean'
    ? 'UNAVAILABLE'
    : botStatus.running
      ? 'RUNNING'
      : 'STOPPED'
  const orderGate: LiveOrderMode | null =
    botStatusAvailable &&
    botStatus.live_order_state_available === true &&
    LIVE_ORDER_MODES.has(botStatus.live_order_mode)
      ? botStatus.live_order_mode
      : null
  const rolloutEnabled =
    botStatusAvailable && typeof botStatus.live_order_rollout_enabled === 'boolean'
      ? botStatus.live_order_rollout_enabled
      : null

  return (
    <AppShell
      navbarProps={{
        totalNetWorth,
        totalPnl,
        isPortfolioLoading,
        portfolioError: portfolioErrorCode,
        portfolioIsStale: isPortfolioStale,
        portfolioUpdatedAt,
        portfolioSource,
      }}
      modeBannerProps={{ runtimeStatus, tradingMode, orderGate, rolloutEnabled }}
    >
      {children}
    </AppShell>
  )
}

export default Layout
