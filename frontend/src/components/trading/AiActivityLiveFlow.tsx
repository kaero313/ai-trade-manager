import { useQuery } from '@tanstack/react-query'

import { getBotStatus, type BotStatus } from '../../services/api'

interface FlowItem {
  label: string
  value: string
  tone: 'primary' | 'success' | 'warning' | 'danger' | 'muted'
}

function formatHeartbeat(value: string | null | undefined): string {
  if (!value) {
    return '대기 중'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function resolveLatestAction(status: BotStatus | undefined, isError: boolean, isLoading: boolean): string {
  if (isError) {
    return 'AI 엔진 상태 조회 실패'
  }

  const latestAction = status?.latest_action?.trim()
  if (latestAction) {
    return latestAction
  }

  if (isLoading) {
    return 'AI 엔진 상태 동기화 중'
  }

  return status?.running ? 'AI 엔진 작업 대기 중' : 'AI 엔진 대기 중'
}

function buildFlowItems(status: BotStatus | undefined, isError: boolean, isLoading: boolean): FlowItem[] {
  const isActive = status?.running ?? false
  const latestAction = resolveLatestAction(status, isError, isLoading)
  const heartbeat = formatHeartbeat(status?.last_heartbeat)

  return [
    {
      label: 'LATEST',
      value: latestAction,
      tone: isError ? 'danger' : isActive ? 'primary' : 'warning',
    },
    {
      label: 'HEARTBEAT',
      value: heartbeat,
      tone: status?.last_heartbeat ? 'muted' : 'warning',
    },
    {
      label: 'SYNC',
      value: isError ? '30s retry' : '15s refresh',
      tone: isError ? 'warning' : 'muted',
    },
  ]
}

function resolveToneClassName(tone: FlowItem['tone']): string {
  switch (tone) {
    case 'success':
      return 'text-[#77e2a8]'
    case 'warning':
      return 'text-[#ffe179]'
    case 'danger':
      return 'text-[#ffb4ab]'
    case 'muted':
      return 'text-[#b9cacb]'
    case 'primary':
    default:
      return 'text-[#7df4ff]'
  }
}

function AiActivityLiveFlow() {
  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: (query) => (query.state.status === 'error' ? 30000 : 15000),
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
    retry: 1,
  })

  const flowItems = buildFlowItems(
    botStatusQuery.data,
    botStatusQuery.isError,
    botStatusQuery.isLoading,
  )
  return (
    <section
      className="relative h-9 overflow-hidden rounded-lg border border-[#29363a]/80 bg-[#0a0e14]"
      aria-label="AI 활동 상태"
    >
      <div className="absolute inset-y-0 left-0 z-10 flex w-32 items-center border-r border-[#29363a]/80 bg-[#262a31] px-3">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-[#7df4ff]">
          AI ACTIVITY
        </span>
      </div>

      <div className="quantum-ticker-scroll flex h-full w-max items-center font-mono text-xs">
        {[0, 1, 2, 3].map((copyIndex) => (
          <div
            key={copyIndex}
            aria-hidden={copyIndex > 0 || undefined}
            className="flex min-w-max shrink-0 items-center gap-10 pl-40 pr-10"
          >
            {flowItems.map((item) => (
              <div key={item.label} className="flex min-w-max items-center gap-2">
                <span className="uppercase tracking-[0.12em] text-[#849495]">{item.label}</span>
                <span className={resolveToneClassName(item.tone)}>{item.value}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}

export default AiActivityLiveFlow
