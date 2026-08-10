import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from '@headlessui/react'
import { isAxiosError } from 'axios'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  SendHorizontal,
  ShieldAlert,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import AIBankerPortfolioSnapshot from '../components/common/AIBankerPortfolioSnapshot'
import { MarkdownLite } from '../components/common/MarkdownLite'
import { usePortfolioSummary } from '../hooks/usePortfolioSummary'
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
import {
  resolvePortfolioDataState,
  resolvePortfolioUnavailableMessage,
} from './portfolioDataState'
import {
  type ConfigApprovalRequest,
  isTradingModeConfigKey,
  parseConfigApprovalRequest,
  TRADING_MODE_CONTROL_GUIDANCE,
} from './chatApprovalPolicy'

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
  expectedVersion: number | null
  status:
    | 'pending'
    | 'applying'
    | 'applied'
    | 'rejected'
    | 'failed'
    | 'conflict'
    | 'runtime_failed'
  errorMessage: string | null
}

type ChatRenderItem = ChatRenderMessageItem | ChatRenderActivityItem | ChatRenderApprovalItem

const CHAT_SESSIONS_QUERY_KEY = ['chat-sessions'] as const
const QUICK_ACTIONS = [
  '현재 포트폴리오의 핵심 위험을 요약해줘',
  '보유 자산 비중을 점검하고 개선 방향을 설명해줘',
  '최근 포트폴리오 상태를 이해하기 쉽게 설명해줘',
] as const

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
  payload: ConfigApprovalRequest,
): ChatRenderApprovalItem {
  return {
    kind: 'approval',
    key,
    agentName,
    configKey: payload.config_key,
    proposedValue: payload.new_value,
    currentValue: payload.current_value,
    expectedVersion: payload.expected_version,
    status: 'pending',
    errorMessage: null,
  }
}

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (
      detail &&
      typeof detail === 'object' &&
      'message' in detail &&
      typeof detail.message === 'string' &&
      detail.message.trim()
    ) {
      return detail.message
    }
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function isSavedButRuntimeApplyFailed(error: unknown): boolean {
  if (!isAxiosError(error) || error.response?.status !== 503) {
    return false
  }
  const detail = error.response.data?.detail
  return Boolean(detail && typeof detail === 'object' && 'saved' in detail && detail.saved === true)
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
      return 'border-brand/25 bg-brand/10 text-content'
    case 'failed':
      return 'border-status-danger/25 bg-status-danger/10 text-status-danger'
    default:
      return 'border-warning/25 bg-warning/10 text-warning'
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
    case 'conflict':
      return '최신값 충돌'
    case 'runtime_failed':
      return '저장됨·반영 실패'
    default:
      return '승인 대기'
  }
}

function resolveApprovalStatusClassName(status: ChatRenderApprovalItem['status']): string {
  switch (status) {
    case 'applying':
      return 'bg-brand/10 text-brand-bright'
    case 'applied':
      return 'bg-brand/10 text-brand-bright'
    case 'rejected':
      return 'bg-warning/10 text-warning'
    case 'failed':
      return 'bg-status-danger/10 text-status-danger'
    case 'conflict':
      return 'bg-status-danger/10 text-status-danger'
    case 'runtime_failed':
      return 'bg-status-danger/10 text-status-danger'
    default:
      return 'bg-surface-high text-content-secondary'
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
                ? 'border border-border-subtle bg-surface-lowest'
                : 'bg-brand/10'
            }`}
          >
            <div className="h-3 w-20 rounded bg-surface-high" />
            <div className="mt-3 h-3 w-64 rounded bg-surface-high" />
            <div className="mt-2 h-3 w-40 rounded bg-surface-high" />
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
  const portfolioQuery = usePortfolioSummary()
  const portfolioState = resolvePortfolioDataState({
    data: portfolioQuery.data,
    error: portfolioQuery.error,
    isError: portfolioQuery.isError,
    isLoading: portfolioQuery.isLoading,
    isRefetchError: portfolioQuery.isRefetchError,
  })
  const canSendNewMessage = portfolioState.canUseAiContext
  const portfolioUnavailableMessage =
    portfolioState.kind === 'loading'
      ? '포트폴리오를 확인하고 있습니다. 확인이 끝난 뒤 메시지를 보낼 수 있습니다.'
      : resolvePortfolioUnavailableMessage(portfolioState)

  const chatSessionsQuery = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: () => getChatSessions('ai_banker'),
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

  useEffect(() => {
    if (!isSidebarOpen || typeof window.matchMedia !== 'function') {
      return
    }

    const desktopQuery = window.matchMedia('(min-width: 1024px)')
    const closeOnDesktop = () => {
      if (desktopQuery.matches) {
        setIsSidebarOpen(false)
      }
    }
    closeOnDesktop()
    desktopQuery.addEventListener('change', closeOnDesktop)
    return () => desktopQuery.removeEventListener('change', closeOnDesktop)
  }, [isSidebarOpen])

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

    if (isTradingModeConfigKey(targetItem.configKey)) {
      setNotice({ type: 'info', message: TRADING_MODE_CONTROL_GUIDANCE })
      return
    }

    if (targetItem.expectedVersion === null) {
      await systemConfigsQuery.refetch()
      const errorMessage = '설정의 제안 시점 버전을 확인할 수 없어 승인하지 않았습니다. 최신 설정에서 다시 제안해 주세요.'
      setLiveItems((current) =>
        updateApprovalCardByKey(current, key, (item) => ({
          ...item,
          status: 'failed',
          errorMessage,
        })),
      )
      setNotice({ type: 'error', message: errorMessage })
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
        expected_version: targetItem.expectedVersion,
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
        message: `${targetItem.configKey} 설정을 저장했습니다. 실제 소비자는 다음 판단부터 새 값을 사용합니다.`,
      })
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 409) {
        await queryClient.invalidateQueries({ queryKey: SYSTEM_CONFIGS_QUERY_KEY })
        const errorMessage = '제안 이후 설정이 변경되어 승인하지 않았습니다. 최신값을 확인한 뒤 새 제안을 요청해 주세요.'
        setLiveItems((current) =>
          updateApprovalCardByKey(current, key, (item) => ({
            ...item,
            status: 'conflict',
            errorMessage,
          })),
        )
        setNotice({ type: 'error', message: errorMessage })
        return
      }
      if (isSavedButRuntimeApplyFailed(error)) {
        await queryClient.invalidateQueries({ queryKey: SYSTEM_CONFIGS_QUERY_KEY })
        const errorMessage = `${resolveErrorMessage(error, '설정은 저장됐지만 runtime 반영에 실패했습니다.')} 최신 저장값을 다시 불러왔습니다.`
        setLiveItems((current) =>
          updateApprovalCardByKey(current, key, (item) => ({
            ...item,
            status: 'runtime_failed',
            errorMessage,
          })),
        )
        setNotice({ type: 'error', message: errorMessage })
        return
      }
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

  const handleQuickAction = (message: string) => {
    if (!canSendNewMessage || isStreaming) {
      return
    }
    setDraftMessage(message)
    setNotice(null)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const normalizedMessage = draftMessage.trim()
    if (!normalizedMessage || isStreaming) {
      return
    }

    if (!canSendNewMessage) {
      setNotice({
        type: 'error',
        message: portfolioUnavailableMessage,
      })
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
          const approvalPayload = parseConfigApprovalRequest(streamEvent.content)

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

        if (streamEvent.type === 'error') {
          const errorMessage = 'AI 처리 중 오류가 발생해 응답을 완료하지 못했습니다. 다시 시도해 주세요.'
          setLiveItems((current) => finishRunningActivities(current, errorMessage))
          setNotice({ type: 'error', message: errorMessage })
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
    <div className="flex h-full min-h-0 flex-col rounded-2xl border border-border-subtle bg-surface text-content">
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-4">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-brand">
            AI Banker
          </p>
          <h2 className="mt-2 text-lg font-bold text-content">대화 세션</h2>
        </div>
        <button
          type="button"
          onClick={() => setIsSidebarOpen(false)}
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-border-strong text-content-secondary transition hover:bg-surface-high hover:text-content lg:hidden"
          aria-label="세션 사이드바 닫기"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="border-b border-border-subtle px-4 py-4">
        <button
          type="button"
          onClick={() => void handleCreateSession()}
          disabled={isCreatingSession || isStreaming || deletingSessionId !== null}
          className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-brand px-4 py-3 text-sm font-bold text-surface-lowest transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-surface-high disabled:text-content-muted"
        >
          {isCreatingSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          <span>{isCreatingSession ? '생성 중...' : '새 대화'}</span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {chatSessionsQuery.isLoading && (
          <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-content-secondary">
            <Loader2 className="h-4 w-4 animate-spin" />
            세션 목록을 불러오는 중입니다.
          </div>
        )}

        {chatSessionsQuery.isError && (
          <div className="rounded-lg bg-status-danger/10 px-4 py-3 text-sm font-medium text-status-danger">
            {resolveErrorMessage(chatSessionsQuery.error, '세션 목록을 불러오지 못했습니다.')}
          </div>
        )}

        {!chatSessionsQuery.isLoading && !chatSessionsQuery.isError && sessions.length === 0 && (
          <div className="rounded-lg border border-dashed border-border-strong bg-surface-lowest px-4 py-8 text-center text-sm text-content-muted">
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
                    ? 'border-brand/35 bg-brand/10 text-content'
                    : 'border-transparent bg-surface-lowest text-content-secondary hover:border-border-strong hover:bg-surface-high hover:text-content'
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
                    className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg bg-status-danger/10 text-status-danger transition hover:bg-status-danger/15 disabled:cursor-not-allowed disabled:opacity-60"
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

        <section className="flex min-h-[680px] min-w-0 flex-col overflow-hidden rounded-2xl border border-border-subtle bg-surface text-content lg:min-h-0">
          <header className="flex items-center justify-between gap-4 border-b border-border-subtle px-5 py-4 sm:px-6">
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-brand">
                Conversation
              </p>
              <h1 className="mt-2 truncate text-xl font-bold text-content">
                {selectedSession ? '선택된 세션' : 'AI 뱅커 대기 중'}
              </h1>
              <p className="mt-1 truncate text-sm text-content-secondary">
                {selectedSession?.session_id ??
                  '세션을 선택하거나 바로 질문을 입력하면 새 대화가 자동으로 생성됩니다.'}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {isStreaming && (
                <div className="hidden items-center gap-2 rounded-lg bg-brand/10 px-3 py-1.5 text-xs font-bold text-brand-bright sm:inline-flex" role="status">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  응답 생성 중
                </div>
              )}
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto bg-surface-lowest/45 px-5 py-5 sm:px-6 sm:py-6">
            {!selectedSession && (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface-lowest px-6 text-center">
                <Sparkles className="h-10 w-10 text-brand" />
                <h2 className="mt-4 text-xl font-bold text-content">
                  새 대화를 시작하세요
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
                  상단의 새 대화 버튼을 누르거나 바로 질문을 입력하면, AI 뱅커 전용 세션이 자동으로
                  생성됩니다.
                </p>
              </div>
            )}

            {selectedSession && showMessagesSkeleton && <MessageSkeleton />}

            {selectedSession && chatMessagesQuery.isError && !showMessagesSkeleton && (
              <div className="rounded-lg bg-status-danger/10 px-5 py-4 text-sm font-medium text-status-danger">
                {resolveErrorMessage(chatMessagesQuery.error, '대화 이력을 불러오지 못했습니다.')}
              </div>
            )}

            {showEmptySelectedSession && (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface-lowest px-6 text-center">
                <MessageSquare className="h-10 w-10 text-brand" />
                <h2 className="mt-4 text-xl font-bold text-content">
                  아직 이 세션에 메시지가 없습니다
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 text-content-secondary">
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
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-lowest">
                                {item.status === 'running' ? (
                                  <Loader2 className="h-4 w-4 animate-spin text-brand" />
                                ) : (
                                  <Check className="h-4 w-4 text-brand-bright" />
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
                            <div className="shrink-0 rounded-lg bg-surface-lowest p-1">
                              {item.isCollapsed ? (
                                <ChevronRight className="h-4 w-4" />
                              ) : (
                                <ChevronDown className="h-4 w-4" />
                              )}
                            </div>
                          </button>

                          {!item.isCollapsed && item.detailsText && (
                            <div className="mt-3 border-t border-border-subtle pt-3 text-xs leading-6 text-content-secondary">
                              <p className="font-semibold opacity-80">상세 로그</p>
                              <p className="mt-1 whitespace-pre-wrap break-words opacity-90">{item.detailsText}</p>
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  }

                  if (item.kind === 'approval') {
                    const displayedCurrentValue = item.currentValue
                    const isTradingModeApproval = isTradingModeConfigKey(item.configKey)
                    const canApprove =
                      !isTradingModeApproval &&
                      (item.status === 'pending' || item.status === 'failed')
                    const canReject =
                      item.status === 'pending' ||
                      item.status === 'failed' ||
                      item.status === 'conflict' ||
                      item.status === 'runtime_failed'

                    return (
                      <div key={item.key} className="flex justify-start">
                        <div className="flex max-w-[82%] items-start gap-3">
                          <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand/10 text-brand-bright">
                            <Sparkles className="h-4 w-4" aria-hidden="true" />
                          </div>
                          <div className="w-full rounded-lg rounded-bl-sm border border-warning/25 bg-warning/10 px-4 py-4 text-content">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-warning">
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

                            <p className="mt-2 text-sm font-bold leading-6 text-content">
                              설정 변경 제안
                            </p>
                            <p className="mt-1 text-sm leading-6 text-content-secondary">
                              Operations 에이전트가 아래 설정 변경을 제안했습니다.
                            </p>

                            <div className="mt-4 overflow-hidden rounded-lg bg-surface-lowest">
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-border-subtle px-4 py-3 text-sm">
                                <span className="font-semibold text-content-secondary">변경 대상 키</span>
                                <span className="break-all text-content">{item.configKey}</span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-border-subtle px-4 py-3 text-sm">
                                <span className="font-semibold text-content-secondary">현재값</span>
                                <span className="break-all text-content">
                                  {formatConfigValueLabel(displayedCurrentValue, systemConfigsQuery.isLoading)}
                                </span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-border-subtle px-4 py-3 text-sm">
                                <span className="font-semibold text-content-secondary">제안 기준 버전</span>
                                <span className="break-all text-content">
                                  {item.expectedVersion ?? '확인 불가'}
                                </span>
                              </div>
                              <div className="grid grid-cols-[120px_minmax(0,1fr)] px-4 py-3 text-sm">
                                <span className="font-semibold text-content-secondary">제안값</span>
                                <span className="break-all text-content">{item.proposedValue}</span>
                              </div>
                            </div>

                            {item.errorMessage && (
                              <div className="mt-3 rounded-lg bg-status-danger/10 px-3 py-2 text-sm text-status-danger">
                                {item.errorMessage}
                              </div>
                            )}

                            {isTradingModeApproval && (
                              <div className="mt-3 rounded-lg bg-warning/10 px-3 py-2 text-sm font-semibold leading-6 text-warning">
                                {TRADING_MODE_CONTROL_GUIDANCE}
                              </div>
                            )}

                            <div className="mt-4 flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void handleApproveRequest(item.key)}
                                disabled={!canApprove || item.status === 'applying'}
                                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-bold text-surface-lowest transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-surface-high disabled:text-content-muted"
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
                                className="inline-flex min-h-11 items-center justify-center rounded-lg bg-surface-high px-4 py-2.5 text-sm font-bold text-content-secondary transition hover:bg-surface-highest hover:text-content disabled:cursor-not-allowed disabled:opacity-60"
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
                        <div className="max-w-[82%] rounded-lg rounded-br-sm bg-brand/15 px-4 py-3 text-content">
                          <p className="whitespace-pre-wrap break-words text-sm leading-6">{item.content}</p>
                          <div className="mt-2 text-right text-[11px] font-medium text-brand-bright">
                            {formatMessageTimestamp(item.createdAt)}
                          </div>
                        </div>
                      </div>
                    )
                  }

                  return (
                    <div key={item.key} className="flex justify-start">
                      <div className="flex max-w-[82%] items-start gap-3">
                        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand/10 text-brand-bright">
                          <Sparkles className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <div className="rounded-lg rounded-bl-sm border border-border-subtle bg-surface-lowest px-4 py-3 text-content">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-content-muted">
                              {item.agentName ?? 'assistant'}
                            </span>
                            {item.isPending && (
                              <span className="inline-flex items-center gap-1 rounded-lg bg-brand/10 px-2 py-1 text-[11px] font-semibold text-brand-bright">
                                <Loader2 className="h-3 w-3 animate-spin" />
                                작성 중
                              </span>
                            )}
                          </div>
                          <MarkdownLite text={item.content} className="mt-2 text-sm leading-6" />
                          <div className="mt-2 text-[11px] font-medium text-content-muted">
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

          <div className="border-t border-border-subtle bg-surface px-5 py-4 sm:px-6">
            <div className="mb-3 flex gap-2 overflow-x-auto pb-1" aria-label="빠른 질문">
              {QUICK_ACTIONS.map((message) => (
                <button
                  key={message}
                  type="button"
                  onClick={() => handleQuickAction(message)}
                  disabled={!canSendNewMessage || isStreaming}
                  className="shrink-0 rounded-full border border-border-subtle bg-surface-lowest px-3 py-2 text-xs font-semibold text-content-secondary transition hover:border-border-strong hover:bg-surface-high hover:text-content disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {message}
                </button>
              ))}
            </div>

            {!canSendNewMessage ? (
              <div
                className="mb-4 flex flex-col gap-3 rounded-xl border border-warning/25 bg-warning/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                role="status"
              >
                <div className="flex min-w-0 items-start gap-3">
                  <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
                  <div>
                    <p className="text-sm font-bold text-content">새 메시지 전송을 잠시 차단했습니다</p>
                    <p className="mt-1 text-xs leading-5 text-content-secondary">
                      {portfolioUnavailableMessage}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void portfolioQuery.refetch()}
                  disabled={portfolioQuery.isFetching}
                  className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg border border-border-strong bg-surface-lowest px-4 py-2 text-sm font-bold text-content transition hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <RefreshCw
                    className={`h-4 w-4 ${portfolioQuery.isFetching ? 'animate-spin' : ''}`}
                    aria-hidden="true"
                  />
                  포트폴리오 다시 확인
                </button>
              </div>
            ) : null}

            {notice && (
              <div
                className={`mb-4 rounded-lg px-4 py-3 text-sm font-medium ${
                  notice.type === 'success'
                    ? 'bg-brand/10 text-brand-bright'
                    : notice.type === 'info'
                      ? 'bg-surface-high text-content-secondary'
                      : 'bg-status-danger/10 text-status-danger'
                }`}
                role="status"
              >
                {notice.message}
              </div>
            )}

            <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <label className="min-w-0 flex-1">
                <span className="sr-only">AI 뱅커에게 보낼 메시지</span>
                <textarea
                  value={draftMessage}
                  onChange={(event) => setDraftMessage(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                  placeholder="AI 뱅커에게 무엇이든 물어보세요..."
                  rows={2}
                  disabled={isStreaming || !canSendNewMessage}
                  className="max-h-36 min-h-[52px] w-full resize-y rounded-xl border border-border-strong bg-surface-lowest px-4 py-3 text-sm text-content outline-none transition placeholder:text-content-muted focus:border-brand focus:ring-2 focus:ring-focus-ring/20 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </label>
              <button
                type="submit"
                disabled={isStreaming || !canSendNewMessage || draftMessage.trim().length === 0}
                className="inline-flex min-h-[52px] min-w-[116px] items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 text-sm font-bold text-surface-lowest transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-surface-high disabled:text-content-muted"
              >
                {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
                <span>{isStreaming ? '전송 중...' : '전송'}</span>
              </button>
            </form>
          </div>
        </section>
      </div>

      <Dialog
        open={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        className="relative z-50"
      >
        <DialogBackdrop className="fixed inset-0 bg-surface-lowest/80 backdrop-blur-sm" />
        <div className="fixed inset-0 overflow-y-auto">
          <DialogPanel className="h-full w-[min(88vw,340px)] p-4 pt-20">
            <DialogTitle className="sr-only">대화 세션 목록</DialogTitle>
            {sidebarContent}
          </DialogPanel>
        </div>
      </Dialog>
    </div>
  )
}

export default AIChatPage
