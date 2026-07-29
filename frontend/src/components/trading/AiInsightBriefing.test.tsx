// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AiInsightBriefing from './AiInsightBriefing'


const apiMocks = vi.hoisted(() => ({
  getBotStatus: vi.fn(),
  getLatestAiAnalysis: vi.fn(),
  runManualAiCycle: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)

function botStatus(
  mode: 'ARMED' | 'EXIT_ONLY' | 'BLOCK_ALL',
  tradingMode: 'paper' | 'live' = 'live',
  tradingModeAvailable = true,
) {
  return {
    running: true,
    live_order_mode: mode,
    live_order_rollout_enabled: true,
    live_order_state_available: true,
    trading_mode: tradingMode,
    trading_mode_version: 1,
    trading_mode_state_available: tradingModeAvailable,
    trading_mode_mirror_consistent: tradingModeAvailable,
  }
}

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>),
  }
}

describe('AiInsightBriefing manual trade gate', () => {
  beforeEach(() => {
    apiMocks.getLatestAiAnalysis.mockResolvedValue(null)
    apiMocks.runManualAiCycle.mockResolvedValue({
      symbol: 'KRW-BTC',
      analysis: {
        id: 1,
        symbol: 'KRW-BTC',
        decision: 'HOLD',
        confidence: 50,
        recommended_weight: 0,
        reasoning: '분석 완료',
        created_at: '2026-07-10T00:00:00Z',
      },
      trade_evaluated: false,
      order_created: false,
      order_id: null,
      order_intent_id: null,
      order_side: null,
      submission_status: null,
      exchange_state: null,
      message: '분석 완료',
      started_at: '2026-07-10T00:00:00Z',
      finished_at: '2026-07-10T00:00:01Z',
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    Object.values(apiMocks).forEach((mock) => mock.mockReset())
  })

  it.each(['BLOCK_ALL', 'EXIT_ONLY'] as const)(
    '%s에서는 Gemini/AI 분석만 실행하고 manual trade를 요청하지 않는다',
    async (mode) => {
      apiMocks.getBotStatus.mockResolvedValue(botStatus(mode))

      renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
      fireEvent.click(await screen.findByRole('button', { name: 'AI 분석만 실행' }))

      await waitFor(() =>
        expect(apiMocks.runManualAiCycle).toHaveBeenCalledWith('KRW-BTC', false),
      )
      expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('분석만 실행'))
    },
  )

  it('정상 live와 ARMED에서는 분석과 실거래 평가를 함께 요청한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(botStatus('ARMED'))

    renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
    fireEvent.click(await screen.findByRole('button', { name: 'AI 분석 + 실거래 평가' }))

    await waitFor(() =>
      expect(apiMocks.runManualAiCycle).toHaveBeenCalledWith('KRW-BTC', true),
    )
  })

  it.each([
    ['PREPARED', null, '주문 확인 중'],
    ['SUBMITTING', null, '주문 확인 중'],
    ['UNKNOWN', null, '주문 확인 중'],
    ['ACCEPTED', 'done', '주문 접수 완료 · 거래소 처리 완료'],
  ] as const)(
    '%s 주문 상태는 체결 성공으로 표시하지 않는다',
    async (submissionStatus, exchangeState, expectedMessage) => {
      apiMocks.getBotStatus.mockResolvedValue(botStatus('ARMED'))
      apiMocks.runManualAiCycle.mockResolvedValue({
        symbol: 'KRW-BTC',
        analysis: {
          id: 2,
          symbol: 'KRW-BTC',
          decision: 'BUY',
          confidence: 80,
          recommended_weight: 10,
          reasoning: '분석 완료',
          created_at: '2026-07-10T00:00:00Z',
        },
        trade_evaluated: true,
        order_created: true,
        order_id: null,
        order_intent_id: 17,
        order_side: 'BUY',
        submission_status: submissionStatus,
        exchange_state: exchangeState,
        message: expectedMessage,
        started_at: '2026-07-10T00:00:00Z',
        finished_at: '2026-07-10T00:00:01Z',
      })

      renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
      fireEvent.click(await screen.findByRole('button', { name: 'AI 분석 + 실거래 평가' }))

      const feedback = await screen.findByText(new RegExp(expectedMessage))
      expect(feedback.className).toContain('text-warning')
      expect(feedback.className).not.toContain('text-status-success')
    },
  )

  it('paper에서는 실주문 Gate와 무관하게 모의매매를 평가한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(botStatus('BLOCK_ALL', 'paper'))

    renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
    fireEvent.click(await screen.findByRole('button', { name: 'AI 분석 + 모의매매' }))

    await waitFor(() =>
      expect(apiMocks.runManualAiCycle).toHaveBeenCalledWith('KRW-BTC', true),
    )
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('PAPER 모의매매'))
  })

  it('paper라도 런타임이 정지되어 있으면 기존 정책대로 분석만 실행한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue({
      ...botStatus('BLOCK_ALL', 'paper'),
      running: false,
    })

    renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
    fireEvent.click(await screen.findByRole('button', { name: 'AI 분석만 실행' }))

    await waitFor(() =>
      expect(apiMocks.runManualAiCycle).toHaveBeenCalledWith('KRW-BTC', false),
    )
  })

  it('거래 모드 unavailable은 live로 간주하지 않고 분석만 실행한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(botStatus('ARMED', 'live', false))

    renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
    fireEvent.click(await screen.findByRole('button', { name: 'AI 분석만 실행' }))

    await waitFor(() =>
      expect(apiMocks.runManualAiCycle).toHaveBeenCalledWith('KRW-BTC', false),
    )
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('안전하게 확인할 수 없습니다'))
  })

  it('정상 live 뒤 status polling이 실패하면 stale ARMED를 사용하지 않고 분석만 실행한다', async () => {
    apiMocks.getBotStatus
      .mockResolvedValueOnce(botStatus('ARMED'))
      .mockRejectedValue(new Error('status polling failed'))

    const { queryClient } = renderWithQueryClient(<AiInsightBriefing symbol="KRW-BTC" />)
    expect(await screen.findByRole('button', { name: 'AI 분석 + 실거래 평가' })).toBeTruthy()

    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['bot-status'] })
    })

    const analysisOnlyButton = await screen.findByRole('button', { name: 'AI 분석만 실행' })
    fireEvent.click(analysisOnlyButton)
    await waitFor(() =>
      expect(apiMocks.runManualAiCycle).toHaveBeenCalledWith('KRW-BTC', false),
    )
  })
})
