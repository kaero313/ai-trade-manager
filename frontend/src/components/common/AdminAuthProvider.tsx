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
  const [reason, setReason] = useState('관리 작업')
  const [token, setToken] = useState('')
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
    pendingRequestRef.current = null
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedToken = token.trim()
    if (!normalizedToken || pendingRequestRef.current === null) {
      return
    }

    storeAdminToken(normalizedToken)
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
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <form
            onSubmit={handleSubmit}
            className="w-full max-w-md rounded-xl border border-[#00dbe9]/20 bg-[#10141a] p-5 shadow-[0_0_24px_rgba(0,219,233,0.12)]"
          >
            <div className="mb-4">
              <p className="text-xs font-bold uppercase tracking-[0.22em] text-[#00dbe9]">
                Admin Authorization
              </p>
              <h2 className="mt-2 text-xl font-bold text-[#dfe2eb]">운영 관리 토큰</h2>
              <p className="mt-2 text-sm leading-6 text-[#b9cacb]">
                {reason} 작업은 관리 API 보호 대상입니다. `.env.local`의 ADMIN_API_TOKEN을 입력해 주세요.
              </p>
            </div>

            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                Token
              </span>
              <input
                type="password"
                value={token}
                autoFocus
                onChange={(event) => setToken(event.target.value)}
                className="w-full rounded-lg border border-[#3b494b] bg-[#0a0e14] px-3 py-2.5 text-sm font-semibold text-[#dfe2eb] outline-none transition focus:border-[#00dbe9]/70 focus:ring-2 focus:ring-[#00dbe9]/20"
                placeholder="ADMIN_API_TOKEN"
              />
            </label>

            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={handleCancel}
                className="rounded-lg border border-[#3b494b]/70 px-4 py-2 text-sm font-bold text-[#b9cacb] transition hover:border-[#849495]"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={!token.trim()}
                className="rounded-lg bg-[#00dbe9] px-4 py-2 text-sm font-bold text-[#00363a] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                토큰 적용
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}

export default AdminAuthProvider
