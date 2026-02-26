import { Link } from 'react-router-dom'

function Navbar() {
  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-slate-800 bg-slate-900 text-slate-100 shadow-lg">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          to="/"
          className="text-lg font-semibold tracking-tight transition-colors hover:text-emerald-300"
        >
          AI Trade Manager
        </Link>
        <nav className="flex items-center gap-2 text-sm font-medium sm:gap-4">
          <Link
            to="/"
            className="rounded-md px-3 py-2 text-slate-200 transition-colors hover:bg-slate-800 hover:text-white"
          >
            Dashboard
          </Link>
          <Link
            to="/settings"
            className="rounded-md px-3 py-2 text-slate-200 transition-colors hover:bg-slate-800 hover:text-white"
          >
            Settings
          </Link>
        </nav>
      </div>
    </header>
  )
}

export default Navbar
