import { useQuery } from '@tanstack/react-query'
import { Activity, ShieldCheck, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import AiActivityLiveFlow from '../components/trading/AiActivityLiveFlow'
import AiInsightBriefing from '../components/trading/AiInsightBriefing'
import AiMarketSentiment from '../components/trading/AiMarketSentiment'
import AiNewsBoard from '../components/trading/AiNewsBoard'
import AiPerformanceWidget from '../components/trading/AiPerformanceWidget'
import BotControlPanel from '../components/trading/BotControlPanel'
import ControlPanel from '../components/trading/ControlPanel'
import MarketChart from '../components/trading/MarketChart'
import PortfolioChart from '../components/trading/PortfolioChart'
import RecentOrders from '../components/trading/RecentOrders'
import WatchlistSidebar from '../components/trading/Watchlist'
import { usePortfolioSummary } from '../hooks/usePortfolioSummary'
import { fetchOrders } from '../services/portfolioService'
import type { AssetItem } from '../services/portfolioService'
import { resolvePortfolioDataState } from './portfolioDataState'

function resolveTabClassName(isActive: boolean): string {
  return `quantum-tab ${isActive ? 'quantum-tab-active' : 'quantum-tab-inactive'}`
}

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

  const portfolioState = resolvePortfolioDataState({
    data: portfolioSummaryQuery.data,
    error: portfolioSummaryQuery.error,
    isError: portfolioSummaryQuery.isError,
    isLoading: portfolioSummaryQuery.isLoading,
    isRefetchError: portfolioSummaryQuery.isRefetchError,
  })
  const portfolio = portfolioState.portfolio
  const portfolioErrorCode = portfolioState.errorCode
  const portfolioIsStale = portfolioState.isStale
  const orders = ordersQuery.data ?? []
  const ordersHasRefreshError = ordersQuery.isError || ordersQuery.isRefetchError
  const ordersUpdatedAt = ordersQuery.dataUpdatedAt > 0 ? ordersQuery.dataUpdatedAt : null
  const ordersErrorMessage =
    ordersHasRefreshError && orders.length === 0 ? '최근 체결 내역을 불러오지 못했습니다.' : null
  const assets: AssetItem[] = portfolio?.items ?? []

  return (
    <div className="dashboard-quantum min-h-full space-y-4">
      <header className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div className="min-w-0">
          <p className="font-mono text-xs font-bold uppercase tracking-[0.22em] text-brand">
            Operations overview
          </p>
          <h1 className="mt-2 text-2xl font-extrabold tracking-tight text-content sm:text-3xl">
            AI 트레이딩 운영 대시보드
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-content-secondary">
            시장·AI 분석·포트폴리오 상태를 함께 확인합니다. 주문과 비상 제어는 기존 안전 경계를 그대로
            통과합니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label="대시보드 운영 원칙">
          <span className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 text-xs font-semibold text-content-secondary">
            <Activity className="h-4 w-4 text-brand" aria-hidden="true" />
            실시간 상태 조회
          </span>
          <span className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 text-xs font-semibold text-content-secondary">
            <ShieldCheck className="h-4 w-4 text-warning" aria-hidden="true" />
            중앙 주문 경계 유지
          </span>
        </div>
      </header>

      <AiActivityLiveFlow />

      <div data-testid="dashboard-grid" className="grid min-h-0 gap-4 lg:grid-cols-2 2xl:grid-cols-12">
        <div
          data-testid="dashboard-left-column"
          className="flex min-w-0 flex-col gap-4 lg:order-2 lg:col-span-1 2xl:order-1 2xl:col-span-3 2xl:min-h-0"
        >
          <div className="flex min-w-0 flex-col gap-3">
            <div className="inline-flex w-fit shrink-0 rounded-xl border border-border-subtle bg-surface-lowest p-1">
              <button
                type="button"
                onClick={() => setMacroTab('sentiment')}
                className={resolveTabClassName(macroTab === 'sentiment')}
              >
                시장 심리
              </button>
              <button
                type="button"
                onClick={() => setMacroTab('news')}
                className={resolveTabClassName(macroTab === 'news')}
              >
                RAG 뉴스
              </button>
            </div>

            <section className="quantum-card macro-panel-shell overflow-hidden rounded-2xl">
              {macroTab === 'sentiment' ? (
                <div className="min-w-0">
                  <AiMarketSentiment />
                </div>
              ) : (
                <div className="flex max-h-[520px] min-h-0 flex-col overflow-hidden">
                  <AiNewsBoard />
                </div>
              )}
            </section>
          </div>
          <div className="min-h-[280px] overflow-hidden 2xl:min-h-0 [&>aside]:flex [&>aside]:h-full [&>aside]:min-h-0 [&>aside]:flex-1">
            <WatchlistSidebar selectedSymbol={selectedSymbol} onSelectSymbol={setSelectedSymbol} />
          </div>
        </div>

        <div
          data-testid="dashboard-center-column"
          className="flex min-w-0 flex-col gap-4 lg:order-1 lg:col-span-2 2xl:order-2 2xl:col-span-6 2xl:min-h-0"
        >
          <div data-testid="dashboard-chart" className="h-[400px] sm:h-[440px] xl:h-[480px]">
            <MarketChart symbol={selectedSymbol} />
          </div>
          <div className="min-h-0">
            <AiInsightBriefing symbol={selectedSymbol} />
          </div>
        </div>

        <div
          data-testid="dashboard-right-column"
          className="flex min-w-0 flex-col gap-4 lg:order-3 lg:col-span-1 2xl:order-3 2xl:col-span-3 2xl:min-h-0"
        >
          <div className="flex min-h-[220px] shrink-0 flex-col gap-3">
            <div className="inline-flex w-fit rounded-xl border border-border-subtle bg-surface-lowest p-1">
              <button
                type="button"
                onClick={() => setRightPanelTab('portfolio')}
                className={resolveTabClassName(rightPanelTab === 'portfolio')}
              >
                포트폴리오
              </button>
              <button
                type="button"
                onClick={() => setRightPanelTab('performance')}
                className={resolveTabClassName(rightPanelTab === 'performance')}
              >
                AI 성과
              </button>
            </div>
            <div className="min-h-[220px]">
              {rightPanelTab === 'portfolio' ? (
                <PortfolioChart
                  items={assets}
                  isLoading={portfolioState.kind === 'loading'}
                  source={portfolioState.source}
                  isStale={portfolioIsStale}
                  updatedAt={portfolioState.updatedAt}
                  errorCode={portfolioErrorCode}
                  totalNetWorth={portfolio?.total_net_worth ?? 0}
                  totalPnl={portfolio?.total_pnl ?? 0}
                />
              ) : (
                <AiPerformanceWidget />
              )}
            </div>
          </div>
          <div className="min-h-[180px] pr-1 2xl:min-h-0 2xl:flex-1">
            <RecentOrders
              orders={orders}
              isLoading={ordersQuery.isLoading}
              errorMessage={ordersErrorMessage}
              isStale={ordersHasRefreshError && orders.length > 0}
              updatedAt={ordersUpdatedAt}
            />
          </div>
        </div>
      </div>

      <div data-testid="dashboard-controls" className="grid gap-4 lg:grid-cols-2">
        <ControlPanel />
        <BotControlPanel portfolioError={portfolioErrorCode} />
      </div>

      <Link
        to="/chat"
        aria-label="AI 뱅커 열기"
        title="AI 뱅커 열기"
        className="group fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full border border-brand-bright/40 bg-brand text-surface-lowest shadow-lg shadow-brand/20 transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand active:scale-95 sm:bottom-8 sm:right-8"
      >
        <span className="absolute inset-1 rounded-full bg-brand-bright/20 opacity-0 transition-opacity group-hover:opacity-100" />
        <Sparkles className="relative h-6 w-6" aria-hidden="true" />
        <span className="sr-only">AI 뱅커 열기</span>
      </Link>
    </div>
  )
}

export default DashboardPage
