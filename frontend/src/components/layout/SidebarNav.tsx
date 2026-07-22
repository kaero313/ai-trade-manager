import { Activity, PanelLeftClose, PanelLeftOpen, ShieldCheck } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { NAVIGATION_ITEMS, resolveNavigationClassName } from './navigation'

interface SidebarNavProps {
  onNavigate?: () => void
  collapsed?: boolean
  onToggleCollapsed?: () => void
}

function SidebarNav({ onNavigate, collapsed = false, onToggleCollapsed }: SidebarNavProps) {
  return (
    <div className="relative flex h-full flex-col bg-surface-low text-content">
      <div
        className={`flex h-16 shrink-0 items-center border-b border-border-subtle ${
          collapsed ? 'justify-center px-2' : 'gap-3 px-5'
        }`}
      >
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand/12 text-brand" aria-hidden="true">
          <Activity className="h-5 w-5" />
        </span>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-extrabold tracking-tight text-content">AI Trade Manager</p>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-content-muted">
              Operations
            </p>
          </div>
        )}
      </div>

      {onToggleCollapsed && (
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
          aria-expanded={!collapsed}
          aria-controls="desktop-primary-navigation"
          title={collapsed ? '사이드바 펼치기' : '사이드바 접기'}
          className="absolute -right-[22px] top-20 z-10 grid h-11 w-11 place-items-center rounded-full border border-border-subtle bg-surface-low text-content-secondary shadow-lg transition-colors hover:border-brand/35 hover:bg-surface-high hover:text-brand-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring motion-reduce:transition-none"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-5 w-5" aria-hidden="true" />
          ) : (
            <PanelLeftClose className="h-5 w-5" aria-hidden="true" />
          )}
        </button>
      )}

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-5" aria-label="주요 메뉴">
        {NAVIGATION_ITEMS.map(({ to, label, description, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            aria-label={collapsed ? label : undefined}
            title={collapsed ? `${label} · ${description}` : undefined}
            className={(state) => resolveNavigationClassName(state, collapsed)}
          >
            <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
            {!collapsed && (
              <span className="min-w-0">
                <span className="block truncate">{label}</span>
                <span className="block truncate text-[11px] font-medium text-content-muted group-hover:text-content-secondary">
                  {description}
                </span>
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className={`border-t border-border-subtle ${collapsed ? 'p-3' : 'p-4'}`}>
        <div
          title={collapsed ? '관리자 전용 콘솔 · 거래 상태는 상단 안전 배너에서 확인하세요.' : undefined}
          className={`rounded-lg border border-border-subtle bg-surface-lowest/55 ${
            collapsed ? 'grid min-h-11 place-items-center' : 'flex items-start gap-2 px-3 py-2.5'
          }`}
        >
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden="true" />
          {!collapsed && (
            <div className="min-w-0">
              <p className="text-xs font-bold text-content">관리자 전용 콘솔</p>
              <p className="mt-0.5 text-[11px] leading-4 text-content-muted">
                거래 상태는 상단의 조회 전용 배너에서 확인하세요.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default SidebarNav
