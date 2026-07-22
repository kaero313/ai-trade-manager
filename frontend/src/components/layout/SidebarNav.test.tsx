// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SidebarNav from './SidebarNav'

describe('SidebarNav', () => {
  afterEach(() => {
    cleanup()
  })

  it('접힌 메뉴에서도 route 이름·현재 페이지·툴팁과 토글 접근성을 보존한다', () => {
    const onToggleCollapsed = vi.fn()

    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <SidebarNav collapsed onToggleCollapsed={onToggleCollapsed} />
      </MemoryRouter>,
    )

    const portfolioLink = screen.getByRole('link', { name: '포트폴리오' })
    const toggle = screen.getByRole('button', { name: '사이드바 펼치기' })

    expect(portfolioLink.getAttribute('aria-current')).toBe('page')
    expect(portfolioLink.getAttribute('title')).toBe('포트폴리오 · 실제 계좌 자산 현황')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(toggle.getAttribute('aria-controls')).toBe('desktop-primary-navigation')

    fireEvent.click(toggle)
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1)
  })

  it('모바일에서 사용하는 기본 확장형 메뉴에는 데스크톱 접기 버튼을 노출하지 않는다', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <SidebarNav />
      </MemoryRouter>,
    )

    expect(screen.getByText('시장과 봇 운영 현황')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /사이드바/ })).toBeNull()
  })
})
