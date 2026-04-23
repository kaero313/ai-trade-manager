import { AlertTriangle, Check, Loader2, MessageSquare, Plus, SendHorizontal } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'

import { streamChatMessage } from '../../services/api'

interface PortfolioMiniChatProps {
  sessionId: string | null
  onCreateSession: () => Promise<string | null>
}

interface NoticeState {
  type: 'error' | 'info'
  message: string
}

interface ChatRenderMessageItem {
  kind: 'message'
  key: string
  role: 'user' | 'assistant'
  content: string
  agentName: string | null
  createdAt: string | null
  isPending: boolean
}

interface ChatRenderActivityItem {
  kind: 'activity'
  key: string
  agentName: string
  status: 'running' | 'completed' | 'failed'
  summaryText: string
  detailsText: string
}

type ChatRenderItem = ChatRenderMessageItem | ChatRenderActivityItem

function formatMessageTimestamp(value: string | null): string {
  if (!value) {
    return '방금 전'
  }

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return '방금 전'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

function buildOptimisticMessageItem(
  role: 'user' | 'assistant',
  content: string,
  key: string,
  agentName: string | null = null,
): ChatRenderMessageItem {
  return {
    kind: 'message',
    key,
    role,
    content,
    agentName,
    createdAt: new Date().toISOString(),
    isPending: true,
  }
}

function buildActivityCard(agentName: string, key: string): ChatRenderActivityItem {
  return {
    kind: 'activity',
    key,
    agentName,
    status: 'running',
    summaryText: `[${agentName}] 작업을 시작했습니다...`,
    detailsText: '',
  }
}

function updateActivityCardByIndex(
  items: ChatRenderItem[],
  targetIndex: number,
  updater: (item: ChatRenderActivityItem) => ChatRenderActivityItem,
): ChatRenderItem[] {
  return items.map((item, index) => {
    if (index !== targetIndex || item.kind !== 'activity') {
      return item
    }

    return updater(item)
  })
}

function findLatestRunningActivityIndex(items: ChatRenderItem[], preferredAgentName?: string): number {
  if (preferredAgentName) {
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index]
      if (item.kind === 'activity' && item.status === 'running' && item.agentName === preferredAgentName) {
        return index
      }
    }
  }

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]
    if (item.kind === 'activity' && item.status === 'running') {
      return index
    }
  }

  return -1
}

function updateLatestRunningActivity(
  items: ChatRenderItem[],
  updater: (item: ChatRenderActivityItem) => ChatRenderActivityItem,
  preferredAgentName?: string,
): ChatRenderItem[] {
  const targetIndex = findLatestRunningActivityIndex(items, preferredAgentName)
  if (targetIndex === -1) {
    return items
  }

  return updateActivityCardByIndex(items, targetIndex, updater)
}

function finishRunningActivities(items: ChatRenderItem[], fallbackText: string): ChatRenderItem[] {
  return items.map((item) => {
    if (item.kind !== 'activity' || item.status !== 'running') {
      return item
    }

    return {
      ...item,
      status: 'failed',
      summaryText: `[${item.agentName}] 응답이 중단되었습니다.`,
      detailsText: item.detailsText || fallbackText,
    }
  })
}

function resolveActivityCardClassName(status: ChatRenderActivityItem['status']): string {
  if (status === 'completed') {
    return 'border-slate-200/80 bg-slate-100/80 text-slate-800 dark:border-slate-600/60 dark:bg-slate-700/40 dark:text-slate-100'
  }
  if (status === 'failed') {
    return 'border-rose-200/80 bg-rose-50/90 text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-100'
  }
  return 'border-slate-200/80 bg-slate-100/85 text-slate-800 dark:border-slate-600/60 dark:bg-slate-700/35 dark:text-slate-100'
}

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }

  return fallback
}

function PortfolioMiniChat({ sessionId, onCreateSession }: PortfolioMiniChatProps) {
  const [draftMessage, setDraftMessage] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isCreatingSession, setIsCreatingSession] = useState(false)
  const [liveItems, setLiveItems] = useState<ChatRenderItem[]>([])
  const [notice, setNotice] = useState<NoticeState | null>(null)

  const liveItemSequenceRef = useRef(0)
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null)
  const requestSequenceRef = useRef(0)
  const activeRequestIdRef = useRef(0)

  useEffect(() => {
    activeRequestIdRef.current += 1
    setDraftMessage('')
    setIsStreaming(false)
    setNotice(null)
    setLiveItems([])
  }, [sessionId])

  useEffect(() => {
    bottomAnchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [liveItems])

  useEffect(() => {
    return () => {
      activeRequestIdRef.current += 1
    }
  }, [])

  const handleCreateSession = async () => {
    if (isCreatingSession || isStreaming) {
      return
    }

    setIsCreatingSession(true)
    setNotice(null)

    try {
      const createdSessionId = await onCreateSession()
      if (!createdSessionId) {
        setNotice({
          type: 'error',
          message: '새 대화를 시작하지 못했습니다.',
        })
      }
    } catch (error) {
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '새 대화를 시작하지 못했습니다.'),
      })
    } finally {
      setIsCreatingSession(false)
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const normalizedMessage = draftMessage.trim()
    if (!sessionId || !normalizedMessage || isStreaming) {
      return
    }

    const requestId = ++requestSequenceRef.current
    activeRequestIdRef.current = requestId

    const optimisticUserMessage = buildOptimisticMessageItem(
      'user',
      normalizedMessage,
      `mini-chat-user-${++liveItemSequenceRef.current}`,
    )

    setDraftMessage('')
    setIsStreaming(true)
    setNotice(null)
    setLiveItems((current) => [...current, optimisticUserMessage])

    try {
      await streamChatMessage(sessionId, normalizedMessage, (streamEvent) => {
        if (activeRequestIdRef.current !== requestId) {
          return
        }

        if (streamEvent.type === 'agent_start') {
          setLiveItems((current) => [
            ...current,
            buildActivityCard(
              streamEvent.agent_name,
              `mini-chat-activity-${++liveItemSequenceRef.current}`,
            ),
          ])
          return
        }

        if (streamEvent.type === 'tool_call') {
          setLiveItems((current) =>
            updateLatestRunningActivity(current, (activity) => ({
              ...activity,
              summaryText: `[${activity.agentName}] 도구를 호출하고 있습니다...`,
              detailsText: streamEvent.content || activity.detailsText,
            })),
          )
          return
        }

        if (streamEvent.type === 'agent_end') {
          setLiveItems((current) =>
            updateLatestRunningActivity(
              current,
              (activity) => ({
                ...activity,
                status: 'completed',
                summaryText: `[${activity.agentName}] 작업이 완료되었습니다.`,
                detailsText: streamEvent.content || activity.detailsText,
              }),
              streamEvent.agent_name,
            ),
          )
          return
        }

        if (streamEvent.type === 'final_answer') {
          setLiveItems((current) => [
            ...current,
            buildOptimisticMessageItem(
              'assistant',
              streamEvent.content,
              `mini-chat-assistant-${++liveItemSequenceRef.current}`,
              streamEvent.agent_name,
            ),
          ])
        }
      })
    } catch (error) {
      if (activeRequestIdRef.current !== requestId) {
        return
      }

      setLiveItems((current) =>
        finishRunningActivities(current, '채팅 스트리밍이 중단되었습니다.'),
      )
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '채팅 요청을 처리하지 못했습니다.'),
      })
    } finally {
      if (activeRequestIdRef.current === requestId) {
        setLiveItems((current) =>
          current.map((item) =>
            item.kind === 'message' ? { ...item, isPending: false } : item,
          ),
        )
        setIsStreaming(false)
      }
    }
  }

  return (
    <section className="relative flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/70 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.5)] backdrop-blur-xl transition-shadow duration-200 hover:shadow-[0_36px_110px_-44px_rgba(15,23,42,0.58)] dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_36px_110px_-44px_rgba(2,6,23,1)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.14),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.12),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.14),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative flex min-h-0 flex-1 flex-col">
        <header className="border-b border-white/50 px-5 py-4 dark:border-white/10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
                AI MINI CHAT
              </p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950 dark:text-white">
                💬 AI에게 질문하기
              </h2>
            </div>

            {isStreaming ? (
              <span className="inline-flex items-center gap-2 rounded-full border border-emerald-200/80 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/15 dark:text-emerald-200">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                응답 생성 중
              </span>
            ) : null}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          {!sessionId ? (
            <div className="flex h-full min-h-[220px] flex-col items-center justify-center rounded-[24px] border border-dashed border-slate-300 bg-white/45 px-6 text-center dark:border-slate-600 dark:bg-slate-800/30">
              <MessageSquare className="h-10 w-10 text-emerald-500 dark:text-emerald-300" />
              <h3 className="mt-4 text-lg font-semibold text-slate-950 dark:text-white">
                채팅 세션이 없습니다
              </h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-slate-600 dark:text-slate-300">
                새 대화를 시작하면 포트폴리오 페이지 안에서 바로 AI에게 질문할 수 있습니다.
              </p>
              <button
                type="button"
                onClick={() => void handleCreateSession()}
                disabled={isCreatingSession}
                className="mt-5 inline-flex items-center gap-2 rounded-full bg-emerald-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-300"
              >
                {isCreatingSession ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                새 대화 시작
              </button>
            </div>
          ) : null}

          {sessionId && liveItems.length === 0 ? (
            <div className="flex h-full min-h-[220px] flex-col items-center justify-center rounded-[24px] border border-dashed border-slate-300 bg-white/45 px-6 text-center dark:border-slate-600 dark:bg-slate-800/30">
              <MessageSquare className="h-10 w-10 text-sky-500 dark:text-sky-300" />
              <h3 className="mt-4 text-lg font-semibold text-slate-950 dark:text-white">
                첫 질문을 남겨보세요
              </h3>
              <p className="mt-2 max-w-sm text-sm leading-6 text-slate-600 dark:text-slate-300">
                포트폴리오, 리스크, 시장 상황에 대해 짧게 물어보면 여기서 바로 답변을 받을 수 있습니다.
              </p>
            </div>
          ) : null}

          {sessionId && liveItems.length > 0 ? (
            <div className="space-y-4">
              {liveItems.map((item) => {
                if (item.kind === 'activity') {
                  return (
                    <div key={item.key} className="flex justify-start">
                      <div
                        className={`w-full max-w-xl rounded-2xl border px-4 py-3 text-sm shadow-sm backdrop-blur-sm ${resolveActivityCardClassName(item.status)}`}
                      >
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/75 dark:bg-slate-900/40">
                            {item.status === 'running' ? (
                              <Loader2 className="h-4 w-4 animate-spin text-slate-600 dark:text-slate-200" />
                            ) : item.status === 'completed' ? (
                              <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-300" />
                            ) : (
                              <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-300" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-semibold uppercase tracking-[0.18em] opacity-70">
                              {item.agentName}
                            </p>
                            <p className="mt-1 whitespace-pre-wrap break-words font-medium leading-6">
                              {item.summaryText}
                            </p>
                            {item.detailsText ? (
                              <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-6 opacity-80">
                                {item.detailsText}
                              </p>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                }

                if (item.role === 'user') {
                  return (
                    <div key={item.key} className="flex justify-end">
                      <div className="max-w-[82%] rounded-2xl rounded-br-md bg-gradient-to-br from-indigo-600 to-blue-600 px-4 py-3 text-white shadow-sm">
                        <p className="whitespace-pre-wrap break-words text-sm leading-6">{item.content}</p>
                        <div className="mt-2 text-right text-[11px] font-medium text-indigo-100/90">
                          {formatMessageTimestamp(item.createdAt)}
                        </div>
                      </div>
                    </div>
                  )
                }

                return (
                  <div key={item.key} className="flex justify-start">
                    <div className="flex max-w-[82%] items-start gap-3">
                      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm text-white shadow-sm dark:bg-slate-100 dark:text-slate-900">
                        <span aria-hidden="true">AI</span>
                      </div>
                      <div className="rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 text-slate-900 shadow-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                            {item.agentName ?? 'assistant'}
                          </span>
                          {item.isPending ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              작성 중
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">
                          {item.content}
                        </p>
                        <div className="mt-2 text-[11px] font-medium text-slate-500 dark:text-slate-400">
                          {formatMessageTimestamp(item.createdAt)}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
              <div ref={bottomAnchorRef} />
            </div>
          ) : null}
        </div>

        <div className="border-t border-white/50 px-5 py-4 dark:border-white/10">
          {notice ? (
            <div
              className={`mb-3 rounded-xl px-4 py-3 text-sm ${
                notice.type === 'info'
                  ? 'border border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
                  : 'border border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200'
              }`}
            >
              {notice.message}
            </div>
          ) : null}

          <form onSubmit={handleSubmit} className="flex items-center gap-3">
            <input
              type="text"
              value={draftMessage}
              onChange={(event) => setDraftMessage(event.target.value)}
              placeholder={
                sessionId
                  ? 'AI에게 포트폴리오 관련 질문을 남겨보세요...'
                  : '새 대화를 시작하면 입력할 수 있습니다.'
              }
              disabled={!sessionId || isStreaming}
              className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-emerald-400 dark:focus:ring-emerald-400 dark:disabled:bg-slate-800 dark:disabled:text-slate-500"
            />
            <button
              type="submit"
              disabled={!sessionId || isStreaming || draftMessage.trim().length === 0}
              className="inline-flex min-w-[108px] items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-500 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white dark:disabled:bg-slate-600 dark:disabled:text-slate-300"
            >
              {isStreaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <SendHorizontal className="h-4 w-4" />
              )}
              <span>{isStreaming ? '전송 중' : '전송'}</span>
            </button>
          </form>
        </div>
      </div>
    </section>
  )
}

export default PortfolioMiniChat
