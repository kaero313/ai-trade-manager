import { Link } from 'react-router-dom'

import ThemeToggle from '../common/ThemeToggle'

function Navbar() {
  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-slate-200 bg-white/95 text-slate-900 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-900/95 dark:text-slate-100">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          to="/"
          className="text-lg font-semibold tracking-tight transition-colors hover:text-emerald-600 dark:hover:text-emerald-300"
        >
          AI Trade Manager
        </Link>
        <nav className="flex items-center gap-2 text-sm font-medium sm:gap-4">
          <Link
            to="/"
            className="rounded-md px-3 py-2 text-slate-600 transition-colors hover:bg-gray-200 hover:text-slate-900 dark:text-slate-200 dark:hover:bg-gray-700 dark:hover:text-white"
          >
            Dashboard
          </Link>
          <Link
            to="/laboratory"
            className="rounded-md px-3 py-2 text-slate-600 transition-colors hover:bg-gray-200 hover:text-slate-900 dark:text-slate-200 dark:hover:bg-gray-700 dark:hover:text-white"
          >
            진단/백테스트(🧪)
          </Link>
          <Link
            to="/settings"
            className="rounded-md px-3 py-2 text-slate-600 transition-colors hover:bg-gray-200 hover:text-slate-900 dark:text-slate-200 dark:hover:bg-gray-700 dark:hover:text-white"
          >
            Settings
          </Link>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  )
}

export default Navbar
