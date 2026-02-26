import { isAxiosError } from 'axios'
import { useState } from 'react'

import { liquidateAll, startBot, stopBot } from '../../services/botService'
import type { BotStatus } from '../../services/botService'

interface ControlPanelProps {
  isRunning: boolean
  onStatusChange: (nextStatus: BotStatus) => void
}

type ActionType = 'start' | 'stop' | 'liquidate' | null

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

function ControlPanel({ isRunning, onStatusChange }: ControlPanelProps) {
  const [activeAction, setActiveAction] = useState<ActionType>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const isSubmitting = activeAction !== null

  const handleStart = async () => {
    setActiveAction('start')
    setErrorMessage(null)
    setSuccessMessage(null)

    try {
      const nextStatus = await startBot()
      onStatusChange(nextStatus)
      setSuccessMessage('봇 가동 명령을 전송했습니다.')
    } catch (error) {
      setErrorMessage(resolveErrorMessage(error, '봇 가동 요청에 실패했습니다.'))
    } finally {
      setActiveAction(null)
    }
  }

  const handleStop = async () => {
    setActiveAction('stop')
    setErrorMessage(null)
    setSuccessMessage(null)

    try {
      const nextStatus = await stopBot()
      onStatusChange(nextStatus)
      setSuccessMessage('봇 정지 명령을 전송했습니다.')
    } catch (error) {
      setErrorMessage(resolveErrorMessage(error, '봇 정지 요청에 실패했습니다.'))
    } finally {
      setActiveAction(null)
    }
  }

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
      setSuccessMessage('전량 롤백 요청을 전송했습니다.')
    } catch (error) {
      setErrorMessage(resolveErrorMessage(error, '전량 롤백 요청에 실패했습니다.'))
    } finally {
      setActiveAction(null)
    }
  }

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Control Panel</h2>
        <p className="mt-1 text-sm text-slate-500">봇 제어 및 비상 조치 패널</p>
      </header>

      <section>
        <p className="mb-2 text-sm font-medium text-slate-700">봇 상태 변경</p>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={handleStart}
            disabled={isSubmitting || isRunning}
            className={`rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              isRunning
                ? 'cursor-not-allowed bg-emerald-100 text-emerald-700'
                : 'bg-emerald-600 text-white hover:bg-emerald-500'
            } disabled:opacity-70`}
          >
            {activeAction === 'start' ? '처리 중...' : '봇 가동(Start)'}
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={isSubmitting || !isRunning}
            className={`rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              !isRunning
                ? 'cursor-not-allowed bg-slate-200 text-slate-700'
                : 'bg-slate-900 text-white hover:bg-slate-700'
            } disabled:opacity-70`}
          >
            {activeAction === 'stop' ? '처리 중...' : '봇 정지(Stop)'}
          </button>
        </div>
      </section>

      <section className="mt-5 border-t border-slate-200 pt-5">
        <p className="mb-2 text-sm font-medium text-slate-700">비상 제어</p>
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
