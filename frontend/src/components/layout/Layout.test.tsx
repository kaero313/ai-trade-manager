// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Layout from './Layout'

const apiMocks = vi.hoisted(() => ({
  getBotStatus: vi.fn(),
}))

const portfolioMocks = vi.hoisted(() => ({
  usePortfolioSummary: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)
vi.mock('../../hooks/usePortfolioSummary', () => portfolioMocks)
vi.mock('./AppShell', () => ({
  default: ({
    children,
    modeBannerProps,
    navbarProps,
  }: {
    children: React.ReactNode
    modeBannerProps: {
      runtimeStatus: string
      tradingMode: 'paper' | 'live' | null
      orderGate: string | null
      rolloutEnabled: boolean | null
    }
    navbarProps: {
      totalNetWorth: number
      portfolioError: string | null
      portfolioIsStale: boolean
      portfolioSource: 'live' | 'snapshot' | 'empty' | null
    }
  }) => (
    <div>
      <span>
        {modeBannerProps.tradingMode === 'paper'
          ? 'PAPER 모의투자 모드'
          : modeBannerProps.tradingMode === 'live'
            ? 'LIVE 실거래 모드'
            : '거래 모드 확인 불가'}
      </span>
      <span>Runtime {modeBannerProps.runtimeStatus}</span>
      <span>Order Gate {modeBannerProps.orderGate ?? 'UNAVAILABLE'}</span>
      <span>
        Rollout {modeBannerProps.rolloutEnabled === null ? 'UNAVAILABLE' : String(modeBannerProps.rolloutEnabled)}
      </span>
      <span data-testid="navbar-source">{navbarProps.portfolioSource ?? 'UNAVAILABLE'}</span>
      <span data-testid="navbar-total">{String(navbarProps.totalNetWorth)}</span>
      <span data-testid="navbar-error">{navbarProps.portfolioError ?? 'NONE'}</span>
      <span data-testid="navbar-stale">{String(navbarProps.portfolioIsStale)}</span>
      {children}
    </div>
  ),
}))

function renderLayout() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <Layout>
          <div>page</div>
        </Layout>
      </QueryClientProvider>,
    ),
  }
}

describe('Layout 거래 모드 상시 배너', () => {
  beforeEach(() => {
    portfolioMocks.usePortfolioSummary.mockReturnValue({
      data: null,
      error: null,
      isError: false,
      isLoading: false,
    })
  })

  afterEach(() => {
    cleanup()
    apiMocks.getBotStatus.mockReset()
    portfolioMocks.usePortfolioSummary.mockReset()
  })

  it('정상 paper 상태를 모의투자 배너로 표시한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue({
      running: false,
      live_order_mode: 'BLOCK_ALL',
      live_order_rollout_enabled: false,
      live_order_state_available: true,
      trading_mode: 'paper',
      trading_mode_version: 1,
      trading_mode_state_available: true,
      trading_mode_mirror_consistent: true,
    })

    renderLayout()

    expect(await screen.findByText(/PAPER 모의투자 모드/)).toBeTruthy()
    expect(screen.getByText('Runtime STOPPED')).toBeTruthy()
    expect(screen.getByText('Order Gate BLOCK_ALL')).toBeTruthy()
  })

  it('정상 live 상태를 실거래 경고 배너로 표시한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue({
      running: true,
      live_order_mode: 'ARMED',
      live_order_rollout_enabled: true,
      live_order_state_available: true,
      trading_mode: 'live',
      trading_mode_version: 2,
      trading_mode_state_available: true,
      trading_mode_mirror_consistent: true,
    })

    renderLayout()

    expect(await screen.findByText(/LIVE 실거래 모드/)).toBeTruthy()
    expect(screen.getByText('Runtime RUNNING')).toBeTruthy()
    expect(screen.getByText('Order Gate ARMED')).toBeTruthy()
  })

  it('누락 또는 불일치 상태를 live로 fallback하지 않는다', async () => {
    apiMocks.getBotStatus.mockResolvedValue({
      running: true,
      live_order_mode: 'ARMED',
      live_order_rollout_enabled: true,
      live_order_state_available: false,
      trading_mode: 'live',
      trading_mode_version: 2,
      trading_mode_state_available: false,
      trading_mode_mirror_consistent: false,
    })

    renderLayout()

    expect(await screen.findByText(/거래 모드 확인 불가/)).toBeTruthy()
    expect(screen.queryByText(/LIVE 실거래 모드/)).toBeNull()
    expect(screen.getByText('Order Gate UNAVAILABLE')).toBeTruthy()
  })

  it('runtime과 rollout 필드가 누락되면 정지나 OFF로 추정하지 않는다', async () => {
    apiMocks.getBotStatus.mockResolvedValue({
      live_order_mode: 'BLOCK_ALL',
      live_order_state_available: true,
      trading_mode: 'paper',
      trading_mode_version: 2,
      trading_mode_state_available: true,
      trading_mode_mirror_consistent: true,
    })

    renderLayout()

    expect(await screen.findByText(/PAPER 모의투자 모드/)).toBeTruthy()
    expect(screen.getByText('Runtime UNAVAILABLE')).toBeTruthy()
    expect(screen.getByText('Rollout UNAVAILABLE')).toBeTruthy()
  })

  it('정상 live 뒤 polling이 실패하면 stale live 대신 unavailable 배너를 표시한다', async () => {
    apiMocks.getBotStatus
      .mockResolvedValueOnce({
        running: true,
        live_order_mode: 'ARMED',
        live_order_rollout_enabled: true,
        live_order_state_available: true,
        trading_mode: 'live',
        trading_mode_version: 2,
        trading_mode_state_available: true,
        trading_mode_mirror_consistent: true,
      })
      .mockRejectedValue(new Error('status polling failed'))

    const { queryClient } = renderLayout()
    expect(await screen.findByText(/LIVE 실거래 모드/)).toBeTruthy()

    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['bot-status'] })
    })

    expect(await screen.findByText(/거래 모드 확인 불가/)).toBeTruthy()
    expect(screen.queryByText(/LIVE 실거래 모드/)).toBeNull()
    expect(screen.getByText('Runtime UNAVAILABLE')).toBeTruthy()
    expect(screen.getByText('Order Gate UNAVAILABLE')).toBeTruthy()
    expect(screen.getByText('Rollout UNAVAILABLE')).toBeTruthy()
  })

  it('유효하지 않은 포트폴리오 숫자를 금액으로 전달하지 않는다', async () => {
    portfolioMocks.usePortfolioSummary.mockReturnValue({
      data: {
        source: 'live',
        is_stale: false,
        error: null,
        updated_at: '2026-07-15T00:00:00Z',
        total_net_worth: Number.NaN,
        total_pnl: 0,
        items: [],
      },
      error: null,
      isError: false,
      isLoading: false,
      isRefetchError: false,
    })
    apiMocks.getBotStatus.mockResolvedValue({
      running: false,
      live_order_mode: 'BLOCK_ALL',
      live_order_rollout_enabled: false,
      live_order_state_available: true,
      trading_mode: 'paper',
      trading_mode_version: 1,
      trading_mode_state_available: true,
      trading_mode_mirror_consistent: true,
    })

    renderLayout()

    expect((await screen.findByTestId('navbar-source')).textContent).toBe('UNAVAILABLE')
    expect(screen.getByTestId('navbar-total').textContent).toBe('0')
    expect(screen.getByTestId('navbar-error').textContent).toBe('PORTFOLIO_INVALID_DATA')
  })

  it('snapshot 출처와 stale 상태를 Navbar에 그대로 전달한다', async () => {
    portfolioMocks.usePortfolioSummary.mockReturnValue({
      data: {
        source: 'snapshot',
        is_stale: true,
        error: 'LIVE_FETCH_FAILED',
        updated_at: '2026-07-15T00:00:00Z',
        total_net_worth: 123456,
        total_pnl: 789,
        items: [],
      },
      error: null,
      isError: false,
      isLoading: false,
      isRefetchError: false,
    })
    apiMocks.getBotStatus.mockResolvedValue({
      running: false,
      live_order_mode: 'BLOCK_ALL',
      live_order_rollout_enabled: false,
      live_order_state_available: true,
      trading_mode: 'paper',
      trading_mode_version: 1,
      trading_mode_state_available: true,
      trading_mode_mirror_consistent: true,
    })

    renderLayout()

    expect((await screen.findByTestId('navbar-source')).textContent).toBe('snapshot')
    expect(screen.getByTestId('navbar-total').textContent).toBe('123456')
    expect(screen.getByTestId('navbar-stale').textContent).toBe('true')
  })
})
