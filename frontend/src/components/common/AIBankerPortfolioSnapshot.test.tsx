// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PortfolioSummary } from '../../services/portfolioService'
import AIBankerPortfolioSnapshot from './AIBankerPortfolioSnapshot'

const mocks = vi.hoisted(() => ({
  usePortfolioSummary: vi.fn(),
}))

vi.mock('../../hooks/usePortfolioSummary', () => ({
  usePortfolioSummary: mocks.usePortfolioSummary,
}))

function buildPortfolio(overrides: Partial<PortfolioSummary> = {}): PortfolioSummary {
  return {
    total_net_worth: 8_000_000,
    total_pnl: -100_000,
    items: [
      {
        broker: 'SNAPSHOT',
        currency: 'KRW',
        balance: 3_000_000,
        locked: 0,
        avg_buy_price: 1,
        current_price: 1,
        total_value: 3_000_000,
        pnl_percentage: 0,
      },
    ],
    source: 'snapshot',
    is_stale: true,
    updated_at: '2026-07-15T03:00:00Z',
    error: 'PORTFOLIO_FETCH_FAILED',
    ...overrides,
  }
}

describe('AIBankerPortfolioSnapshot 사실성', () => {
  afterEach(() => {
    cleanup()
    mocks.usePortfolioSummary.mockReset()
  })

  it('snapshot은 마지막 수치와 stale 근거를 함께 표시한다', () => {
    mocks.usePortfolioSummary.mockReturnValue({
      data: buildPortfolio(),
      error: null,
      isError: false,
      isFetching: false,
      isLoading: false,
      isRefetchError: false,
    })

    render(<AIBankerPortfolioSnapshot />)

    expect(screen.getByText('SNAPSHOT')).toBeTruthy()
    expect(screen.getByText('₩8,000,000')).toBeTruthy()
    expect(screen.getByText(/PORTFOLIO_FETCH_FAILED/)).toBeTruthy()
  })

  it('empty는 정상 0원으로 표시하지 않는다', () => {
    mocks.usePortfolioSummary.mockReturnValue({
      data: buildPortfolio({
        source: 'empty',
        total_net_worth: 0,
        total_pnl: 0,
        items: [],
        updated_at: null,
      }),
      error: null,
      isError: false,
      isFetching: false,
      isLoading: false,
      isRefetchError: false,
    })

    render(<AIBankerPortfolioSnapshot />)

    expect(screen.getByText('포트폴리오 금액을 표시할 수 없습니다')).toBeTruthy()
    expect(screen.queryByText('₩0')).toBeNull()
  })
})
