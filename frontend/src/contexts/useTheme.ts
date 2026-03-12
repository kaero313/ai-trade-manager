import { useContext } from 'react'

import { ThemeContext } from './theme-context'

export function useTheme() {
  const context = useContext(ThemeContext)

  if (!context) {
    throw new Error('useTheme은 ThemeProvider 내부에서만 사용할 수 있습니다.')
  }

  return context
}
