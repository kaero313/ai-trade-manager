import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { getBotStatus } from '../../services/api'

function resolveTickerText(
  latestAction: string | null | undefined,
  isActive: boolean,
  isError: boolean,
  isLoading: boolean,
): string {
  if (isError) {
    return 'AI 엔진 상태 조회 실패...'
  }

  if (typeof latestAction === 'string' && latestAction.trim().length > 0) {
    return latestAction
  }

  if (isLoading) {
    return 'AI 엔진 상태 동기화 중...'
  }

  return isActive ? 'AI 엔진 작업 동기화 중...' : 'AI 엔진 대기 중...'
}

function AiCoreStatus() {
  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 4000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  const isActive = botStatusQuery.data?.running ?? false
  const targetAction = resolveTickerText(
    botStatusQuery.data?.latest_action,
    isActive,
    botStatusQuery.isError,
    botStatusQuery.isLoading,
  )

  const [displayedAction, setDisplayedAction] = useState('')
  const [isTickerVisible, setIsTickerVisible] = useState(false)

  useEffect(() => {
    setDisplayedAction('')
    setIsTickerVisible(false)

    const animationFrameId = window.requestAnimationFrame(() => {
      setIsTickerVisible(true)
    })

    let index = 0
    const intervalId = window.setInterval(() => {
      index += 1
      setDisplayedAction(targetAction.slice(0, index))

      if (index >= targetAction.length) {
        window.clearInterval(intervalId)
      }
    }, 28)

    return () => {
      window.cancelAnimationFrame(animationFrameId)
      window.clearInterval(intervalId)
    }
  }, [targetAction])

  const containerClassName = isActive
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 ring-emerald-100 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20'
    : 'border-rose-200 bg-rose-50 text-rose-700 ring-rose-100 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20'
  const pulseClassName = isActive ? 'animate-pulse bg-sky-400/50' : 'bg-rose-400/30'
  const coreClassName = isActive
    ? 'bg-emerald-400 shadow-[0_0_18px_rgba(74,222,128,0.85)]'
    : 'bg-rose-400 shadow-[0_0_14px_rgba(251,113,133,0.65)]'
  const badgeClassName = isActive
    ? 'bg-white/80 text-emerald-700 dark:bg-gray-900/60 dark:text-emerald-300'
    : 'bg-white/80 text-rose-700 dark:bg-gray-900/60 dark:text-rose-300'
  const badgeText = isActive ? '🟢 Active' : '🔴 Offline'

  return (
    <section
      className={`inline-flex min-w-0 max-w-[240px] items-center gap-2.5 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm ring-1 lg:max-w-[360px] ${containerClassName}`}
    >
      <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
        <span className={`absolute inline-flex h-full w-full rounded-full ${pulseClassName}`} />
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${coreClassName}`} />
      </span>

      <div className="min-w-0 flex-1">
        <p
          aria-live="polite"
          className={`overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[11px] font-medium transition-opacity duration-300 ${isTickerVisible ? 'opacity-100' : 'opacity-40'}`}
        >
          {displayedAction}
          <span className="ml-0.5 inline-block h-3.5 w-px animate-pulse bg-current align-middle opacity-70" />
        </p>
      </div>

      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${badgeClassName}`}>
        {badgeText}
      </span>
    </section>
  )
}

export default AiCoreStatus
