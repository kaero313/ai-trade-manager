import { MessageSquare, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'

import ThemeToggle from '../common/ThemeToggle'

interface NavbarProps {
  aiStatus: ReactNode
  totalNetWorth: number
  totalPnl: number
  isPortfolioLoading: boolean
  portfolioError: string | null
}

interface NavItem {
  to: string
  label: string
  end?: boolean
  icon?: LucideIcon
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '대시보드', end: true },
  { to: '/portfolio', label: '📊 포트폴리오' },
  { to: '/chat', label: 'AI 뱅커', icon: MessageSquare },
  { to: '/settings', label: '설정' },
  { to: '/laboratory', label: '연구소/백테스트' },
]

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

function resolveNavLinkClassName({ isActive }: { isActive: boolean }): string {
  return `inline-flex items-center gap-2 whitespace-nowrap rounded-md px-2.5 py-2 text-[13px] transition-colors sm:px-3 sm:text-sm ${
    isActive
      ? 'bg-emerald-500 text-white shadow-sm'
      : 'text-gray-600 hover:bg-gray-200 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
  }`
}

function renderNavLinks() {
  return NAV_ITEMS.map(({ to, label, end, icon: Icon }) => (
    <NavLink key={to} to={to} end={end} className={resolveNavLinkClassName}>
      {Icon ? <Icon className="h-4 w-4" /> : null}
      <span>{label}</span>
    </NavLink>
  ))
}

function Navbar({ aiStatus, totalNetWorth, totalPnl, isPortfolioLoading, portfolioError }: NavbarProps) {
  const hasPortfolioError = portfolioError !== null
  const pnlTextColor = hasPortfolioError
    ? 'text-gray-500 dark:text-gray-400'
    : totalPnl >= 0
      ? 'text-emerald-600 dark:text-emerald-400'
      : 'text-rose-600 dark:text-rose-400'
  const totalNetWorthLabel = isPortfolioLoading ? '...' : hasPortfolioError ? '조회 불가' : formatKrw(totalNetWorth)
  const totalPnlLabel = isPortfolioLoading ? '...' : hasPortfolioError ? '-' : formatSignedKrw(totalPnl)

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-gray-200 bg-white/95 text-gray-900 shadow-sm backdrop-blur dark:border-gray-700 dark:bg-gray-800/95 dark:text-gray-100">
      <div className="mx-auto flex w-full max-w-full flex-col gap-3 px-4 py-3 sm:px-6 lg:grid lg:h-16 lg:grid-cols-[minmax(0,1fr)_auto_auto] lg:items-center lg:gap-4 lg:px-8 lg:py-0">
        <div className="flex min-w-0 items-center justify-between gap-3 lg:hidden">
          <NavLink
            to="/"
            className="shrink-0 text-lg font-semibold tracking-tight transition-colors hover:text-emerald-600 dark:hover:text-emerald-300"
          >
            AI Trade Manager
          </NavLink>

          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0">{aiStatus}</div>
            <ThemeToggle />
          </div>
        </div>

        <nav className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium lg:hidden">
          {renderNavLinks()}
        </nav>

        <div className="hidden min-w-0 items-center gap-3 lg:flex lg:gap-4">
          <NavLink
            to="/"
            className="shrink-0 text-lg font-semibold tracking-tight transition-colors hover:text-emerald-600 dark:hover:text-emerald-300"
          >
            AI Trade Manager
          </NavLink>

          <nav className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium lg:gap-2 xl:gap-3">
            {renderNavLinks()}
          </nav>
        </div>

        <div className="hidden min-w-0 items-center justify-center gap-3 justify-self-center lg:flex lg:gap-4">
          {aiStatus}
          <div className="hidden items-center gap-4 xl:flex">
            <span className="whitespace-nowrap text-xs font-semibold text-gray-600 dark:text-gray-300">
              총 자산:{' '}
              <span className={hasPortfolioError ? 'text-gray-500 dark:text-gray-400' : 'text-gray-900 dark:text-gray-100'}>
                {totalNetWorthLabel}
              </span>
            </span>
            <span className={`whitespace-nowrap text-xs font-semibold ${pnlTextColor}`}>
              총 수익: {totalPnlLabel}
            </span>
          </div>
        </div>

        <div className="hidden justify-self-end lg:block">
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

export default Navbar
