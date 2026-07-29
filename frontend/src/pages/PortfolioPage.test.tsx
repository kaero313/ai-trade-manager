// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioSummary } from '../services/portfolioService'
import PortfolioPage from './PortfolioPage'

const mocks = vi.hoisted(() => ({
  createChatSession: vi.fn(),
  fetchLatestAnalysisBatch: vi.fn(),
  fetchPortfolioSnapshots: vi.fn(),
  usePortfolioSummary: vi.fn(),
}))

vi.mock('../hooks/usePortfolioSummary', () => ({
  usePortfolioSummary: mocks.usePortfolioSummary,
}))
vi.mock('../services/api', () => ({
  createChatSession: mocks.createChatSession,
}))
vi.mock('../services/portfolioService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/portfolioService')>()
  return {
    ...actual,
    fetchLatestAnalysisBatch: mocks.fetchLatestAnalysisBatch,
    fetchPortfolioSnapshots: mocks.fetchPortfolioSnapshots,
  }
})
vi.mock('../components/portfolio/PortfolioAiBriefing', () => ({
  default: ({ isPortfolioAvailable }: { isPortfolioAvailable: boolean }) => (
    <div data-testid="ai-briefing">briefing:{String(isPortfolioAvailable)}</div>
  ),
}))
vi.mock('../components/portfolio/PortfolioMiniChat', () => ({
  default: ({ isPortfolioAvailable }: { isPortfolioAvailable: boolean }) => (
    <div data-testid="mini-chat">chat:{String(isPortfolioAvailable)}</div>
  ),
}))
vi.mock('../components/portfolio/PortfolioSummaryCard', () => ({
  default: ({ totalNetWorth }: { totalNetWorth: number }) => (
    <div data-testid="summary-card">summary:{totalNetWorth}</div>
  ),
}))
vi.mock('../components/portfolio/PortfolioAllocationChart', () => ({
  default: () => <div>allocation</div>,
}))
vi.mock('../components/portfolio/PortfolioHoldingsTable', () => ({
  default: () => <div>holdings</div>,
}))
vi.mock('../components/portfolio/PortfolioPeriodPnlChart', () => ({
  default: () => <div>performance</div>,
}))

function buildPortfolio(overrides: Partial<PortfolioSummary> = {}): PortfolioSummary {
  return {
    total_net_worth: 12_500_000,
    total_pnl: 250_000,
    items: [
      {
        broker: 'UPBIT',
        currency: 'KRW',
        balance: 5_000_000,
        locked: 0,
        avg_buy_price: 1,
        current_price: 1,
        total_value: 5_000_000,
        pnl_percentage: 0,
      },
      {
        broker: 'UPBIT',
        currency: 'BTC',
        balance: 0.05,
        locked: 0,
        avg_buy_price: 100_000_000,
        current_price: 150_000_000,
        total_value: 7_500_000,
        pnl_percentage: 50,
      },
    ],
    source: 'live',
    is_stale: false,
    updated_at: '2026-07-15T03:00:00Z',
    error: null,
    ...overrides,
  }
}

function setQueryState({
  data,
  error = null,
  isError = false,
  isLoading = false,
  isRefetchError = false,
}: {
  data: PortfolioSummary | null
  error?: Error | null
  isError?: boolean
  isLoading?: boolean
  isRefetchError?: boolean
}) {
  mocks.usePortfolioSummary.mockReturnValue({
    data,
    error,
    isError,
    isFetching: false,
    isLoading,
    isRefetchError,
    refetch: vi.fn(),
  })
}

describe('PortfolioPage 포트폴리오 사실성', () => {
  beforeEach(() => {
    mocks.createChatSession.mockResolvedValue({ session_id: 'portfolio-session' })
    mocks.fetchLatestAnalysisBatch.mockResolvedValue({})
    mocks.fetchPortfolioSnapshots.mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('empty 응답을 정상 0원으로 표시하지 않고 모든 AI 요청을 차단한다', async () => {
    setQueryState({
      data: buildPortfolio({
        source: 'empty',
        total_net_worth: 0,
        total_pnl: 0,
        items: [],
      }),
    })

    render(<PortfolioPage />)

    expect(screen.getByText('포트폴리오 금액을 표시할 수 없습니다')).toBeTruthy()
    expect(screen.getByText(/정상 ₩0 포트폴리오로 대체하지 않습니다/)).toBeTruthy()
    expect(screen.queryByTestId('summary-card')).toBeNull()
    expect(screen.getByTestId('ai-briefing').textContent).toBe('briefing:false')
    expect(screen.getByTestId('mini-chat').textContent).toBe('chat:false')
    await waitFor(() => expect(mocks.fetchPortfolioSnapshots).toHaveBeenCalledTimes(1))
    expect(mocks.createChatSession).not.toHaveBeenCalled()
    expect(mocks.fetchLatestAnalysisBatch).not.toHaveBeenCalled()
  })

  it('캐시 없는 조회 오류를 hard error로 숨기고 과거 금액을 만들지 않는다', () => {
    setQueryState({
      data: null,
      error: new Error('UPBIT_AUTH_FAILED'),
      isError: true,
    })

    render(<PortfolioPage />)

    expect(screen.getByText('UNAVAILABLE')).toBeTruthy()
    expect(screen.queryByTestId('summary-card')).toBeNull()
    expect(screen.getAllByText(/거래소 인증 상태를 확인할 수 없습니다/).length).toBeGreaterThan(0)
    expect(mocks.createChatSession).not.toHaveBeenCalled()
  })

  it('live 응답은 실제 수치와 해당 종목만 사용해 AI context를 준비한다', async () => {
    setQueryState({ data: buildPortfolio() })

    render(<PortfolioPage />)

    expect(screen.getByTestId('summary-card').textContent).toBe('summary:12500000')
    expect(screen.getByTestId('ai-briefing').textContent).toBe('briefing:true')
    expect(screen.getByTestId('mini-chat').textContent).toBe('chat:true')
    await waitFor(() => {
      expect(mocks.createChatSession).toHaveBeenCalledWith('portfolio')
      expect(mocks.fetchLatestAnalysisBatch).toHaveBeenCalledWith(['KRW-BTC'])
    })
  })

  it('refetch 오류는 마지막 수치를 유지하면서 stale과 오류를 명시한다', () => {
    setQueryState({
      data: buildPortfolio(),
      error: new Error('network failed'),
      isError: true,
      isRefetchError: true,
    })

    render(<PortfolioPage />)

    expect(screen.getByText('STALE')).toBeTruthy()
    expect(screen.getByText('오류: network failed')).toBeTruthy()
    expect(screen.getByTestId('summary-card').textContent).toBe('summary:12500000')
  })
})
