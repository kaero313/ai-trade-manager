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
      className="rounded-md bg-[#262a31] px-3 py-2 text-sm font-semibold text-[#b9cacb] transition-colors hover:bg-[#31353c] hover:text-[#7df4ff]"
    >
      {theme === 'light' ? 'Dark' : 'Light'}
    </button>
  )
}

export default ThemeToggle
