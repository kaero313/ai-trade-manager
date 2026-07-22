import { useState, type ReactNode } from 'react'

import ModeBanner, { type ModeBannerProps } from './ModeBanner'
import MobileNavDrawer from './MobileNavDrawer'
import Navbar, { type NavbarProps } from './Navbar'
import SidebarNav from './SidebarNav'

interface AppShellProps {
  children: ReactNode
  navbarProps: Omit<NavbarProps, 'desktopNavigationCollapsed' | 'onOpenNavigation'>
  modeBannerProps: Omit<ModeBannerProps, 'desktopNavigationCollapsed'>
}

function AppShell({ children, navbarProps, modeBannerProps }: AppShellProps) {
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)
  const [desktopNavigationCollapsed, setDesktopNavigationCollapsed] = useState(false)

  return (
    <div className="h-dvh overflow-hidden bg-canvas text-content">
      <a
        href="#main-content"
        className="fixed left-3 top-3 z-[100] -translate-y-20 rounded-md bg-brand px-3 py-2 text-sm font-bold text-surface-lowest transition-transform focus:translate-y-0"
      >
        본문으로 건너뛰기
      </a>

      <aside
        id="desktop-primary-navigation"
        aria-label="데스크톱 주요 메뉴"
        className={`fixed inset-y-0 left-0 z-50 hidden border-r border-border-subtle transition-[width] duration-200 motion-reduce:transition-none lg:block ${
          desktopNavigationCollapsed ? 'w-20' : 'w-60'
        }`}
      >
        <SidebarNav
          collapsed={desktopNavigationCollapsed}
          onToggleCollapsed={() => setDesktopNavigationCollapsed((collapsed) => !collapsed)}
        />
      </aside>

      <MobileNavDrawer open={mobileNavigationOpen} onClose={() => setMobileNavigationOpen(false)} />

      <div
        data-testid="app-shell-content"
        className={`h-full transition-[padding-left] duration-200 motion-reduce:transition-none ${
          desktopNavigationCollapsed ? 'lg:pl-20' : 'lg:pl-60'
        }`}
      >
        <Navbar
          {...navbarProps}
          desktopNavigationCollapsed={desktopNavigationCollapsed}
          onOpenNavigation={() => setMobileNavigationOpen(true)}
        />
        <main
          id="main-content"
          tabIndex={-1}
          className="mt-16 h-[calc(100dvh-4rem)] scroll-mt-16 overflow-y-auto"
        >
          <ModeBanner
            {...modeBannerProps}
            desktopNavigationCollapsed={desktopNavigationCollapsed}
          />
          <div
            data-testid="app-shell-page"
            className={`mx-auto w-full px-4 pb-10 pt-5 transition-[max-width] duration-200 motion-reduce:transition-none sm:px-6 lg:px-8 lg:pb-12 lg:pt-6 ${
              desktopNavigationCollapsed ? 'max-w-[1600px]' : 'max-w-[1440px]'
            }`}
          >
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}

export default AppShell
