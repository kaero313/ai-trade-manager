// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AIChatPage from './AIChatPage'

const mocks = vi.hoisted(() => ({
  approveChatConfigChange: vi.fn(),
  createChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  getChatMessages: vi.fn(),
  getChatSessions: vi.fn(),
  streamChatMessage: vi.fn(),
  usePortfolioSummary: vi.fn(),
  systemConfigRefetch: vi.fn(),
}))

vi.mock('../services/api', () => ({
  approveChatConfigChange: mocks.approveChatConfigChange,
  createChatSession: mocks.createChatSession,
  deleteChatSession: mocks.deleteChatSession,
  getChatMessages: mocks.getChatMessages,
  getChatSessions: mocks.getChatSessions,
  streamChatMessage: mocks.streamChatMessage,
}))

vi.mock('../hooks/usePortfolioSummary', () => ({
  usePortfolioSummary: mocks.usePortfolioSummary,
}))

vi.mock('../hooks/useSystemConfigs', () => ({
  SYSTEM_CONFIGS_QUERY_KEY: ['system-configs'],
  useSystemConfigs: () => ({
    isLoading: false,
    refetch: mocks.systemConfigRefetch,
  }),
}))

vi.mock('../components/common/AIBankerPortfolioSnapshot', () => ({
  default: () => <div data-testid="portfolio-snapshot" />,
}))

const LIVE_PORTFOLIO = {
  total_net_worth: 1_000_000,
  total_pnl: 10_000,
  items: [],
  source: 'live' as const,
  is_stale: false,
  updated_at: '2026-07-15T00:00:00Z',
}

const EMPTY_PORTFOLIO = {
  total_net_worth: 0,
  total_pnl: 0,
  items: [],
  source: 'empty' as const,
  is_stale: true,
  updated_at: null,
  error: 'PORTFOLIO_UNAVAILABLE',
}

function portfolioQuery(data: typeof LIVE_PORTFOLIO | typeof EMPTY_PORTFOLIO | undefined) {
  return {
    data,
    error: null,
    isError: false,
    isLoading: data === undefined,
    isRefetchError: false,
    isFetching: false,
    refetch: vi.fn(),
  }
}

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  const view = render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>)
  return {
    ...view,
    rerenderWithClient: (nextChildren: ReactNode) =>
      view.rerender(<QueryClientProvider client={queryClient}>{nextChildren}</QueryClientProvider>),
  }
}

async function selectExistingSession() {
  fireEvent.click(await screen.findByText('기존 대화'))
  await waitFor(() => expect(mocks.getChatMessages).toHaveBeenCalledWith('session-1'))
}

async function sendMessage(message = '설정을 검토해줘') {
  const textbox = screen.getByRole('textbox', { name: 'AI 뱅커에게 보낼 메시지' })
  fireEvent.change(textbox, { target: { value: message } })
  fireEvent.click(screen.getByRole('button', { name: '전송' }))
  await waitFor(() => expect(mocks.streamChatMessage).toHaveBeenCalledTimes(1))
}

function approvalStream(payload: Record<string, unknown>) {
  mocks.streamChatMessage.mockImplementation(
    async (_sessionId: string, _message: string, onEvent: (event: unknown) => void) => {
      onEvent({ type: 'agent_start', agent_name: 'Operations', content: '' })
      onEvent({
        type: 'approval_request',
        agent_name: 'Operations',
        content: JSON.stringify(payload),
      })
      onEvent({ type: 'agent_end', agent_name: 'Operations', content: '제안 준비 완료' })
    },
  )
}

function makeAxiosLikeError(status: number, detail: unknown) {
  return {
    isAxiosError: true,
    message: 'request failed',
    response: {
      status,
      data: { detail },
    },
  }
}

describe('AIChatPage 안전 계약', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    mocks.usePortfolioSummary.mockReturnValue(portfolioQuery(LIVE_PORTFOLIO))
    mocks.getChatSessions.mockResolvedValue([
      {
        session_id: 'session-1',
        last_message_preview: '기존 대화',
        last_activity: '2026-07-15T00:00:00Z',
      },
    ])
    mocks.getChatMessages.mockResolvedValue([
      {
        id: 1,
        session_id: 'session-1',
        role: 'assistant',
        content: '저장된 답변',
        agent_name: 'Portfolio',
        is_tool_call: false,
        created_at: '2026-07-15T00:00:00Z',
      },
    ])
    mocks.createChatSession.mockResolvedValue({ session_id: 'new-session' })
    mocks.approveChatConfigChange.mockResolvedValue([
      {
        id: 1,
        config_key: 'max_position_pct',
        config_value: '35',
        description: null,
        version: 10,
      },
    ])
    mocks.systemConfigRefetch.mockResolvedValue(undefined)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('제안 시점 current_value와 expected_version을 표시하고 exact 값으로 승인한다', async () => {
    approvalStream({
      action: 'config_change',
      config_key: 'max_position_pct',
      new_value: '35',
      current_value: '20',
      expected_version: 9,
      requires_approval: true,
    })

    renderWithQueryClient(<AIChatPage />)
    await selectExistingSession()
    await sendMessage()

    expect(await screen.findByText('설정 변경 제안')).toBeTruthy()
    expect(screen.getByText('20')).toBeTruthy()
    expect(screen.getByText('9')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '승인' }))

    await waitFor(() =>
      expect(mocks.approveChatConfigChange).toHaveBeenCalledWith('session-1', {
        config_key: 'max_position_pct',
        config_value: '35',
        expected_version: 9,
      }),
    )
  })

  it('trading_mode 제안은 전용 제어 안내만 표시하고 승인 API를 호출하지 않는다', async () => {
    approvalStream({
      action: 'config_change',
      config_key: 'trading_mode',
      new_value: 'live',
      current_value: 'paper',
      expected_version: 3,
      requires_approval: true,
    })

    renderWithQueryClient(<AIChatPage />)
    await selectExistingSession()
    await sendMessage('거래 모드를 변경해줘')

    expect(await screen.findByText(/거래 모드는 AI Banker 설정 승인으로 변경할 수 없습니다/)).toBeTruthy()
    expect((screen.getByRole('button', { name: '승인' }) as HTMLButtonElement).disabled).toBe(true)
    expect(mocks.approveChatConfigChange).not.toHaveBeenCalled()
  })

  it('409 충돌과 저장된 503 runtime 실패를 서로 다른 상태로 표시한다', async () => {
    approvalStream({
      action: 'config_change',
      config_key: 'max_position_pct',
      new_value: '35',
      current_value: '20',
      expected_version: 9,
      requires_approval: true,
    })
    mocks.approveChatConfigChange
      .mockRejectedValueOnce(makeAxiosLikeError(409, 'version conflict'))
      .mockRejectedValueOnce(
        makeAxiosLikeError(503, {
          saved: true,
          message: '설정은 저장됐지만 runtime 반영에 실패했습니다.',
        }),
      )

    renderWithQueryClient(<AIChatPage />)
    await selectExistingSession()
    await sendMessage()

    fireEvent.click(await screen.findByRole('button', { name: '승인' }))
    expect(await screen.findByText('최신값 충돌')).toBeTruthy()
    expect(screen.queryByText('저장됨·반영 실패')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '거부' }))
    await sendMessage('같은 설정을 다시 검토해줘')
    const approvals = await screen.findAllByRole('button', { name: '승인' })
    fireEvent.click(approvals.at(-1) as HTMLButtonElement)

    expect(await screen.findByText('저장됨·반영 실패')).toBeTruthy()
    expect((await screen.findAllByText(/최신 저장값을 다시 불러왔습니다/)).length).toBeGreaterThan(0)
  })

  it('포트폴리오 context가 unavailable이면 이력은 표시하지만 새 전송은 0회다', async () => {
    let currentPortfolioQuery = portfolioQuery(LIVE_PORTFOLIO)
    mocks.usePortfolioSummary.mockImplementation(() => currentPortfolioQuery)

    const view = renderWithQueryClient(<AIChatPage />)
    await selectExistingSession()
    expect(await screen.findByText('저장된 답변')).toBeTruthy()

    const textbox = screen.getByRole('textbox', { name: 'AI 뱅커에게 보낼 메시지' })
    fireEvent.change(textbox, { target: { value: '포트폴리오를 분석해줘' } })

    currentPortfolioQuery = portfolioQuery(EMPTY_PORTFOLIO)
    view.rerenderWithClient(<AIChatPage />)

    expect(screen.getByText('새 메시지 전송을 잠시 차단했습니다')).toBeTruthy()
    expect(screen.getByText('저장된 답변')).toBeTruthy()
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).disabled).toBe(true)
    fireEvent.submit(screen.getByRole('textbox').closest('form') as HTMLFormElement)

    expect(mocks.streamChatMessage).not.toHaveBeenCalled()
    expect(mocks.createChatSession).not.toHaveBeenCalled()
  })

  it('빠른 질문은 draft만 채우며 세션 생성이나 메시지 API를 호출하지 않는다', async () => {
    renderWithQueryClient(<AIChatPage />)

    const quickAction = await screen.findByRole('button', {
      name: '현재 포트폴리오의 핵심 위험을 요약해줘',
    })
    fireEvent.click(quickAction)

    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(
      '현재 포트폴리오의 핵심 위험을 요약해줘',
    )
    expect(mocks.createChatSession).not.toHaveBeenCalled()
    expect(mocks.streamChatMessage).not.toHaveBeenCalled()
  })

  it('정상 HTTP 안의 SSE error를 실행 중이 아닌 실패 상태로 종결한다', async () => {
    mocks.streamChatMessage.mockImplementation(
      async (_sessionId: string, _message: string, onEvent: (event: unknown) => void) => {
        onEvent({ type: 'agent_start', agent_name: 'Risk', content: '' })
        onEvent({ type: 'error', agent_name: 'system', content: 'internal exception' })
      },
    )

    renderWithQueryClient(<AIChatPage />)
    await selectExistingSession()
    await sendMessage('리스크를 다시 분석해줘')

    expect(
      (
        await screen.findAllByText(
          'AI 처리 중 오류가 발생해 응답을 완료하지 못했습니다. 다시 시도해 주세요.',
        )
      ).length,
    ).toBeGreaterThan(0)
    expect(screen.getByText(/ERROR \[Risk\] 응답이 중단되었습니다/)).toBeTruthy()
    expect(screen.queryByText('응답 생성 중')).toBeNull()
  })
})
