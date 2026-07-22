// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AppShell from './AppShell'

vi.mock('./Navbar', () => ({
  default: ({
    onOpenNavigation,
    desktopNavigationCollapsed,
  }: {
    onOpenNavigation: () => void
    desktopNavigationCollapsed: boolean
  }) => (
    <div data-testid="navbar" data-collapsed={desktopNavigationCollapsed ? 'true' : 'false'}>
      <button type="button" onClick={onOpenNavigation}>
        메뉴 열기
      </button>
    </div>
  ),
}))

vi.mock('./SidebarNav', () => ({
  default: ({
    collapsed,
    onToggleCollapsed,
  }: {
    collapsed: boolean
    onToggleCollapsed: () => void
  }) => (
    <div>
      <span>{collapsed ? '데스크톱 메뉴 접힘' : '데스크톱 메뉴 펼침'}</span>
      <button type="button" onClick={onToggleCollapsed}>
        {collapsed ? '사이드바 펼치기' : '사이드바 접기'}
      </button>
    </div>
  ),
}))

vi.mock('./MobileNavDrawer', () => ({
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) => (
    <div>
      <span>{open ? '모바일 메뉴 열림' : '모바일 메뉴 닫힘'}</span>
      <button type="button" onClick={onClose}>
        메뉴 닫기
      </button>
    </div>
  ),
}))

vi.mock('./ModeBanner', () => ({
  default: ({ desktopNavigationCollapsed }: { desktopNavigationCollapsed: boolean }) => (
    <div
      data-testid="mode-banner"
      data-collapsed={desktopNavigationCollapsed ? 'true' : 'false'}
    >
      거래 안전 상태
    </div>
  ),
}))

const navbarProps = {
  totalNetWorth: 0,
  totalPnl: 0,
  isPortfolioLoading: false,
  portfolioError: null,
  portfolioIsStale: false,
  portfolioUpdatedAt: null,
  portfolioSource: null,
} as const

const modeBannerProps = {
  runtimeStatus: 'STOPPED',
  tradingMode: 'paper',
  orderGate: 'BLOCK_ALL',
  rolloutEnabled: false,
} as const

describe('AppShell', () => {
  afterEach(() => {
    cleanup()
  })

  it('모바일 drawer가 열리고 닫혀도 route children을 계속 mount한다', () => {
    render(
      <AppShell navbarProps={navbarProps} modeBannerProps={modeBannerProps}>
        <input aria-label="보존할 화면 상태" defaultValue="draft" />
      </AppShell>,
    )

    const pageState = screen.getByRole('textbox', { name: '보존할 화면 상태' })
    fireEvent.change(pageState, { target: { value: 'pending-request' } })
    fireEvent.click(screen.getByRole('button', { name: '메뉴 열기' }))

    expect(screen.getByText('모바일 메뉴 열림')).toBeTruthy()
    expect(
      (screen.getByRole('textbox', { name: '보존할 화면 상태' }) as HTMLInputElement).value,
    ).toBe('pending-request')

    fireEvent.click(screen.getByRole('button', { name: '메뉴 닫기' }))

    expect(screen.getByText('모바일 메뉴 닫힘')).toBeTruthy()
    expect(
      (screen.getByRole('textbox', { name: '보존할 화면 상태' }) as HTMLInputElement).value,
    ).toBe('pending-request')
  })

  it('키보드 사용자를 위한 본문 건너뛰기 링크와 고정 본문 영역을 제공한다', () => {
    render(
      <AppShell navbarProps={navbarProps} modeBannerProps={modeBannerProps}>
        <div>화면 본문</div>
      </AppShell>,
    )

    expect(screen.getByRole('link', { name: '본문으로 건너뛰기' }).getAttribute('href')).toBe(
      '#main-content',
    )
    const main = screen.getByText('화면 본문').closest('main')

    expect(main?.id).toBe('main-content')
    expect(main?.className).toContain('mt-16')
    expect(main?.className).toContain('h-[calc(100dvh-4rem)]')
    expect(main?.className).toContain('scroll-mt-16')
    expect(main?.className).not.toContain('pt-16')
  })

  it('데스크톱 사이드바 폭·Navbar offset·본문 여백을 함께 바꾸고 화면 상태를 보존한다', () => {
    render(
      <AppShell navbarProps={navbarProps} modeBannerProps={modeBannerProps}>
        <input aria-label="접기 전후 보존할 화면 상태" defaultValue="draft" />
      </AppShell>,
    )

    const pageState = screen.getByRole('textbox', { name: '접기 전후 보존할 화면 상태' })
    const desktopAside = screen.getByRole('complementary', { name: '데스크톱 주요 메뉴' })
    const content = screen.getByTestId('app-shell-content')
    const page = screen.getByTestId('app-shell-page')

    fireEvent.change(pageState, { target: { value: 'unsaved-change' } })
    expect(desktopAside.className).toContain('w-60')
    expect(content.className).toContain('lg:pl-60')
    expect(page.className).toContain('max-w-[1440px]')
    expect(screen.getByTestId('navbar').getAttribute('data-collapsed')).toBe('false')
    expect(screen.getByTestId('mode-banner').getAttribute('data-collapsed')).toBe('false')

    fireEvent.click(screen.getByRole('button', { name: '사이드바 접기' }))

    expect(desktopAside.className).toContain('w-20')
    expect(content.className).toContain('lg:pl-20')
    expect(page.className).toContain('max-w-[1600px]')
    expect(screen.getByTestId('navbar').getAttribute('data-collapsed')).toBe('true')
    expect(screen.getByTestId('mode-banner').getAttribute('data-collapsed')).toBe('true')
    expect(screen.getByRole('textbox', { name: '접기 전후 보존할 화면 상태' })).toBe(pageState)
    expect((pageState as HTMLInputElement).value).toBe('unsaved-change')

    fireEvent.click(screen.getByRole('button', { name: '사이드바 펼치기' }))

    expect(desktopAside.className).toContain('w-60')
    expect(content.className).toContain('lg:pl-60')
    expect(page.className).toContain('max-w-[1440px]')
    expect(screen.getByTestId('navbar').getAttribute('data-collapsed')).toBe('false')
    expect(screen.getByRole('textbox', { name: '접기 전후 보존할 화면 상태' })).toBe(pageState)
  })
})
