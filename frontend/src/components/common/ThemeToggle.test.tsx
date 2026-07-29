// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState, type ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { ThemeContext, type Theme } from '../../contexts/theme-context'
import ThemeToggle from './ThemeToggle'

function ThemeHarness({ children, initialTheme }: { children: ReactNode; initialTheme: Theme }) {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

describe('ThemeToggle', () => {
  afterEach(() => {
    cleanup()
  })

  it('라이트 테마에서는 접근 가능한 다크 전환 버튼을 제공한다', () => {
    render(
      <ThemeHarness initialTheme="light">
        <ThemeToggle />
      </ThemeHarness>,
    )

    const button = screen.getByRole('button', { name: '다크 테마로 전환' })
    fireEvent.click(button)

    expect(screen.getByRole('button', { name: '라이트 테마로 전환' })).toBeTruthy()
  })

  it('다크 테마에서 라이트 테마로 전환한다', () => {
    render(
      <ThemeHarness initialTheme="dark">
        <ThemeToggle />
      </ThemeHarness>,
    )

    fireEvent.click(screen.getByRole('button', { name: '라이트 테마로 전환' }))

    expect(screen.getByRole('button', { name: '다크 테마로 전환' })).toBeTruthy()
  })
})
