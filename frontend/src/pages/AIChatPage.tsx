import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  Plus,
  SendHorizontal,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import AIBankerPortfolioSnapshot from '../components/common/AIBankerPortfolioSnapshot'
import { SYSTEM_CONFIGS_QUERY_KEY, useSystemConfigs } from '../hooks/useSystemConfigs'
import {
  approveChatConfigChange,
  createChatSession,
  deleteChatSession,
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
    summaryText: `AI [${agentName}] 작업을 시작합니다...`,
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
      summaryText: `ERROR [${item.agentName}] 응답이 중단되었습니다.`,
      detailsText: item.detailsText || fallbackText,
      isCollapsed: false,
    }
  })
}

function resolveActivityCardClassName(status: ChatRenderActivityItem['status']): string {
  switch (status) {
    case 'completed':
      return 'border-[#00dbe9]/24 bg-[#00dbe9]/8 text-[#dfe2eb]'
    case 'failed':
      return 'border-[#ffb4ab]/24 bg-[#ffb4ab]/10 text-[#ffdad6]'
    default:
      return 'border-[#eac324]/24 bg-[#eac324]/10 text-[#ffe179]'
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
      return 'bg-[#00dbe9]/10 text-[#7df4ff]'
    case 'applied':
      return 'bg-[#00dbe9]/10 text-[#7df4ff]'
    case 'rejected':
      return 'bg-[#eac324]/10 text-[#ffe179]'
    case 'failed':
      return 'bg-[#ffb4ab]/10 text-[#ffdad6]'
    default:
      return 'bg-[#262a31]/80 text-[#b9cacb]'
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
            className={`max-w-[78%] rounded-lg px-4 py-4 ${
              index % 2 === 0
                ? 'border border-[#3b494b]/30 bg-[#0a0e14]/70'
                : 'bg-[#00dbe9]/12'
            }`}
          >
            <div className="h-3 w-20 rounded bg-[#262a31]" />
            <div className="mt-3 h-3 w-64 rounded bg-[#262a31]" />
            <div className="mt-2 h-3 w-40 rounded bg-[#262a31]" />
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
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)
  const [pendingSessions, setPendingSessions] = useState<ChatSession[]>([])
  const [liveItems, setLiveItems] = useState<ChatRenderItem[]>([])
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const liveItemSequenceRef = useRef(0)
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null)
  const lastScrolledSessionIdRef = useRef<string | null>(null)

  const systemConfigsQuery = useSystemConfigs()

  const chatSessionsQuery = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: () => getChatSessions('ai_banker'),
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

  const handleDeleteSession = async (sessionId: string) => {
    if (isStreaming || deletingSessionId !== null) {
      return
    }

    setDeletingSessionId(sessionId)
    setNotice(null)

    try {
      await deleteChatSession(sessionId)

      const remainingSessions = sessions.filter((item) => item.session_id !== sessionId)
      const nextSelectedSessionId =
        selectedSessionId === sessionId ? (remainingSessions[0]?.session_id ?? null) : selectedSessionId

      queryClient.setQueryData<ChatSession[]>(CHAT_SESSIONS_QUERY_KEY, (current) =>
        (current ?? []).filter((item) => item.session_id !== sessionId),
      )
      queryClient.removeQueries({ queryKey: getChatMessagesQueryKey(sessionId), exact: true })

      setPendingSessions((current) => current.filter((item) => item.session_id !== sessionId))
      setSelectedSessionId(nextSelectedSessionId)

      await syncSessions()
    } catch (error) {
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '대화 세션을 삭제하지 못했습니다.'),
      })
    } finally {
      setDeletingSessionId(null)
    }
  }

  const createAndSelectSession = async (): Promise<string | null> => {
    setIsCreatingSession(true)
    try {
      const result = await createChatSession('ai_banker')
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
    <div className="quantum-card flex h-full min-h-0 flex-col rounded-xl text-[#dfe2eb]">
      <div className="flex items-center justify-between border-b border-[#3b494b]/35 px-4 py-4">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-[#00dbe9]">
            AI Banker
          </p>
          <h2 className="mt-2 text-lg font-bold text-[#dfe2eb]">대화 세션</h2>
        </div>
        <button
          type="button"
          onClick={() => setIsSidebarOpen(false)}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[#3b494b] text-[#b9cacb] transition hover:border-[#00dbe9]/40 hover:bg-[#00dbe9]/10 hover:text-[#7df4ff] lg:hidden"
          aria-label="세션 사이드바 닫기"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="border-b border-[#3b494b]/35 px-4 py-4">
        <button
          type="button"
          onClick={() => void handleCreateSession()}
          disabled={isCreatingSession || isStreaming || deletingSessionId !== null}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#00dbe9] px-4 py-3 text-sm font-bold text-[#00363a] transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-[#262a31] disabled:text-[#849495]"
        >
          {isCreatingSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          <span>{isCreatingSession ? '생성 중...' : '새 대화'}</span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {chatSessionsQuery.isLoading && (
          <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-[#b9cacb]">
            <Loader2 className="h-4 w-4 animate-spin" />
            세션 목록을 불러오는 중입니다.
          </div>
        )}

        {chatSessionsQuery.isError && (
          <div className="rounded-lg bg-[#ffb4ab]/10 px-4 py-3 text-sm font-medium text-[#ffdad6]">
            {resolveErrorMessage(chatSessionsQuery.error, '세션 목록을 불러오지 못했습니다.')}
          </div>
        )}

        {!chatSessionsQuery.isLoading && !chatSessionsQuery.isError && sessions.length === 0 && (
          <div className="rounded-lg border border-dashed border-[#3b494b]/50 bg-[#0a0e14]/70 px-4 py-8 text-center text-sm text-[#849495]">
            아직 대화 세션이 없습니다.
          </div>
        )}

        <div className="space-y-2">
          {sessions.map((session) => {
            const isSelected = session.session_id === selectedSessionId
            const isDeletingThisSession = deletingSessionId === session.session_id

            return (
              <div
                key={session.session_id}
                className={`rounded-lg border transition ${
                  isSelected
                    ? 'border-[#00dbe9]/35 bg-[#00dbe9]/10 text-[#dfe2eb]'
                    : 'border-transparent bg-[#0a0e14]/70 text-[#b9cacb] hover:border-[#3b494b]/60 hover:bg-[#10141a]/85 hover:text-[#dfe2eb]'
                }`}
              >
                <div className="flex items-start gap-2 px-4 py-3">
                  <button
                    type="button"
                    onClick={() => handleSelectSession(session.session_id)}
                    disabled={isStreaming || deletingSessionId !== null}
                    className="min-w-0 flex-1 text-left disabled:cursor-not-allowed disabled:opacity-60"
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
                  <button
                    type="button"
                    onClick={() => void handleDeleteSession(session.session_id)}
                    disabled={isStreaming || deletingSessionId !== null}
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#ffb4ab]/10 text-[#ffb4ab] transition hover:bg-[#ffb4ab]/16 disabled:cursor-not-allowed disabled:opacity-60"
                    aria-label={`세션 ${session.session_id} 삭제`}
                  >
                    {isDeletingThisSession ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>
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
    <div className="dashboard-quantum flex h-full min-h-0 min-w-0 flex-col gap-5">
      <AIBankerPortfolioSnapshot onOpenSessions={() => setIsSidebarOpen(true)} />

      <div className="grid min-h-0 min-w-0 flex-1 gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="hidden min-h-0 lg:block">{sidebarContent}</aside>

        <section className="quantum-card flex min-h-0 min-w-0 flex-col rounded-xl text-[#dfe2eb]">
          <header className="flex items-center justify-between gap-4 border-b border-[#3b494b]/35 px-5 py-4">
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-[#00dbe9]">
                Conversation
              </p>
              <h2 className="mt-2 truncate text-lg font-bold text-[#dfe2eb]">
                {selectedSession ? '선택된 세션' : 'AI 뱅커 대기 중'}
              </h2>
              <p className="mt-1 truncate text-sm text-[#b9cacb]">
                {selectedSession?.session_id ??
                  '세션을 선택하거나 바로 질문을 입력하면 새 대화가 자동으로 생성됩니다.'}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {isStreaming && (
                <div className="hidden items-center gap-2 rounded-lg bg-[#00dbe9]/10 px-3 py-1.5 text-xs font-bold text-[#7df4ff] sm:inline-flex">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  응답 생성 중
                </div>
              )}
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto bg-[#0a0e14]/35 px-5 py-5">
            {!selectedSession && (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-[#3b494b]/50 bg-[#0a0e14]/70 px-6 text-center">
                <Sparkles className="h-10 w-10 text-[#00dbe9]" />
                <h3 className="mt-4 text-xl font-bold text-[#dfe2eb]">
                  새 대화를 시작하세요
                </h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-[#b9cacb]">
                  상단의 새 대화 버튼을 누르거나 바로 질문을 입력하면, AI 뱅커 전용 세션이 자동으로
                  생성됩니다.
                </p>
              </div>
            )}

            {selectedSession && showMessagesSkeleton && <MessageSkeleton />}

            {selectedSession && chatMessagesQuery.isError && !showMessagesSkeleton && (
              <div className="rounded-lg bg-[#ffb4ab]/10 px-5 py-4 text-sm font-medium text-[#ffdad6]">
                {resolveErrorMessage(chatMessagesQuery.error, '대화 이력을 불러오지 못했습니다.')}
              </div>
            )}

            {showEmptySelectedSession && (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-[#3b494b]/50 bg-[#0a0e14]/70 px-6 text-center">
                <MessageSquare className="h-10 w-10 text-[#00dbe9]" />
                <h3 className="mt-4 text-xl font-bold text-[#dfe2eb]">
                  아직 이 세션에 메시지가 없습니다
                </h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-[#b9cacb]">
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
                          className={`w-full max-w-2xl rounded-lg border px-4 py-3 text-sm ${resolveActivityCardClassName(
                            item.status,
                          )}`}
                        >
                          <button
                            type="button"
                            onClick={() => toggleActivityCard(item.key)}
                            className="flex w-full items-center justify-between gap-3 text-left"
                          >
                            <div className="flex min-w-0 items-center gap-3">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#0a0e14]">
                                {item.status === 'running' ? (
                                  <Loader2 className="h-4 w-4 animate-spin text-[#00dbe9]" />
                                ) : (
                                  <Check className="h-4 w-4 text-[#7df4ff]" />
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
                            <div className="shrink-0 rounded-lg bg-[#0a0e14]/70 p-1">
                              {item.isCollapsed ? (
                                <ChevronRight className="h-4 w-4" />
                              ) : (
                                <ChevronDown className="h-4 w-4" />
                              )}
                            </div>
                          </button>

                          {!item.isCollapsed && item.detailsText && (
                            <div className="mt-3 border-t border-[#3b494b]/45 pt-3 text-xs leading-6 text-[#b9cacb]">
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
                          <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#00dbe9]/12 text-[#7df4ff]">
                            <Sparkles className="h-4 w-4" aria-hidden="true" />
                          </div>
                          <div className="w-full rounded-lg rounded-bl-sm border border-[#eac324]/24 bg-[#eac324]/8 px-4 py-4 text-[#dfe2eb]">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#ffe179]">
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

                            <p className="mt-2 text-sm font-bold leading-6 text-[#dfe2eb]">
                              설정 변경 제안
                            </p>
                            <p className="mt-1 text-sm leading-6 text-[#b9cacb]">
                              Operations 에이전트가 아래 설정 변경을 제안했습니다.
                            </p>

                            <div className="mt-4 overflow-hidden rounded-lg bg-[#0a0e14]/70">
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-[#3b494b]/35 px-4 py-3 text-sm">
                                <span className="font-semibold text-[#b9cacb]">변경 대상 키</span>
                                <span className="break-all text-[#dfe2eb]">{item.configKey}</span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-[#3b494b]/35 px-4 py-3 text-sm">
                                <span className="font-semibold text-[#b9cacb]">현재값</span>
                                <span className="break-all text-[#dfe2eb]">
                                  {formatConfigValueLabel(displayedCurrentValue, systemConfigsQuery.isLoading)}
                                </span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] px-4 py-3 text-sm">
                                <span className="font-semibold text-[#b9cacb]">제안값</span>
                                <span className="break-all text-[#dfe2eb]">{item.proposedValue}</span>
                              </div>
                            </div>

                            {item.errorMessage && (
                              <div className="mt-3 rounded-lg bg-[#ffb4ab]/10 px-3 py-2 text-sm text-[#ffdad6]">
                                {item.errorMessage}
                              </div>
                            )}

                            <div className="mt-4 flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void handleApproveRequest(item.key)}
                                disabled={!canApprove || item.status === 'applying'}
                                className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#00dbe9] px-4 py-2.5 text-sm font-bold text-[#00363a] transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-[#262a31] disabled:text-[#849495]"
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
                                className="inline-flex items-center justify-center rounded-lg bg-[#262a31]/80 px-4 py-2.5 text-sm font-bold text-[#b9cacb] transition hover:bg-[#3b494b]/60 hover:text-[#dfe2eb] disabled:cursor-not-allowed disabled:opacity-60"
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
                        <div className="max-w-[82%] rounded-lg rounded-br-sm bg-[#00dbe9]/16 px-4 py-3 text-[#dfe2eb]">
                          <p className="whitespace-pre-wrap break-words text-sm leading-6">{item.content}</p>
                          <div className="mt-2 text-right text-[11px] font-medium text-[#7df4ff]">
                            {formatMessageTimestamp(item.createdAt)}
                          </div>
                        </div>
                      </div>
                    )
                  }

                  return (
                    <div key={item.key} className="flex justify-start">
                      <div className="flex max-w-[82%] items-start gap-3">
                        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#00dbe9]/12 text-[#7df4ff]">
                          <Sparkles className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <div className="rounded-lg rounded-bl-sm border border-[#3b494b]/30 bg-[#0a0e14]/88 px-4 py-3 text-[#dfe2eb]">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[#849495]">
                              {item.agentName ?? 'assistant'}
                            </span>
                            {item.isPending && (
                              <span className="inline-flex items-center gap-1 rounded-lg bg-[#00dbe9]/10 px-2 py-1 text-[11px] font-semibold text-[#7df4ff]">
                                <Loader2 className="h-3 w-3 animate-spin" />
                                작성 중
                              </span>
                            )}
                          </div>
                          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{item.content}</p>
                          <div className="mt-2 text-[11px] font-medium text-[#849495]">
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

          <div className="border-t border-[#3b494b]/35 px-5 py-4">
            {notice && (
              <div
                className={`mb-4 rounded-lg px-4 py-3 text-sm font-medium ${
                  notice.type === 'success'
                    ? 'bg-[#00dbe9]/10 text-[#7df4ff]'
                    : notice.type === 'info'
                      ? 'bg-[#262a31]/80 text-[#b9cacb]'
                      : 'bg-[#ffb4ab]/10 text-[#ffdad6]'
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
                className="w-full rounded-lg border border-[#3b494b] bg-[#0a0e14] px-4 py-3 text-sm text-[#dfe2eb] outline-none transition placeholder:text-[#849495] focus:border-[#00dbe9]/60 focus:ring-2 focus:ring-[#00dbe9]/15 disabled:cursor-not-allowed disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={isStreaming || draftMessage.trim().length === 0}
                className="inline-flex min-w-[132px] items-center justify-center gap-2 rounded-lg bg-[#00dbe9] px-4 py-3 text-sm font-bold text-[#00363a] transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-[#262a31] disabled:text-[#849495]"
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
