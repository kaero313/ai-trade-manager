import type { ReactNode } from 'react'

import Navbar from './Navbar'

interface LayoutProps {
  children: ReactNode
}

function Layout({ children }: LayoutProps) {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-gray-100 text-gray-900 transition-colors dark:bg-gray-900 dark:text-gray-100">
      <Navbar />
      <main className="mx-auto flex-1 min-h-0 w-full max-w-full overflow-y-auto px-4 pb-10 pt-24 sm:px-6 lg:px-8">
        {children}
      </main>
    </div>
  )
}

export default Layout
