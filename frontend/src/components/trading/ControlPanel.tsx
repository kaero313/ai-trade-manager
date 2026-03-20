import { useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useState } from 'react'

import { liquidateAll } from '../../services/api'
import type { BotStatus } from '../../services/api'

type ActionType = 'liquidate' | null

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (error.message) {
      return error.message
    }
  }
  return fallback
}

function ControlPanel() {
  const queryClient = useQueryClient()
  const [activeAction, setActiveAction] = useState<ActionType>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const isSubmitting = activeAction !== null

  const handleLiquidate = async () => {
    const shouldProceed = window.confirm('정말 전량 롤백(시장가 매도)을 실행하시겠습니까?')
    if (!shouldProceed) {
      return
    }

    setActiveAction('liquidate')
    setErrorMessage(null)
    setSuccessMessage(null)

    try {
      await liquidateAll()
      queryClient.setQueryData<BotStatus>(['bot-status'], (previous) => ({
        running: false,
        last_heartbeat: previous?.last_heartbeat ?? null,
        last_error: previous?.last_error ?? null,
      }))
      void queryClient.invalidateQueries({ queryKey: ['bot-status'] })
      setSuccessMessage('전량 롤백 요청을 전송했습니다.')
    } catch (error) {
      setErrorMessage(resolveErrorMessage(error, '전량 롤백 요청에 실패했습니다.'))
    } finally {
      setActiveAction(null)
    }
  }

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">비상 제어</h2>
      </header>

      <section>
        <button
          type="button"
          onClick={handleLiquidate}
          disabled={isSubmitting}
          className="w-full rounded-lg bg-rose-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {activeAction === 'liquidate' ? '처리 중...' : '전량 롤백(시장가 매도)'}
        </button>
      </section>

      {successMessage && (
        <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {successMessage}
        </p>
      )}
      {errorMessage && (
        <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {errorMessage}
        </p>
      )}
    </aside>
  )
}

export default ControlPanel
