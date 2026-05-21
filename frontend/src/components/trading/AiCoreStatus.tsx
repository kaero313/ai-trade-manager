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

function AnimatedTicker({ text }: { text: string }) {
  const [displayedAction, setDisplayedAction] = useState('')
  const [isTickerVisible, setIsTickerVisible] = useState(false)

  useEffect(() => {
    let index = 0
    let intervalId: number | undefined

    const animationFrameId = window.requestAnimationFrame(() => {
      setIsTickerVisible(true)
      intervalId = window.setInterval(() => {
        index += 1
        setDisplayedAction(text.slice(0, index))

        if (index >= text.length) {
          if (intervalId !== undefined) {
            window.clearInterval(intervalId)
          }
        }
      }, 28)
    })

    return () => {
      window.cancelAnimationFrame(animationFrameId)
      if (intervalId !== undefined) {
        window.clearInterval(intervalId)
      }
    }
  }, [text])

  return (
    <p
      aria-live="polite"
      className={`overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[11px] font-medium transition-opacity duration-300 ${isTickerVisible ? 'opacity-100' : 'opacity-40'}`}
    >
      {displayedAction}
      <span className="ml-0.5 inline-block h-3.5 w-px animate-pulse bg-current align-middle opacity-70" />
    </p>
  )
}

function AiCoreStatus() {
  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: (query) => (query.state.status === 'error' ? 30000 : 15000),
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
    retry: 1,
  })

  const isActive = botStatusQuery.data?.running ?? false
  const targetAction = resolveTickerText(
    botStatusQuery.data?.latest_action,
    isActive,
    botStatusQuery.isError,
    botStatusQuery.isLoading,
  )

  const containerClassName = isActive
    ? 'border-[#00dbe9]/20 bg-[#00dbe9]/10 text-[#7df4ff]'
    : 'border-[#ffb4ab]/20 bg-[#ffb4ab]/10 text-[#ffb4ab]'
  const pulseClassName = isActive ? 'animate-pulse bg-[#00dbe9]/45' : 'bg-[#ffb4ab]/30'
  const coreClassName = isActive ? 'bg-[#00dbe9]' : 'bg-[#ffb4ab]'
  const badgeClassName = isActive
    ? 'bg-[#00dbe9]/10 text-[#7df4ff]'
    : 'bg-[#ffb4ab]/10 text-[#ffb4ab]'
  const badgeText = isActive ? 'ACTIVE' : 'STOP'

  return (
    <section
      className={`inline-flex min-w-0 max-w-[240px] items-center gap-2.5 rounded-full border px-3 py-2 text-sm font-semibold lg:max-w-[360px] ${containerClassName}`}
    >
      <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
        <span className={`absolute inline-flex h-full w-full rounded-full ${pulseClassName}`} />
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${coreClassName}`} />
      </span>

      <div className="min-w-0 flex-1">
        <AnimatedTicker key={targetAction} text={targetAction} />
      </div>

      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${badgeClassName}`}>
        {badgeText}
      </span>
    </section>
  )
}

export default AiCoreStatus
