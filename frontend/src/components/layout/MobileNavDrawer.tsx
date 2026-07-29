import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from '@headlessui/react'
import { X } from 'lucide-react'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import MarketSearchBar from '../trading/MarketSearchBar'
import SidebarNav from './SidebarNav'

interface MobileNavDrawerProps {
  open: boolean
  onClose: () => void
}

function MobileNavDrawer({ open, onClose }: MobileNavDrawerProps) {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (!open || typeof window.matchMedia !== 'function') {
      return
    }

    const desktopQuery = window.matchMedia('(min-width: 1024px)')
    const closeOnDesktop = () => {
      if (desktopQuery.matches) {
        onClose()
      }
    }
    closeOnDesktop()
    desktopQuery.addEventListener('change', closeOnDesktop)
    return () => desktopQuery.removeEventListener('change', closeOnDesktop)
  }, [onClose, open])

  const handleSelectSymbol = (symbol: string) => {
    const nextParams = new URLSearchParams(location.pathname === '/' ? location.search : '')
    nextParams.set('symbol', symbol)
    navigate({ pathname: '/', search: nextParams.toString() })
    onClose()
  }

  return (
    <Dialog open={open} onClose={onClose} className="relative z-[70]">
      <DialogBackdrop
        transition
        className="fixed inset-0 bg-surface-lowest/75 backdrop-blur-sm transition-opacity duration-200 data-closed:opacity-0 motion-reduce:duration-0"
      />
      <div className="fixed inset-0 flex">
        <DialogPanel
          transition
          className="relative flex h-full w-[min(88vw,320px)] flex-col border-r border-border-subtle bg-surface-low shadow-2xl transition duration-200 ease-out data-closed:-translate-x-full motion-reduce:duration-0"
        >
          <DialogTitle className="sr-only">주요 메뉴</DialogTitle>
          <button
            type="button"
            onClick={onClose}
            aria-label="메뉴 닫기"
            className="absolute right-3 top-2.5 z-10 grid min-h-11 min-w-11 place-items-center rounded-lg text-content-secondary transition-colors hover:bg-surface-high hover:text-content"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
          <div className="min-h-0 flex-1">
            <SidebarNav onNavigate={onClose} />
          </div>
          <div className="shrink-0 border-t border-border-subtle bg-surface-low px-4 py-4">
            <p className="mb-2 text-xs font-bold text-content-secondary">종목 바로가기</p>
            <MarketSearchBar compact onSelectSymbol={handleSelectSymbol} />
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  )
}

export default MobileNavDrawer
