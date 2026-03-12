import { useTheme } from '../../contexts/useTheme'

function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  const handleClick = () => {
    if (theme === 'light') {
      setTheme('dark')
      return
    }

    setTheme('light')
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-gray-200 hover:text-slate-900 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-gray-700 dark:hover:text-white"
    >
      {theme === 'light' ? 'Dark Theme' : 'Light Theme'}
    </button>
  )
}

export default ThemeToggle
