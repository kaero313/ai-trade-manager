import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import BotConfigForm from './BotConfigForm'
import { getBotStatus, startBot, stopBot } from '../../services/api'

type ActionType = 'start' | 'stop' | null
type NoticeType = 'success' | 'error'

interface NoticeState {
  message: string
  type: NoticeType
}

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

function BotControlPanel() {
  const queryClient = useQueryClient()
  const [activeAction, setActiveAction] = useState<ActionType>(null)
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false)
  const [notice, setNotice] = useState<NoticeState | null>(null)

  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  useEffect(() => {
    if (notice === null) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setNotice(null)
    }, 3000)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [notice])

  const isLoading = botStatusQuery.isLoading
  const isError = botStatusQuery.isError
  const isActive = botStatusQuery.data?.running ?? false
  const isSubmitting = activeAction !== null
  const badgeLabel = isError ? 'Error' : isLoading ? '확인 중' : isActive ? 'Active' : 'Inactive'
  const badgeClassName = isError
    ? 'border border-rose-200 bg-rose-100 text-rose-700'
    : isActive
      ? 'border border-emerald-200 bg-emerald-100 text-emerald-700'
      : 'border border-slate-300 bg-slate-200 text-slate-700'
  const description = isError
    ? '봇 상태를 확인하지 못했습니다.'
    : isLoading
      ? '봇 상태를 확인하고 있습니다.'
      : isActive
        ? '트레이딩 봇이 현재 가동 중입니다.'
        : '트레이딩 봇이 현재 정지 상태입니다.'

  const handleStart = async () => {
    setActiveAction('start')
    setNotice(null)

    try {
      const nextStatus = await startBot()
      queryClient.setQueryData(['bot-status'], nextStatus)
      void queryClient.invalidateQueries({ queryKey: ['bot-status'] })
      setNotice({ message: '봇 가동 요청을 전송했습니다.', type: 'success' })
    } catch (error) {
      setNotice({ message: resolveErrorMessage(error, '봇 가동 요청에 실패했습니다.'), type: 'error' })
    } finally {
      setActiveAction(null)
    }
  }

  const handleStop = async () => {
    setActiveAction('stop')
    setNotice(null)

    try {
      const nextStatus = await stopBot()
      queryClient.setQueryData(['bot-status'], nextStatus)
      void queryClient.invalidateQueries({ queryKey: ['bot-status'] })
      setNotice({ message: '봇 정지 요청을 전송했습니다.', type: 'success' })
    } catch (error) {
      setNotice({ message: resolveErrorMessage(error, '봇 정지 요청에 실패했습니다.'), type: 'error' })
    } finally {
      setActiveAction(null)
    }
  }

  const handleConfigSaveSuccess = (message: string) => {
    setNotice({ message, type: 'success' })
    setIsConfigModalOpen(false)
  }

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Bot Status</h2>
          <p className="mt-1 text-sm text-slate-500">5초 주기로 실시간 상태를 자동 갱신합니다.</p>
        </div>
        <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${badgeClassName}`}>
          {badgeLabel}
        </span>
      </header>

      <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
        <span className={`h-2.5 w-2.5 rounded-full ${isError ? 'bg-rose-500' : isActive ? 'bg-emerald-500' : 'bg-slate-400'}`} />
        <p>{description}</p>
      </div>

      <section className="mt-5 border-t border-slate-200 pt-5">
        <p className="mb-2 text-sm font-medium text-slate-700">봇 원격 제어</p>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={handleStart}
            disabled={isSubmitting || isLoading || isActive}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              isActive
                ? 'cursor-not-allowed bg-emerald-100 text-emerald-700'
                : 'bg-emerald-600 text-white hover:bg-emerald-500'
            } disabled:opacity-70`}
          >
            {activeAction === 'start' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>{activeAction === 'start' ? '가동 중...' : '봇 가동(Start)'}</span>
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={isSubmitting || isLoading || !isActive}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              !isActive
                ? 'cursor-not-allowed bg-slate-200 text-slate-700'
                : 'bg-slate-900 text-white hover:bg-slate-700'
            } disabled:opacity-70`}
          >
            {activeAction === 'stop' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>{activeAction === 'stop' ? '정지 중...' : '봇 정지(Stop)'}</span>
          </button>
        </div>
        <button
          type="button"
          onClick={() => setIsConfigModalOpen(true)}
          className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
        >
          설정()
        </button>
      </section>

      {notice && (
        <p
          className={`mt-4 rounded-lg px-3 py-2 text-xs ${
            notice.type === 'success'
              ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border border-rose-200 bg-rose-50 text-rose-700'
          }`}
        >
          {notice.message}
        </p>
      )}

      {isConfigModalOpen && (
        <BotConfigForm
          isOpen={isConfigModalOpen}
          onClose={() => setIsConfigModalOpen(false)}
          onSaveSuccess={handleConfigSaveSuccess}
        />
      )}
    </aside>
  )
}

export default BotControlPanel
