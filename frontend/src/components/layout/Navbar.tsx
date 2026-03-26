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

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

function resolveNavLinkClassName({ isActive }: { isActive: boolean }): string {
  return `whitespace-nowrap rounded-md px-3 py-2 transition-colors ${
    isActive
      ? 'bg-emerald-500 text-white shadow-sm'
      : 'text-gray-600 hover:bg-gray-200 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
  }`
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
      <div className="mx-auto grid h-16 w-full max-w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:px-8">
        <div className="flex min-w-0 items-center gap-3 lg:gap-4">
          <NavLink
            to="/"
            className="shrink-0 text-lg font-semibold tracking-tight transition-colors hover:text-emerald-600 dark:hover:text-emerald-300"
          >
            AI Trade Manager
          </NavLink>
          <nav className="flex min-w-0 items-center gap-2 overflow-x-auto text-sm font-medium sm:gap-3 lg:gap-4">
            <NavLink to="/" end className={resolveNavLinkClassName}>
              대시보드
            </NavLink>
            <NavLink to="/settings" className={resolveNavLinkClassName}>
              시스템 설정
            </NavLink>
            <NavLink to="/laboratory" className={resolveNavLinkClassName}>
              연구소/백테스트(실험)
            </NavLink>
          </nav>
        </div>

        <div className="flex min-w-0 items-center justify-center gap-3 justify-self-center lg:gap-4">
          {aiStatus}
          <div className="hidden items-center gap-4 lg:flex">
            <span className="whitespace-nowrap text-xs font-semibold text-gray-600 dark:text-gray-300">
              총 자산:{' '}
              <span className={hasPortfolioError ? 'text-gray-500 dark:text-gray-400' : 'text-gray-900 dark:text-gray-100'}>
                {totalNetWorthLabel}
              </span>
            </span>
            <span className={`whitespace-nowrap text-xs font-semibold ${pnlTextColor}`}>
              총 손익: {totalPnlLabel}
            </span>
          </div>
        </div>

        <div className="justify-self-end">
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

export default Navbar
