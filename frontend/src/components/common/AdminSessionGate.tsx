import { isAxiosError } from 'axios'
import { Loader2, ShieldAlert } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'

import { ADMIN_SESSION_INVALIDATED_EVENT, ensureAdminSession } from '../../services/api'

interface AdminSessionGateProps {
  children: ReactNode
}

type SessionGateState = 'checking' | 'authenticated' | 'locked'

function resolveLockMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const status = error.response?.status
    if (status === 401 || status === 403) {
      return '관리자 토큰이 올바르지 않습니다. 토큰을 확인한 뒤 다시 인증해 주세요.'
    }
    if (status === 503) {
      return '관리자 인증 서비스를 사용할 수 없습니다. 서버 설정을 확인한 뒤 다시 시도해 주세요.'
    }
    if (!error.response) {
      return '관리자 인증 서버에 연결할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.'
    }
  }

  if (error instanceof Error && error.message.includes('취소')) {
    return '관리자 인증이 취소되었습니다. 관리 화면을 사용하려면 다시 인증해 주세요.'
  }

  return '관리자 인증을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.'
}

function AdminSessionGate({ children }: AdminSessionGateProps) {
  const [state, setState] = useState<SessionGateState>('checking')
  const [lockMessage, setLockMessage] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const handleSessionInvalidated = () => {
      setLockMessage('관리자 세션이 만료되었거나 거부되었습니다. 다시 인증해 주세요.')
      setState('locked')
    }

    window.addEventListener(ADMIN_SESSION_INVALIDATED_EVENT, handleSessionInvalidated)
    return () => {
      window.removeEventListener(ADMIN_SESSION_INVALIDATED_EVENT, handleSessionInvalidated)
    }
  }, [])

  useEffect(() => {
    let isActive = true

    const timeoutId = window.setTimeout(() => {
      void ensureAdminSession()
        .then(() => {
          if (isActive) {
            setState('authenticated')
          }
        })
        .catch((error: unknown) => {
          if (isActive) {
            setLockMessage(resolveLockMessage(error))
            setState('locked')
          }
        })
    }, 0)

    return () => {
      isActive = false
      window.clearTimeout(timeoutId)
    }
  }, [attempt])

  if (state === 'authenticated') {
    return children
  }

  if (state === 'checking') {
    return (
      <div
        role="status"
        className="flex min-h-screen flex-col items-center justify-center gap-3 bg-canvas px-4 text-center text-content-secondary"
      >
        <Loader2 className="h-7 w-7 animate-spin text-brand" aria-hidden="true" />
        <p className="text-sm font-semibold">관리자 세션을 확인하고 있습니다.</p>
      </div>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 text-content">
      <section
        role="alert"
        className="w-full max-w-md rounded-xl border border-status-danger/25 bg-surface p-6 shadow-xl"
      >
        <ShieldAlert className="h-8 w-8 text-status-danger" aria-hidden="true" />
        <h1 className="mt-4 text-xl font-bold">관리자 인증이 필요합니다</h1>
        <p className="mt-3 text-sm leading-6 text-content-secondary">{lockMessage}</p>
        <button
          type="button"
          onClick={() => {
            setState('checking')
            setLockMessage('')
            setAttempt((current) => current + 1)
          }}
          className="mt-5 min-h-11 w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-bold text-surface-lowest transition hover:brightness-110"
        >
          다시 인증
        </button>
      </section>
    </main>
  )
}

export default AdminSessionGate
