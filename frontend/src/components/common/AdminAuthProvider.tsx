import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from '@headlessui/react'
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react'

import {
  ADMIN_TOKEN_REQUIRED_EVENT,
  storeAdminToken,
  type AdminTokenRequestDetail,
} from '../../services/api'

interface AdminAuthProviderProps {
  children: ReactNode
}

function AdminAuthProvider({ children }: AdminAuthProviderProps) {
  const pendingRequestRef = useRef<AdminTokenRequestDetail | null>(null)
  const tokenInputRef = useRef<HTMLInputElement | null>(null)
  const [reason, setReason] = useState('관리 작업')
  const [token, setToken] = useState('')
  const [persistent, setPersistent] = useState(true)
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const handleTokenRequired = (event: Event) => {
      const detail = (event as CustomEvent<AdminTokenRequestDetail>).detail
      if (!detail) {
        return
      }

      if (pendingRequestRef.current !== null) {
        detail.reject(new Error('이미 관리 토큰 입력이 진행 중입니다.'))
        return
      }

      pendingRequestRef.current = detail
      setReason(detail.reason || '관리 작업')
      setPersistent(detail.persistent)
      setToken('')
      setIsOpen(true)
    }

    window.addEventListener(ADMIN_TOKEN_REQUIRED_EVENT, handleTokenRequired)
    return () => {
      window.removeEventListener(ADMIN_TOKEN_REQUIRED_EVENT, handleTokenRequired)
    }
  }, [])

  const closeModal = () => {
    setIsOpen(false)
    setToken('')
    setReason('관리 작업')
    setPersistent(true)
    pendingRequestRef.current = null
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedToken = token.trim()
    if (!normalizedToken || pendingRequestRef.current === null) {
      return
    }

    if (pendingRequestRef.current.persistent) {
      storeAdminToken(normalizedToken)
    }
    pendingRequestRef.current.resolve(normalizedToken)
    closeModal()
  }

  const handleCancel = () => {
    pendingRequestRef.current?.reject(new Error('관리 토큰 입력이 취소되었습니다.'))
    closeModal()
  }

  return (
    <>
      {children}
      <Dialog
        open={isOpen}
        onClose={handleCancel}
        initialFocus={tokenInputRef}
        className="relative z-[100]"
      >
        <DialogBackdrop className="fixed inset-0 bg-black/70 backdrop-blur-sm" />
        <div className="fixed inset-0 flex items-center justify-center overflow-y-auto px-4 py-8">
          <DialogPanel
            as="form"
            onSubmit={handleSubmit}
            className="w-full max-w-md rounded-xl border border-brand/20 bg-surface p-5 shadow-xl"
          >
            <div className="mb-4">
              <p className="text-xs font-bold uppercase tracking-[0.22em] text-brand">
                Admin Authorization
              </p>
              <DialogTitle className="mt-2 text-xl font-bold text-content">
                운영 관리 토큰
              </DialogTitle>
              <p className="mt-2 text-sm leading-6 text-content-secondary">
                {reason} 작업은 관리 API 보호 대상입니다. `.env.local`의 ADMIN_API_TOKEN을 입력해 주세요.
              </p>
              {!persistent && (
                <p className="mt-2 text-xs font-semibold leading-5 text-warning">
                  이 토큰은 현재 고위험 작업에만 일회성으로 사용되며 브라우저에 저장하지 않습니다.
                </p>
              )}
            </div>

            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-[0.16em] text-content-muted">
                Token
              </span>
              <input
                type="password"
                ref={tokenInputRef}
                value={token}
                onChange={(event) => setToken(event.target.value)}
                className="min-h-11 w-full rounded-lg border border-border-strong bg-surface-lowest px-3 py-2.5 text-sm font-semibold text-content outline-none transition focus:border-brand/70 focus:ring-2 focus:ring-brand/20"
                placeholder="ADMIN_API_TOKEN"
              />
            </label>

            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={handleCancel}
                className="min-h-11 rounded-lg border border-border-strong px-4 py-2 text-sm font-bold text-content-secondary transition hover:border-content-muted"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={!token.trim()}
                className="min-h-11 rounded-lg bg-brand px-4 py-2 text-sm font-bold text-surface-lowest transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                토큰 적용
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>
    </>
  )
}

export default AdminAuthProvider
