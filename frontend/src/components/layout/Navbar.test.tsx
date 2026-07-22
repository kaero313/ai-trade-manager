// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Navbar from './Navbar'

vi.mock('../trading/MarketSearchBar', () => ({
  default: () => <div>종목 검색</div>,
}))

vi.mock('../common/ThemeToggle', () => ({
  default: () => <button type="button">테마</button>,
}))

function renderNavbar(
  overrides: Partial<ComponentProps<typeof Navbar>> = {},
) {
  render(
    <MemoryRouter>
      <Navbar
        totalNetWorth={100000}
        totalPnl={1000}
        isPortfolioLoading={false}
        portfolioError={null}
        portfolioIsStale={false}
        portfolioUpdatedAt="2026-07-15T00:00:00Z"
        portfolioSource="live"
        onOpenNavigation={vi.fn()}
        {...overrides}
      />
    </MemoryRouter>,
  )
}

describe('Navbar 포트폴리오 상태', () => {
  afterEach(() => {
    cleanup()
  })

  it('snapshot 출처를 LIVE로 축약하지 않는다', () => {
    renderNavbar({ portfolioSource: 'snapshot', portfolioIsStale: true })

    expect(screen.getByText(/Portfolio SNAPSHOT/)).toBeTruthy()
    expect(screen.queryByText(/Portfolio LIVE/)).toBeNull()
  })

  it('출처를 확인할 수 없으면 금액 대신 UNAVAILABLE을 표시한다', () => {
    renderNavbar({
      totalNetWorth: Number.NaN,
      totalPnl: Number.NaN,
      portfolioSource: null,
      portfolioError: 'PORTFOLIO_INVALID_DATA',
    })

    expect(screen.getByText('Portfolio UNAVAILABLE')).toBeTruthy()
    expect(screen.queryByText(/₩NaN/)).toBeNull()
  })

  it('데스크톱 사이드바 상태에 맞춰 왼쪽 여백을 전환한다', () => {
    const { container, rerender } = render(
      <MemoryRouter>
        <Navbar
          totalNetWorth={100000}
          totalPnl={1000}
          isPortfolioLoading={false}
          portfolioError={null}
          portfolioIsStale={false}
          portfolioUpdatedAt="2026-07-15T00:00:00Z"
          portfolioSource="live"
          onOpenNavigation={vi.fn()}
        />
      </MemoryRouter>,
    )

    const header = container.querySelector('header')

    expect(header?.className).toContain('lg:left-60')
    expect(header?.firstElementChild?.className).toContain('max-w-[1440px]')

    rerender(
      <MemoryRouter>
        <Navbar
          totalNetWorth={100000}
          totalPnl={1000}
          isPortfolioLoading={false}
          portfolioError={null}
          portfolioIsStale={false}
          portfolioUpdatedAt="2026-07-15T00:00:00Z"
          portfolioSource="live"
          desktopNavigationCollapsed
          onOpenNavigation={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(header?.className).toContain('lg:left-20')
    expect(header?.firstElementChild?.className).toContain('max-w-[1600px]')
  })
})
