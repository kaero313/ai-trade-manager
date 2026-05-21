import { NavLink, useLocation, useNavigate } from 'react-router-dom'

import ThemeToggle from '../common/ThemeToggle'
import MarketSearchBar from '../trading/MarketSearchBar'

interface NavbarProps {
  totalNetWorth: number
  totalPnl: number
  isPortfolioLoading: boolean
  portfolioError: string | null
  portfolioIsStale: boolean
  portfolioUpdatedAt: string | null
  portfolioSource: 'live' | 'snapshot' | 'empty' | null
}

interface NavItem {
  to: string
  label: string
  end?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '대시보드', end: true },
  { to: '/portfolio', label: '포트폴리오' },
  { to: '/chat', label: 'AI 뱅커' },
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

function resolveNavLinkClassName({ isActive }: { isActive: boolean }): string {
  return `inline-flex items-center gap-2 whitespace-nowrap rounded-md px-2.5 py-2 text-[13px] font-semibold transition-colors sm:px-3 sm:text-sm ${
    isActive
      ? 'bg-[#00363a]/70 text-[#7df4ff]'
      : 'text-[#b9cacb] hover:bg-[#262a31] hover:text-[#dfe2eb]'
  }`
}

function renderNavLinks() {
  return NAV_ITEMS.map(({ to, label, end }) => {
    const visibleLabel = to === '/laboratory' ? '정책 검증' : label

    return (
      <NavLink key={to} to={to} end={end} className={resolveNavLinkClassName}>
        <span>{visibleLabel}</span>
      </NavLink>
    )
  })
}

function Navbar({
  totalNetWorth,
  totalPnl,
  isPortfolioLoading,
  portfolioError,
  portfolioIsStale,
  portfolioUpdatedAt,
  portfolioSource,
}: NavbarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const isPortfolioUnavailable =
    portfolioSource === 'empty' || (portfolioError !== null && portfolioSource === null)
  const updatedAtLabel = formatUpdatedAt(portfolioUpdatedAt)
  const pnlTextColor = isPortfolioUnavailable
    ? 'text-[#849495]'
    : totalPnl >= 0
      ? 'text-[#77e2a8]'
      : 'text-[#ffb4ab]'
  const totalNetWorthLabel = isPortfolioLoading
    ? '...'
    : isPortfolioUnavailable
      ? resolvePortfolioUnavailableLabel(portfolioError)
      : formatKrw(totalNetWorth)
  const totalPnlLabel = isPortfolioLoading
    ? '...'
    : isPortfolioUnavailable
      ? '-'
      : formatSignedKrw(totalPnl)
  const handleSelectSymbol = (symbol: string) => {
    const nextParams = new URLSearchParams(location.pathname === '/' ? location.search : '')
    nextParams.set('symbol', symbol)
    navigate({
      pathname: '/',
      search: nextParams.toString(),
    })
  }

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-[#29363a]/80 bg-[#181c22]/90 text-[#dfe2eb] backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-full flex-col gap-3 px-4 py-3 sm:px-6 lg:grid lg:h-16 lg:grid-cols-[minmax(0,1fr)_minmax(220px,320px)_auto_auto] lg:items-center lg:gap-4 lg:px-8 lg:py-0">
        <div className="flex min-w-0 items-center justify-between gap-3 lg:hidden">
          <NavLink
            to="/"
            className="shrink-0 text-lg font-extrabold tracking-tight text-[#7df4ff] transition-colors hover:text-[#00dbe9]"
          >
            AI Trade Manager
          </NavLink>

          <ThemeToggle />
        </div>

        <nav className="quantum-nav-scroll flex min-w-0 flex-nowrap items-center gap-2 overflow-x-auto text-sm font-medium lg:hidden">
          {renderNavLinks()}
        </nav>

        <div className="hidden min-w-0 items-center gap-3 lg:flex lg:gap-4">
          <NavLink
            to="/"
            className="shrink-0 text-lg font-extrabold tracking-tight text-[#7df4ff] transition-colors hover:text-[#00dbe9]"
          >
            AI Trade Manager
          </NavLink>

          <nav className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium lg:gap-2 xl:gap-3">
            {renderNavLinks()}
          </nav>
        </div>

        <div className="hidden min-w-0 justify-self-stretch lg:block">
          <MarketSearchBar compact onSelectSymbol={handleSelectSymbol} />
        </div>

        <div className="hidden min-w-0 items-center justify-center gap-4 justify-self-center xl:flex">
            <span className="whitespace-nowrap text-xs font-semibold text-[#b9cacb]">
              총 자산:{' '}
              <span className={isPortfolioUnavailable ? 'text-[#849495]' : 'text-[#dfe2eb]'}>
                {totalNetWorthLabel}
              </span>
            </span>
            <span className={`whitespace-nowrap text-xs font-semibold ${pnlTextColor}`}>
              총 수익: {totalPnlLabel}
            </span>
            {portfolioIsStale && !isPortfolioUnavailable && (
              <span
                className="whitespace-nowrap rounded-full bg-[#ffe179]/10 px-2 py-0.5 text-[11px] font-semibold text-[#ffe179]"
                title={portfolioError ?? undefined}
              >
                지연{updatedAtLabel ? ` · ${updatedAtLabel}` : ''}
              </span>
            )}
        </div>

        <div className="hidden justify-self-end lg:block">
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

export default Navbar
