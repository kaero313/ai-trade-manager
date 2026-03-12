import {
  useLayoutEffect,
  useState,
  type ReactNode,
} from 'react'

import { ThemeContext, type Theme } from './theme-context'

const THEME_STORAGE_KEY = 'theme'

function getSystemTheme(): Theme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light'
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getStoredTheme(): Theme | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (storedTheme === 'light' || storedTheme === 'dark') {
      return storedTheme
    }
  } catch {
    return null
  }

  return null
}

function getInitialTheme(): Theme {
  return getStoredTheme() ?? getSystemTheme()
}

interface ThemeProviderProps {
  children: ReactNode
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [theme, setTheme] = useState<Theme>(() => getInitialTheme())

  useLayoutEffect(() => {
    const root = document.documentElement

    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // 저장소 접근이 차단된 환경에서는 DOM 반영만 유지합니다.
    }
  }, [theme])

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}
