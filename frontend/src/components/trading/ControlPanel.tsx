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
        latest_action: 'AI 엔진 대기 중...',
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
    <aside className="quantum-card rounded-xl p-5">
      <header className="mb-4">
        <h2 className="text-lg font-bold text-[#dfe2eb]">비상 제어</h2>
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
        <p className="mt-4 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#77e2a8]">
          {successMessage}
        </p>
      )}
      {errorMessage && (
        <p className="mt-4 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold text-[#ffb4ab]">
          {errorMessage}
        </p>
      )}
    </aside>
  )
}

export default ControlPanel
