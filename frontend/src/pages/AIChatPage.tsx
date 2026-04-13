import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, Loader2, Menu, MessageSquare, Plus, SendHorizontal, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import { SYSTEM_CONFIGS_QUERY_KEY, useSystemConfigs } from '../hooks/useSystemConfigs'
import {
  approveChatConfigChange,
  createChatSession,
  getChatMessages,
  getChatSessions,
  streamChatMessage,
  type ChatMessage,
  type ChatSession,
  type SystemConfigItem,
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

interface ChatRenderActivityItem {
  kind: 'activity'
  key: string
  agentName: string
  status: 'running' | 'completed' | 'failed'
  summaryText: string
  detailsText: string
  isCollapsed: boolean
}

interface ChatRenderApprovalItem {
  kind: 'approval'
  key: string
  agentName: string
  configKey: string
  proposedValue: string
  currentValue: string | null
  status: 'pending' | 'applying' | 'applied' | 'rejected' | 'failed'
  errorMessage: string | null
}

interface ApprovalRequestPayload {
  action: 'config_change'
  config_key: string
  new_value: string
  requires_approval: true
}

type ChatRenderItem = ChatRenderMessageItem | ChatRenderActivityItem | ChatRenderApprovalItem

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

function buildActivityCard(agentName: string, key: string): ChatRenderActivityItem {
  return {
    kind: 'activity',
    key,
    agentName,
    status: 'running',
    summaryText: `🔄 [${agentName}] 작업을 시작합니다...`,
    detailsText: '',
    isCollapsed: false,
  }
}

function buildApprovalCard(
  agentName: string,
  key: string,
  payload: ApprovalRequestPayload,
  currentValue: string | null,
): ChatRenderApprovalItem {
  return {
    kind: 'approval',
    key,
    agentName,
    configKey: payload.config_key,
    proposedValue: payload.new_value,
    currentValue,
    status: 'pending',
    errorMessage: null,
  }
}

function parseApprovalRequestPayload(content: string): ApprovalRequestPayload | null {
  if (!content.trim()) {
    return null
  }

  try {
    const parsed = JSON.parse(content) as Partial<ApprovalRequestPayload>
    if (
      parsed.action !== 'config_change' ||
      typeof parsed.config_key !== 'string' ||
      typeof parsed.new_value !== 'string' ||
      parsed.requires_approval !== true
    ) {
      return null
    }

    return {
      action: 'config_change',
      config_key: parsed.config_key,
      new_value: parsed.new_value,
      requires_approval: true,
    }
  } catch {
    return null
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

function updateApprovalCardByKey(
  items: ChatRenderItem[],
  key: string,
  updater: (item: ChatRenderApprovalItem) => ChatRenderApprovalItem,
): ChatRenderItem[] {
  return items.map((item) => {
    if (item.kind !== 'approval' || item.key !== key) {
      return item
    }

    return updater(item)
  })
}

function collapseActivityCards(items: ChatRenderItem[]): ChatRenderItem[] {
  return items.map((item) => {
    if (item.kind !== 'activity') {
      return item
    }

    return {
      ...item,
      isCollapsed: true,
    }
  })
}

function finishRunningActivities(items: ChatRenderItem[], fallbackText: string): ChatRenderItem[] {
  return items.map((item) => {
    if (item.kind !== 'activity' || item.status !== 'running') {
      return item
    }

    return {
      ...item,
      status: 'failed',
      summaryText: `⚠️ [${item.agentName}] 응답이 중단되었습니다.`,
      detailsText: item.detailsText || fallbackText,
      isCollapsed: false,
    }
  })
}

function resolveActivityCardClassName(status: ChatRenderActivityItem['status']): string {
  switch (status) {
    case 'completed':
      return 'border-gray-200/80 bg-gray-100/80 text-gray-800 dark:border-gray-600/60 dark:bg-gray-700/40 dark:text-gray-100'
    case 'failed':
      return 'border-rose-200/80 bg-rose-50/85 text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-100'
    default:
      return 'border-gray-200/80 bg-gray-100/85 text-gray-800 dark:border-gray-600/60 dark:bg-gray-700/35 dark:text-gray-100'
  }
}

function resolveApprovalStatusLabel(status: ChatRenderApprovalItem['status']): string {
  switch (status) {
    case 'applying':
      return '적용 중'
    case 'applied':
      return '적용 완료'
    case 'rejected':
      return '사용자가 거부했습니다'
    case 'failed':
      return '적용 실패'
    default:
      return '승인 대기'
  }
}

function resolveApprovalStatusClassName(status: ChatRenderApprovalItem['status']): string {
  switch (status) {
    case 'applying':
      return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
    case 'applied':
      return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200'
    case 'rejected':
      return 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200'
    case 'failed':
      return 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-200'
    default:
      return 'bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200'
  }
}

function formatConfigValueLabel(value: string | null, isLoading: boolean): string {
  if (value && value.trim()) {
    return value
  }

  if (isLoading) {
    return '불러오는 중'
  }

  return '설정되지 않음'
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

  const systemConfigsQuery = useSystemConfigs()

  const chatSessionsQuery = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: getChatSessions,
  })

  const chatMessagesQuery = useQuery({
    queryKey: selectedSessionId ? getChatMessagesQueryKey(selectedSessionId) : ['chat-messages', 'idle'],
    queryFn: () => getChatMessages(selectedSessionId ?? ''),
    enabled: Boolean(selectedSessionId),
  })

  const systemConfigMap = useMemo(
    () => new Map((systemConfigsQuery.data ?? []).map((item) => [item.config_key, item.config_value])),
    [systemConfigsQuery.data],
  )

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
  }, [selectedSessionId, chatMessagesQuery.dataUpdatedAt, renderedConversation])

  const syncSessions = async () => {
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY })
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

  const toggleActivityCard = (key: string) => {
    setLiveItems((current) =>
      current.map((item) => {
        if (item.kind !== 'activity' || item.key !== key) {
          return item
        }

        return {
          ...item,
          isCollapsed: !item.isCollapsed,
        }
      }),
    )
  }

  const handleApproveRequest = async (key: string) => {
    if (!selectedSessionId) {
      return
    }

    const targetItem = liveItems.find(
      (item): item is ChatRenderApprovalItem =>
        item.kind === 'approval' && item.key === key && (item.status === 'pending' || item.status === 'failed'),
    )
    if (!targetItem) {
      return
    }

    setLiveItems((current) =>
      updateApprovalCardByKey(current, key, (item) => ({
        ...item,
        status: 'applying',
        errorMessage: null,
      })),
    )

    try {
      const nextConfigs = await approveChatConfigChange(selectedSessionId, {
        config_key: targetItem.configKey,
        config_value: targetItem.proposedValue,
      })

      queryClient.setQueryData<SystemConfigItem[]>(SYSTEM_CONFIGS_QUERY_KEY, nextConfigs)
      await queryClient.invalidateQueries({ queryKey: SYSTEM_CONFIGS_QUERY_KEY })

      const appliedValue =
        nextConfigs.find((config) => config.config_key === targetItem.configKey)?.config_value ??
        targetItem.proposedValue

      setLiveItems((current) =>
        updateApprovalCardByKey(current, key, (item) => ({
          ...item,
          status: 'applied',
          currentValue: appliedValue,
          errorMessage: null,
        })),
      )
      setNotice({
        type: 'success',
        message: `${targetItem.configKey} 설정이 적용되었습니다.`,
      })
    } catch (error) {
      const errorMessage = resolveErrorMessage(error, '설정 적용 요청에 실패했습니다.')
      setLiveItems((current) =>
        updateApprovalCardByKey(current, key, (item) => ({
          ...item,
          status: 'failed',
          errorMessage,
        })),
      )
      setNotice({
        type: 'error',
        message: errorMessage,
      })
    }
  }

  const handleRejectRequest = (key: string) => {
    setLiveItems((current) =>
      updateApprovalCardByKey(current, key, (item) => ({
        ...item,
        status: 'rejected',
        errorMessage: null,
      })),
    )
    setNotice({
      type: 'info',
      message: '설정 변경 제안을 거부했습니다.',
    })
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
    setLiveItems((current) => [...current, optimisticUserMessage])

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
        if (streamEvent.type === 'agent_start') {
          setLiveItems((current) => [
            ...current,
            buildActivityCard(streamEvent.agent_name, `live-activity-${++liveItemSequenceRef.current}`),
          ])
          return
        }

        if (streamEvent.type === 'tool_call') {
          setLiveItems((current) =>
            updateLatestRunningActivity(current, (activity) => ({
              ...activity,
              summaryText: `🔍 [${activity.agentName}] 데이터를 조회하고 있습니다...`,
              detailsText: streamEvent.content || activity.detailsText,
            })),
          )
          return
        }

        if (streamEvent.type === 'approval_request') {
          const approvalPayload = parseApprovalRequestPayload(streamEvent.content)

          setLiveItems((current) => {
            const nextItems = updateLatestRunningActivity(current, (activity) => ({
              ...activity,
              summaryText: `📝 [${activity.agentName}] 승인 요청안을 준비하고 있습니다...`,
              detailsText: streamEvent.content || activity.detailsText,
            }))

            if (!approvalPayload) {
              return nextItems
            }

            return [
              ...nextItems,
              buildApprovalCard(
                streamEvent.agent_name,
                `live-approval-${++liveItemSequenceRef.current}`,
                approvalPayload,
                systemConfigMap.get(approvalPayload.config_key) ?? null,
              ),
            ]
          })
          return
        }

        if (streamEvent.type === 'agent_end') {
          setLiveItems((current) =>
            updateLatestRunningActivity(
              current,
              (activity) => ({
                ...activity,
                status: 'completed',
                summaryText: `✅ [${activity.agentName}] 작업이 완료되었습니다.`,
                detailsText: streamEvent.content || activity.detailsText,
              }),
              streamEvent.agent_name,
            ),
          )
          return
        }

        if (streamEvent.type === 'final_answer') {
          setLiveItems((current) =>
            collapseActivityCards([
              ...current,
              buildOptimisticMessageItem(
                'assistant',
                streamEvent.content,
                `live-assistant-${++liveItemSequenceRef.current}`,
                streamEvent.agent_name,
              ),
            ]),
          )
        }
      })

      await syncSessions()
    } catch (error) {
      setLiveItems((current) => finishRunningActivities(current, '채팅 스트리밍이 중단되었습니다.'))
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '채팅 스트리밍 요청에 실패했습니다.'),
      })
    } finally {
      setLiveItems((current) =>
        current.map((item) => (item.kind === 'message' ? { ...item, isPending: false } : item)),
      )
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
            아직 대화 세션이 없습니다.
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
              포트폴리오, 주문, AI 분석, 시스템 설정을 대화형으로 조회하고 조정할 수 있는 멀티 에이전트
              채팅 화면입니다.
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
                {selectedSession?.session_id ??
                  '좌측 목록에서 세션을 선택하거나, 바로 질문을 입력하면 새 세션이 자동으로 생성됩니다.'}
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
                  상단의 새 대화 버튼을 누르거나 바로 질문을 입력하면, AI 뱅커 전용 세션이 자동으로
                  생성됩니다.
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
                  if (item.kind === 'activity') {
                    return (
                      <div key={item.key} className="flex justify-start">
                        <div
                          className={`w-full max-w-2xl rounded-2xl border px-4 py-3 text-sm shadow-sm backdrop-blur-sm ${resolveActivityCardClassName(
                            item.status,
                          )}`}
                        >
                          <button
                            type="button"
                            onClick={() => toggleActivityCard(item.key)}
                            className="flex w-full items-center justify-between gap-3 text-left"
                          >
                            <div className="flex min-w-0 items-center gap-3">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/75 dark:bg-gray-900/40">
                                {item.status === 'running' ? (
                                  <Loader2 className="h-4 w-4 animate-spin text-gray-600 dark:text-gray-200" />
                                ) : (
                                  <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-300" />
                                )}
                              </div>
                              <div className="min-w-0">
                                <p className="truncate text-xs font-semibold uppercase tracking-[0.18em] opacity-70">
                                  {item.agentName}
                                </p>
                                <p className="mt-1 whitespace-pre-wrap break-words font-medium leading-6">
                                  {item.summaryText}
                                </p>
                              </div>
                            </div>
                            <div className="shrink-0 rounded-full bg-white/70 p-1 dark:bg-gray-900/30">
                              {item.isCollapsed ? (
                                <ChevronRight className="h-4 w-4" />
                              ) : (
                                <ChevronDown className="h-4 w-4" />
                              )}
                            </div>
                          </button>

                          {!item.isCollapsed && item.detailsText && (
                            <div className="mt-3 border-t border-white/60 pt-3 text-xs leading-6 text-gray-700 dark:border-gray-600/60 dark:text-gray-200">
                              <p className="font-semibold opacity-80">상세 로그</p>
                              <p className="mt-1 whitespace-pre-wrap break-words opacity-90">{item.detailsText}</p>
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  }

                  if (item.kind === 'approval') {
                    const displayedCurrentValue =
                      item.currentValue ?? systemConfigMap.get(item.configKey) ?? null
                    const canApprove = item.status === 'pending' || item.status === 'failed'
                    const canReject = item.status === 'pending' || item.status === 'failed'

                    return (
                      <div key={item.key} className="flex justify-start">
                        <div className="flex max-w-[82%] items-start gap-3">
                          <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm shadow-sm dark:bg-gray-100">
                            <span aria-hidden="true">🤖</span>
                          </div>
                          <div className="w-full rounded-2xl rounded-bl-md border border-amber-200 bg-white px-4 py-4 text-gray-900 shadow-sm dark:border-amber-500/20 dark:bg-gray-800 dark:text-gray-100">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                                {item.agentName}
                              </span>
                              <span
                                className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold ${resolveApprovalStatusClassName(
                                  item.status,
                                )}`}
                              >
                                {item.status === 'applying' && <Loader2 className="h-3 w-3 animate-spin" />}
                                {item.status === 'applied' && <Check className="h-3 w-3" />}
                                {resolveApprovalStatusLabel(item.status)}
                              </span>
                            </div>

                            <p className="mt-2 text-sm font-semibold leading-6 text-gray-900 dark:text-gray-100">
                              설정 변경 제안
                            </p>
                            <p className="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
                              Operations 에이전트가 아래 설정 변경을 제안했습니다.
                            </p>

                            <div className="mt-4 overflow-hidden rounded-xl border border-amber-200/80 bg-amber-50/70 dark:border-amber-500/20 dark:bg-amber-500/5">
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-amber-200/80 px-4 py-3 text-sm dark:border-amber-500/10">
                                <span className="font-semibold text-gray-700 dark:text-gray-200">변경 대상 키</span>
                                <span className="break-all text-gray-900 dark:text-gray-100">{item.configKey}</span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-amber-200/80 px-4 py-3 text-sm dark:border-amber-500/10">
                                <span className="font-semibold text-gray-700 dark:text-gray-200">현재값</span>
                                <span className="break-all text-gray-900 dark:text-gray-100">
                                  {formatConfigValueLabel(displayedCurrentValue, systemConfigsQuery.isLoading)}
                                </span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] px-4 py-3 text-sm">
                                <span className="font-semibold text-gray-700 dark:text-gray-200">제안값</span>
                                <span className="break-all text-gray-900 dark:text-gray-100">{item.proposedValue}</span>
                              </div>
                            </div>

                            {item.errorMessage && (
                              <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
                                {item.errorMessage}
                              </div>
                            )}

                            <div className="mt-4 flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void handleApproveRequest(item.key)}
                                disabled={!canApprove || item.status === 'applying'}
                                className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-emerald-300"
                              >
                                {item.status === 'applying' ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Check className="h-4 w-4" />
                                )}
                                승인
                              </button>
                              <button
                                type="button"
                                onClick={() => handleRejectRequest(item.key)}
                                disabled={!canReject || item.status === 'applying'}
                                className="inline-flex items-center justify-center rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-sm font-semibold text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-700"
                              >
                                거부
                              </button>
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
