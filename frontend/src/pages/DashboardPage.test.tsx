// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import DashboardPage from './DashboardPage'

vi.mock('../components/trading/AiActivityLiveFlow', () => ({
  default: () => <div>AI 활동</div>,
}))
vi.mock('../components/trading/AiInsightBriefing', () => ({
  default: () => <div>AI 분석</div>,
}))
vi.mock('../components/trading/AiMarketSentiment', () => ({
  default: () => <div>시장 심리</div>,
}))
vi.mock('../components/trading/AiNewsBoard', () => ({
  default: () => <div>뉴스</div>,
}))
vi.mock('../components/trading/AiPerformanceWidget', () => ({
  default: () => <div>AI 성과</div>,
}))
vi.mock('../components/trading/BotControlPanel', () => ({
  default: () => <div>봇 제어</div>,
}))
vi.mock('../components/trading/ControlPanel', () => ({
  default: () => <div>청산 제어</div>,
}))
vi.mock('../components/trading/MarketChart', () => ({
  default: () => <div>시장 차트</div>,
}))
vi.mock('../components/trading/PortfolioChart', () => ({
  default: () => <div>포트폴리오 차트</div>,
}))
vi.mock('../components/trading/RecentOrders', () => ({
  default: () => <div>최근 주문</div>,
}))
vi.mock('../components/trading/Watchlist', () => ({
  default: () => <div>관심 종목</div>,
}))
vi.mock('../hooks/usePortfolioSummary', () => ({
  usePortfolioSummary: () => ({
    data: null,
    error: null,
    isError: false,
    isLoading: false,
    isRefetchError: false,
  }),
}))
vi.mock('../services/portfolioService', () => ({
  fetchOrders: vi.fn().mockResolvedValue([]),
}))

describe('DashboardPage 반응형 운영 레이아웃', () => {
  afterEach(() => {
    cleanup()
  })

  it('중간 데스크톱은 차트를 먼저 넓게 배치하고 보조 패널을 2열로 정리한다', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const grid = screen.getByTestId('dashboard-grid')
    const leftColumn = screen.getByTestId('dashboard-left-column')
    const centerColumn = screen.getByTestId('dashboard-center-column')
    const rightColumn = screen.getByTestId('dashboard-right-column')

    expect(grid.className).toContain('lg:grid-cols-2')
    expect(grid.className).toContain('2xl:grid-cols-12')
    expect(centerColumn.className).toContain('lg:order-1')
    expect(centerColumn.className).toContain('lg:col-span-2')
    expect(leftColumn.className).toContain('lg:order-2')
    expect(rightColumn.className).toContain('lg:order-3')
    expect(screen.getByTestId('dashboard-chart').className).toContain('xl:h-[480px]')
    expect(screen.getByTestId('dashboard-controls').className).toContain('lg:grid-cols-2')
    expect(screen.getAllByText('청산 제어')).toHaveLength(1)
    expect(screen.getAllByText('봇 제어')).toHaveLength(1)
  })
})
