import { Menu } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import ThemeToggle from '../common/ThemeToggle'
import MarketSearchBar from '../trading/MarketSearchBar'

export interface NavbarProps {
  totalNetWorth: number
  totalPnl: number
  isPortfolioLoading: boolean
  portfolioError: string | null
  portfolioIsStale: boolean
  portfolioUpdatedAt: string | null
  portfolioSource: 'live' | 'snapshot' | 'empty' | null
  desktopNavigationCollapsed?: boolean
  onOpenNavigation: () => void
}

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

function formatUpdatedAt(value: string | null): string | null {
  if (!value) {
    return null
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }

  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function resolvePortfolioUnavailableLabel(errorCode: string | null): string {
  if (errorCode === 'UPBIT_AUTH_IP_NOT_ALLOWED') {
    return 'IP 미허용'
  }
  if (errorCode === 'UPBIT_AUTH_ERROR') {
    return '인증 오류'
  }
  if (errorCode === 'UPBIT_KEY_MISSING') {
    return '키 없음'
  }
  return '조회 불가'
}

function Navbar({
  totalNetWorth,
  totalPnl,
  isPortfolioLoading,
  portfolioError,
  portfolioIsStale,
  portfolioUpdatedAt,
  portfolioSource,
  desktopNavigationCollapsed = false,
  onOpenNavigation,
}: NavbarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const isPortfolioUnavailable =
    portfolioSource === 'empty' ||
    (!isPortfolioLoading && portfolioSource === null) ||
    (portfolioError !== null && portfolioSource === null)
  const updatedAtLabel = formatUpdatedAt(portfolioUpdatedAt)
  const pnlTextColor = isPortfolioUnavailable
    ? 'text-content-muted'
    : totalPnl >= 0
      ? 'text-market-positive'
      : 'text-market-negative'
  const totalNetWorthLabel = isPortfolioLoading
    ? '불러오는 중'
    : isPortfolioUnavailable
      ? resolvePortfolioUnavailableLabel(portfolioError)
      : formatKrw(totalNetWorth)
  const totalPnlLabel = isPortfolioLoading
    ? '-'
    : isPortfolioUnavailable
      ? '-'
      : formatSignedKrw(totalPnl)
  const portfolioStatusLabel = isPortfolioLoading
    ? '확인 중'
    : isPortfolioUnavailable
      ? 'UNAVAILABLE'
      : portfolioSource === 'snapshot'
        ? 'SNAPSHOT'
        : portfolioIsStale
          ? 'STALE'
          : 'LIVE'
  const portfolioStatusClassName = isPortfolioUnavailable
    ? 'border-status-danger/25 bg-status-danger/10 text-status-danger'
    : portfolioSource === 'snapshot' || portfolioIsStale
      ? 'border-warning/25 bg-warning/10 text-warning'
      : 'border-status-success/25 bg-status-success/10 text-status-success'

  const handleSelectSymbol = (symbol: string) => {
    const nextParams = new URLSearchParams(location.pathname === '/' ? location.search : '')
    nextParams.set('symbol', symbol)
    navigate({ pathname: '/', search: nextParams.toString() })
  }

  return (
    <header
      className={`fixed inset-x-0 top-0 z-40 h-16 border-b border-border-subtle bg-surface-low/92 text-content backdrop-blur-xl transition-[left] duration-200 motion-reduce:transition-none ${
        desktopNavigationCollapsed ? 'lg:left-20' : 'lg:left-60'
      }`}
    >
      <div
        className={`mx-auto grid h-full w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-3 transition-[max-width] duration-200 motion-reduce:transition-none sm:px-6 lg:px-8 ${
          desktopNavigationCollapsed ? 'max-w-[1600px]' : 'max-w-[1440px]'
        }`}
      >
        <button
          type="button"
          onClick={onOpenNavigation}
          aria-label="주요 메뉴 열기"
          className="grid min-h-11 min-w-11 place-items-center rounded-lg text-content-secondary transition-colors hover:bg-surface-high hover:text-content lg:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>

        <div className="hidden min-w-0 max-w-xl sm:block">
          <MarketSearchBar compact onSelectSymbol={handleSelectSymbol} />
        </div>
        <p className="min-w-0 truncate text-sm font-extrabold tracking-tight text-content sm:hidden">
          AI Trade Manager
        </p>

        <div className="flex min-w-0 items-center justify-end gap-2 sm:gap-3">
          <div className="hidden min-w-0 items-center gap-3 border-r border-border-subtle pr-3 md:flex xl:gap-5 xl:pr-5">
            <div className="min-w-0 text-right">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-content-muted">
                총 자산
              </p>
              <p
                className={`truncate text-xs font-extrabold xl:text-sm ${
                  isPortfolioUnavailable ? 'text-content-muted' : 'text-content'
                }`}
              >
                {totalNetWorthLabel}
              </p>
            </div>
            <div className="hidden min-w-0 text-right xl:block">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-content-muted">
                총 수익
              </p>
              <p className={`truncate text-sm font-extrabold ${pnlTextColor}`}>{totalPnlLabel}</p>
            </div>
            {!isPortfolioLoading && (
              <span
                className={`whitespace-nowrap rounded-full border px-2 py-1 text-[11px] font-bold ${portfolioStatusClassName}`}
                title={portfolioError ?? undefined}
              >
                Portfolio {portfolioStatusLabel}
                {(portfolioSource === 'snapshot' || portfolioIsStale) && updatedAtLabel
                  ? ` · ${updatedAtLabel}`
                  : ''}
              </span>
            )}
          </div>

          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

export default Navbar
