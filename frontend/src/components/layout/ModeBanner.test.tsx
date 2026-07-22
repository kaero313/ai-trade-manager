// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import ModeBanner from './ModeBanner'

describe('ModeBanner', () => {
  afterEach(() => {
    cleanup()
  })

  it('고정 Navbar 아래에서 안전 상태를 계속 노출한다', () => {
    const { rerender } = render(
      <ModeBanner
        runtimeStatus="STOPPED"
        tradingMode="paper"
        orderGate="BLOCK_ALL"
        rolloutEnabled={false}
      />,
    )

    const banner = screen.getByRole('region', { name: '거래 안전 상태' })

    expect(banner.className).toContain('sticky')
    expect(banner.className).toContain('top-0')
    expect(banner.className).not.toContain('top-16')
    expect(banner.className).not.toContain('fixed')
    expect(banner.textContent).toContain('PAPER 모의투자 모드')
    expect(banner.textContent).toContain('주문은 실제 자산에 영향을 주지 않습니다.')
    expect(banner.textContent).toContain('RolloutOFF')
    expect(screen.queryByText('Trading Mode')).toBeNull()
    expect(banner.firstElementChild?.className).toContain('max-w-[1440px]')

    rerender(
      <ModeBanner
        runtimeStatus="STOPPED"
        tradingMode="paper"
        orderGate="BLOCK_ALL"
        rolloutEnabled={false}
        desktopNavigationCollapsed
      />,
    )

    expect(banner.firstElementChild?.className).toContain('max-w-[1600px]')
  })
})
