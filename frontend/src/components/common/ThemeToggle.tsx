import { Moon, Sun } from 'lucide-react'

import { useTheme } from '../../contexts/useTheme'

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const nextTheme = theme === 'light' ? 'dark' : 'light'
  const label = `${nextTheme === 'dark' ? '다크' : '라이트'} 테마로 전환`

  return (
    <button
      type="button"
      onClick={() => setTheme(nextTheme)}
      aria-label={label}
      title={label}
      className="grid min-h-11 min-w-11 place-items-center rounded-lg border border-border-subtle bg-surface-low text-content-secondary transition-colors hover:bg-surface-high hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
    >
      {theme === 'light' ? (
        <Moon className="h-4.5 w-4.5" aria-hidden="true" />
      ) : (
        <Sun className="h-4.5 w-4.5" aria-hidden="true" />
      )}
    </button>
  )
}

export default ThemeToggle
