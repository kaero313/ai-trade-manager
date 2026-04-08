import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Menu, MessageSquare, Plus, SendHorizontal, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import {
  createChatSession,
  getChatMessages,
  getChatSessions,
  streamChatMessage,
  type ChatMessage,
  type ChatSession,
} from '../services/api'

interface NoticeState {
  type: 'success' | 'error' | 'info'
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

interface ChatRenderEventItem {
  kind: 'event'
  key: string
  eventType: string
  agentName: string
  content: string
}

type ChatRenderItem = ChatRenderMessageItem | ChatRenderEventItem

const CHAT_SESSIONS_QUERY_KEY = ['chat-sessions'] as const

function getChatMessagesQueryKey(sessionId: string) {
  return ['chat-messages', sessionId] as const
}

function formatSessionTimestamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return '-'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

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

function compareSessionActivityDescending(left: ChatSession, right: ChatSession): number {
  const leftTime = new Date(left.last_activity).getTime()
  const rightTime = new Date(right.last_activity).getTime()
  return rightTime - leftTime
}

function buildPendingSession(sessionId: string): ChatSession {
  return {
    session_id: sessionId,
    last_message_preview: '아직 메시지가 없습니다.',
    last_activity: new Date().toISOString(),
  }
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

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function mapStoredMessagesToRenderItems(messages: ChatMessage[] | undefined): ChatRenderMessageItem[] {
  return (messages ?? [])
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .map((message) => ({
      kind: 'message',
      key: `message-${message.id}`,
      role: message.role as 'user' | 'assistant',
      content: message.content,
      agentName: message.agent_name,
      createdAt: message.created_at,
      isPending: false,
    }))
}

function resolveEventLabel(eventType: string): string {
  switch (eventType) {
    case 'agent_start':
      return '에이전트 시작'
    case 'agent_end':
      return '에이전트 완료'
    case 'tool_call':
      return '툴 호출'
    case 'approval_request':
      return '승인 요청'
    default:
      return '진행 상태'
  }
}

function resolveEventCardClassName(eventType: string): string {
  switch (eventType) {
    case 'approval_request':
      return 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-100'
    case 'tool_call':
      return 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-400/20 dark:bg-sky-500/10 dark:text-sky-100'
    case 'agent_end':
      return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-400/20 dark:bg-emerald-500/10 dark:text-emerald-100'
    default:
      return 'border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-400/20 dark:bg-violet-500/10 dark:text-violet-100'
  }
}

function MessageSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1, 2, 3, 4].map((index) => (
        <div
          key={index}
          className={`flex ${index % 2 === 0 ? 'justify-start' : 'justify-end'} animate-pulse`}
        >
          <div
            className={`max-w-[78%] rounded-2xl px-4 py-4 ${
              index % 2 === 0
                ? 'border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800'
                : 'bg-indigo-300/70 dark:bg-indigo-500/40'
            }`}
          >
            <div className="h-3 w-20 rounded bg-gray-200 dark:bg-gray-700" />
            <div className="mt-3 h-3 w-64 rounded bg-gray-200 dark:bg-gray-700" />
            <div className="mt-2 h-3 w-40 rounded bg-gray-200 dark:bg-gray-700" />
          </div>
        </div>
      ))}
    </div>
  )
}

function AIChatPage() {
  const queryClient = useQueryClient()
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [draftMessage, setDraftMessage] = useState('')
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isCreatingSession, setIsCreatingSession] = useState(false)
  const [pendingSessions, setPendingSessions] = useState<ChatSession[]>([])
  const [liveItems, setLiveItems] = useState<ChatRenderItem[]>([])
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const liveItemSequenceRef = useRef(0)
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null)
  const lastScrolledSessionIdRef = useRef<string | null>(null)

  const chatSessionsQuery = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: getChatSessions,
  })

  const chatMessagesQuery = useQuery({
    queryKey: selectedSessionId ? getChatMessagesQueryKey(selectedSessionId) : ['chat-messages', 'idle'],
    queryFn: () => getChatMessages(selectedSessionId ?? ''),
    enabled: Boolean(selectedSessionId),
  })

  useEffect(() => {
    const serverSessionIds = new Set((chatSessionsQuery.data ?? []).map((item) => item.session_id))
    setPendingSessions((current) => current.filter((item) => !serverSessionIds.has(item.session_id)))
  }, [chatSessionsQuery.data])

  useEffect(() => {
    setLiveItems([])
    setNotice(null)
  }, [selectedSessionId])

  const sessions = useMemo(() => {
    const serverSessions = chatSessionsQuery.data ?? []
    const serverSessionIds = new Set(serverSessions.map((item) => item.session_id))
    const pendingOnlySessions = pendingSessions.filter((item) => !serverSessionIds.has(item.session_id))

    return [...pendingOnlySessions, ...serverSessions].sort(compareSessionActivityDescending)
  }, [chatSessionsQuery.data, pendingSessions])

  const selectedSession = useMemo(
    () => sessions.find((item) => item.session_id === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  )

  const storedMessageItems = useMemo(
    () => mapStoredMessagesToRenderItems(chatMessagesQuery.data),
    [chatMessagesQuery.data],
  )

  const renderedConversation = useMemo(
    () => [...storedMessageItems, ...liveItems],
    [liveItems, storedMessageItems],
  )

  useEffect(() => {
    if (!selectedSessionId) {
      return
    }

    const behavior = lastScrolledSessionIdRef.current === selectedSessionId ? 'smooth' : 'auto'
    bottomAnchorRef.current?.scrollIntoView({ behavior, block: 'end' })
    lastScrolledSessionIdRef.current = selectedSessionId
  }, [selectedSessionId, chatMessagesQuery.dataUpdatedAt, renderedConversation.length])

  const syncSessions = async () => {
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY })
  }

  const syncMessages = async (sessionId: string) => {
    await queryClient.fetchQuery({
      queryKey: getChatMessagesQueryKey(sessionId),
      queryFn: () => getChatMessages(sessionId),
    })
  }

  const createAndSelectSession = async (): Promise<string | null> => {
    setIsCreatingSession(true)
    try {
      const result = await createChatSession()
      const nextSession = buildPendingSession(result.session_id)

      setPendingSessions((current) => {
        const withoutDuplicate = current.filter((item) => item.session_id !== result.session_id)
        return [nextSession, ...withoutDuplicate]
      })
      setSelectedSessionId(result.session_id)
      setIsSidebarOpen(false)
      return result.session_id
    } catch (error) {
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '새 대화 세션을 만들지 못했습니다.'),
      })
      return null
    } finally {
      setIsCreatingSession(false)
    }
  }

  const ensureSelectedSessionId = async (): Promise<string | null> => {
    if (selectedSessionId) {
      return selectedSessionId
    }
    return await createAndSelectSession()
  }

  const handleCreateSession = async () => {
    if (isStreaming) {
      return
    }
    await createAndSelectSession()
  }

  const handleSelectSession = (sessionId: string) => {
    if (isStreaming) {
      return
    }

    setSelectedSessionId(sessionId)
    setIsSidebarOpen(false)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const normalizedMessage = draftMessage.trim()
    if (!normalizedMessage || isStreaming) {
      return
    }

    const targetSessionId = await ensureSelectedSessionId()
    if (!targetSessionId) {
      return
    }

    const optimisticUserMessage = buildOptimisticMessageItem(
      'user',
      normalizedMessage,
      `live-user-${++liveItemSequenceRef.current}`,
    )

    setIsStreaming(true)
    setNotice(null)
    setDraftMessage('')
    setLiveItems([optimisticUserMessage])

    setPendingSessions((current) =>
      current.map((item) =>
        item.session_id === targetSessionId
          ? {
              ...item,
              last_message_preview: normalizedMessage,
              last_activity: new Date().toISOString(),
            }
          : item,
      ),
    )

    try {
      await streamChatMessage(targetSessionId, normalizedMessage, (streamEvent) => {
        if (streamEvent.type === 'final_answer') {
          setLiveItems((current) => [
            ...current,
            buildOptimisticMessageItem(
              'assistant',
              streamEvent.content,
              `live-assistant-${++liveItemSequenceRef.current}`,
              streamEvent.agent_name,
            ),
          ])
          return
        }

        setLiveItems((current) => [
          ...current,
          {
            kind: 'event',
            key: `live-event-${++liveItemSequenceRef.current}`,
            eventType: streamEvent.type,
            agentName: streamEvent.agent_name,
            content: streamEvent.content,
          },
        ])
      })

      await Promise.all([syncSessions(), syncMessages(targetSessionId)])
      setLiveItems([])
    } catch (error) {
      try {
        await syncMessages(targetSessionId)
      } catch {
        // 동기화 실패는 원래 오류 메시지를 우선 유지합니다.
      }

      setLiveItems([])
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '채팅 스트리밍 요청에 실패했습니다.'),
      })
    } finally {
      setIsStreaming(false)
    }
  }

  const sidebarContent = (
    <div className="flex h-full min-h-0 flex-col rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-4 dark:border-gray-700">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-300">
            AI Banker
          </p>
          <h2 className="mt-2 text-lg font-semibold text-gray-900 dark:text-gray-100">대화 세션</h2>
        </div>
        <button
          type="button"
          onClick={() => setIsSidebarOpen(false)}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-gray-200 text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 lg:hidden dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
          aria-label="세션 사이드바 닫기"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="border-b border-gray-200 px-4 py-4 dark:border-gray-700">
        <button
          type="button"
          onClick={() => void handleCreateSession()}
          disabled={isCreatingSession || isStreaming}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-300"
        >
          {isCreatingSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          <span>{isCreatingSession ? '생성 중...' : '+ 새 대화'}</span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {chatSessionsQuery.isLoading && (
          <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            세션 목록을 불러오는 중입니다.
          </div>
        )}

        {chatSessionsQuery.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            {resolveErrorMessage(chatSessionsQuery.error, '세션 목록을 불러오지 못했습니다.')}
          </div>
        )}

        {!chatSessionsQuery.isLoading && !chatSessionsQuery.isError && sessions.length === 0 && (
          <div className="rounded-xl border border-dashed border-gray-300 px-4 py-8 text-center text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
            아직 저장된 대화가 없습니다.
          </div>
        )}

        <div className="space-y-2">
          {sessions.map((session) => {
            const isSelected = session.session_id === selectedSessionId

            return (
              <button
                key={session.session_id}
                type="button"
                onClick={() => handleSelectSession(session.session_id)}
                disabled={isStreaming}
                className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                  isSelected
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 shadow-sm dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
                    : 'border-transparent bg-gray-50 text-gray-700 hover:border-gray-200 hover:bg-gray-100 dark:bg-gray-700/40 dark:text-gray-200 dark:hover:border-gray-600 dark:hover:bg-gray-700'
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm font-semibold">
                    {session.last_message_preview || '새 대화'}
                  </span>
                  <span className="shrink-0 text-[11px] font-medium opacity-70">
                    {formatSessionTimestamp(session.last_activity)}
                  </span>
                </div>
                <p className="mt-2 truncate text-xs opacity-80">{session.session_id}</p>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )

  const showMessagesSkeleton = Boolean(selectedSessionId) && chatMessagesQuery.isLoading
  const showEmptySelectedSession =
    Boolean(selectedSession) &&
    !showMessagesSkeleton &&
    !chatMessagesQuery.isError &&
    renderedConversation.length === 0

  return (
    <div className="flex h-full min-h-0 flex-col gap-6">
      <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-300">
              AI Banker Chat
            </p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
              AI 뱅커
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-600 dark:text-gray-300">
              포트폴리오, 주문, AI 분석, 시스템 설정을 대화형으로 조회하고 조정할 수 있는 멀티 에이전트 채팅 화면입니다.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setIsSidebarOpen(true)}
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-gray-200 text-gray-700 transition hover:bg-gray-100 hover:text-gray-900 lg:hidden dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-700 dark:hover:text-white"
            aria-label="세션 목록 열기"
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </section>

      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 lg:block">{sidebarContent}</aside>

        <section className="flex min-h-0 flex-col rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <header className="flex items-center justify-between gap-4 border-b border-gray-200 px-5 py-4 dark:border-gray-700">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500 dark:text-gray-400">
                Conversation
              </p>
              <h2 className="mt-2 truncate text-lg font-semibold text-gray-900 dark:text-gray-100">
                {selectedSession ? '선택된 세션' : '새 대화를 시작하세요'}
              </h2>
              <p className="mt-1 truncate text-sm text-gray-500 dark:text-gray-400">
                {selectedSession?.session_id ?? '좌측 목록에서 세션을 선택하거나 새 대화를 만들어 시작합니다.'}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {isStreaming && (
                <div className="hidden items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 sm:inline-flex dark:bg-emerald-500/10 dark:text-emerald-200">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  응답 생성 중
                </div>
              )}
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                className="hidden h-10 w-10 items-center justify-center rounded-lg border border-gray-200 text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 sm:inline-flex lg:hidden dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
                aria-label="세션 목록 열기"
              >
                <Menu className="h-5 w-5" />
              </button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto bg-gray-50/80 px-5 py-5 dark:bg-gray-900/30">
            {!selectedSession && (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-2xl border border-dashed border-gray-300 bg-white/70 px-6 text-center dark:border-gray-600 dark:bg-gray-800/30">
                <MessageSquare className="h-10 w-10 text-emerald-500" />
                <h3 className="mt-4 text-xl font-semibold text-gray-900 dark:text-gray-100">
                  새 대화를 시작하세요
                </h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-gray-500 dark:text-gray-400">
                  상단의 새 대화 버튼을 누르거나 바로 질문을 입력하면, AI 뱅커 전용 세션이 자동으로 생성됩니다.
                </p>
              </div>
            )}

            {selectedSession && showMessagesSkeleton && <MessageSkeleton />}

            {selectedSession && chatMessagesQuery.isError && !showMessagesSkeleton && (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
                {resolveErrorMessage(chatMessagesQuery.error, '대화 이력을 불러오지 못했습니다.')}
              </div>
            )}

            {showEmptySelectedSession && (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-2xl border border-dashed border-gray-300 bg-white/70 px-6 text-center dark:border-gray-600 dark:bg-gray-800/30">
                <MessageSquare className="h-10 w-10 text-indigo-500" />
                <h3 className="mt-4 text-xl font-semibold text-gray-900 dark:text-gray-100">
                  아직 이 세션에 메시지가 없습니다
                </h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-gray-500 dark:text-gray-400">
                  아래 입력창에서 첫 질문을 보내면 대화 이력이 이 영역에 순서대로 쌓입니다.
                </p>
              </div>
            )}

            {selectedSession && !showMessagesSkeleton && !chatMessagesQuery.isError && renderedConversation.length > 0 && (
              <div className="space-y-4">
                {renderedConversation.map((item) => {
                  if (item.kind === 'event') {
                    return (
                      <div key={item.key} className="flex justify-center">
                        <div
                          className={`w-full max-w-2xl rounded-2xl border px-4 py-3 text-sm shadow-sm ${resolveEventCardClassName(
                            item.eventType,
                          )}`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-xs font-semibold uppercase tracking-[0.18em] opacity-80">
                              {resolveEventLabel(item.eventType)}
                            </span>
                            <span className="rounded-full bg-white/70 px-2 py-1 text-[11px] font-semibold text-gray-700 dark:bg-gray-900/30 dark:text-gray-200">
                              {item.agentName}
                            </span>
                          </div>
                          <p className="mt-2 whitespace-pre-wrap break-words leading-6">{item.content}</p>
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
                        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm shadow-sm dark:bg-gray-100">
                          <span aria-hidden="true">🤖</span>
                        </div>
                        <div className="rounded-2xl rounded-bl-md border border-gray-200 bg-white px-4 py-3 text-gray-900 shadow-sm dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                              {item.agentName ?? 'assistant'}
                            </span>
                            {item.isPending && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200">
                                <Loader2 className="h-3 w-3 animate-spin" />
                                작성 중
                              </span>
                            )}
                          </div>
                          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{item.content}</p>
                          <div className="mt-2 text-[11px] font-medium text-gray-500 dark:text-gray-400">
                            {formatMessageTimestamp(item.createdAt)}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
                <div ref={bottomAnchorRef} />
              </div>
            )}
          </div>

          <div className="border-t border-gray-200 px-5 py-4 dark:border-gray-700">
            {notice && (
              <div
                className={`mb-4 rounded-xl px-4 py-3 text-sm ${
                  notice.type === 'success'
                    ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200'
                    : notice.type === 'info'
                      ? 'border border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-700/40 dark:text-gray-200'
                      : 'border border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200'
                }`}
              >
                {notice.message}
              </div>
            )}

            <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <input
                type="text"
                value={draftMessage}
                onChange={(event) => setDraftMessage(event.target.value)}
                placeholder="AI 뱅커에게 무엇이든 물어보세요..."
                disabled={isStreaming}
                className="w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500 dark:focus:border-emerald-400 dark:focus:ring-emerald-400"
              />
              <button
                type="submit"
                disabled={isStreaming || draftMessage.trim().length === 0}
                className="inline-flex min-w-[132px] items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-500"
              >
                {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
                <span>{isStreaming ? '전송 중...' : '전송'}</span>
              </button>
            </form>
          </div>
        </section>
      </div>

      {isSidebarOpen && (
        <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setIsSidebarOpen(false)}>
          <div
            className="h-full w-[min(88vw,340px)] bg-transparent p-4 pt-20"
            onClick={(event) => event.stopPropagation()}
          >
            {sidebarContent}
          </div>
        </div>
      )}
    </div>
  )
}

export default AIChatPage
