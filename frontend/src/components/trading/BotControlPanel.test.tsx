// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AxiosError } from 'axios'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BotControlPanel from './BotControlPanel'


const apiMocks = vi.hoisted(() => ({
  armLiveOrderGate: vi.fn(),
  blockLiveOrderGate: vi.fn(),
  enableLiveTrading: vi.fn(),
  enablePaperTrading: vi.fn(),
  getBotStatus: vi.fn(),
  getTradingMode: vi.fn(),
  reauthAdminForLiveTrading: vi.fn(),
  requestAdminToken: vi.fn(),
  startBot: vi.fn(),
  stopBot: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)

function modeStatus(overrides: Record<string, unknown> = {}) {
  return {
    mode: 'live',
    version: 5,
    reason_code: 'OPERATOR_LIVE',
    reason: '관리자가 live 거래 모드를 확인했습니다.',
    source: 'REST',
    actor_ref: 'admin',
    changed_at: '2026-07-11T00:00:00Z',
    state_available: true,
    mirror_consistent: true,
    unavailable_reason: null,
    ...overrides,
  }
}

function axiosResponseError(status: number): AxiosError {
  const error = new AxiosError(`HTTP ${status}`)
  Object.assign(error, {
    response: {
      status,
      data: {
        detail: {
          error_code: 'TRADING_MODE_STATUS_QUERY_FAILED',
          message: `HTTP ${status} after transition`,
        },
      },
    },
  })
  return error
}

function status(overrides: Record<string, unknown> = {}) {
  return {
    running: true,
    last_heartbeat: null,
    last_error: null,
    latest_action: '분석 중',
    live_order_mode: 'BLOCK_ALL',
    live_order_generation: 3,
    live_order_version: 7,
    live_order_reason_code: 'OPERATOR_BLOCK',
    live_order_reason: '운영자가 실주문을 차단했습니다.',
    live_order_source: 'REST',
    live_order_changed_at: '2026-07-10T00:00:00Z',
    live_order_active_liquidation_operation_id: null,
    live_order_rollout_enabled: true,
    live_order_state_available: true,
    trading_mode: 'live',
    trading_mode_version: 5,
    trading_mode_reason_code: 'OPERATOR_LIVE',
    trading_mode_reason: '관리자가 live 거래 모드를 확인했습니다.',
    trading_mode_source: 'REST',
    trading_mode_actor_ref: 'admin',
    trading_mode_changed_at: '2026-07-11T00:00:00Z',
    trading_mode_state_available: true,
    trading_mode_mirror_consistent: true,
    trading_mode_unavailable_reason: null,
    ...overrides,
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

describe('BotControlPanel 실주문 Gate 제어', () => {
  beforeEach(() => {
    apiMocks.getBotStatus.mockResolvedValue(status())
    apiMocks.getTradingMode.mockResolvedValue(modeStatus())
    apiMocks.requestAdminToken.mockResolvedValue('one-time-admin-token')
    apiMocks.reauthAdminForLiveTrading.mockResolvedValue({
      reauth_proof: 'reauth-proof',
      expires_at: '2026-07-11T00:05:00Z',
    })
    vi.stubGlobal('crypto', {
      randomUUID: () => '11111111-1111-4111-8111-111111111111',
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    Object.values(apiMocks).forEach((mock) => mock.mockReset())
  })

  it('런타임과 주문 Gate 상태를 분리해 표시한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(
      status({
        running: false,
        live_order_mode: 'EXIT_ONLY',
        live_order_active_liquidation_operation_id: 19,
      }),
    )

    renderWithQueryClient(<BotControlPanel />)

    expect(await screen.findByText('EXIT_ONLY')).toBeTruthy()
    expect(screen.getByText('STOPPED')).toBeTruthy()
    expect(screen.getByText('LIVE')).toBeTruthy()
    expect(screen.getByText('#19')).toBeTruthy()
    expect((screen.getByRole('button', { name: '봇 정지' }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  })

  it('start는 런타임만 시작하고 arm API를 호출하지 않는다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(status({ running: false }))
    apiMocks.startBot.mockResolvedValue(status({ running: true }))

    renderWithQueryClient(<BotControlPanel />)
    const startButton = await screen.findByRole('button', { name: '봇 가동' })
    await waitFor(() => expect((startButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(startButton)

    await waitFor(() => expect(apiMocks.startBot).toHaveBeenCalledTimes(1))
    expect(apiMocks.armLiveOrderGate).not.toHaveBeenCalled()
    expect(await screen.findByText(/자동 재무장하지 않았습니다/)).toBeTruthy()
  })

  it('재무장 확인을 focus trap modal로 열고 Escape 시 트리거로 복귀한다', async () => {
    renderWithQueryClient(<BotControlPanel />)
    const armButton = await screen.findByRole('button', { name: '실주문 재무장' })
    await waitFor(() => expect((armButton as HTMLButtonElement).disabled).toBe(false))

    fireEvent.click(armButton)

    expect(await screen.findByRole('dialog', { name: '실주문 Gate 재무장' })).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByLabelText('운영 사유 (10자 이상)'))

    fireEvent.keyDown(document, { key: 'Escape' })

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '실주문 Gate 재무장' })).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(armButton))
  })

  it.each([
    ['네트워크 응답 유실', new AxiosError('network error')],
    ['HTTP 503', axiosResponseError(503)],
  ])('%s 뒤 arm은 동일 UUID와 동일 payload로 재시도한다', async (_case, firstError) => {
    apiMocks.armLiveOrderGate.mockRejectedValueOnce(firstError).mockResolvedValueOnce({
      mode: 'ARMED',
      generation: 4,
      version: 8,
      reason_code: 'OPERATOR_ARM',
      reason: '운영자가 안전 상태를 모두 확인했습니다.',
      source: 'REST',
      changed_at: '2026-07-10T00:01:00Z',
      active_liquidation_operation_id: null,
      rollout_enabled: true,
      state_available: true,
    })

    renderWithQueryClient(<BotControlPanel />)
    const armButton = await screen.findByRole('button', { name: '실주문 재무장' })
    await waitFor(() => expect((armButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(armButton)
    fireEvent.change(screen.getByLabelText('운영 사유 (10자 이상)'), {
      target: { value: '운영자가 안전 상태를 모두 확인했습니다.' },
    })
    fireEvent.change(screen.getByLabelText('확인 문구: ENABLE_LIVE_ORDERS'), {
      target: { value: 'ENABLE_LIVE_ORDERS' },
    })
    fireEvent.click(screen.getByRole('button', { name: '재무장 승인' }))

    await waitFor(() => expect(apiMocks.armLiveOrderGate).toHaveBeenCalledTimes(1))
    const firstCall = apiMocks.armLiveOrderGate.mock.calls[0]
    expect(firstCall[1]).toBe('11111111-1111-4111-8111-111111111111')
    expect(await screen.findByText(/같은 Idempotency-Key로만 재시도합니다/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '동일 키로 재시도' }))

    await waitFor(() => expect(apiMocks.armLiveOrderGate).toHaveBeenCalledTimes(2))
    const secondCall = apiMocks.armLiveOrderGate.mock.calls[1]
    expect(secondCall).toEqual(firstCall)
    expect(await screen.findByText(/ARMED로 재무장했습니다/)).toBeTruthy()
  })

  it('stop drain pending이면 차단 적용을 알리고 상태 재확인 버튼을 유지한다', async () => {
    apiMocks.getBotStatus
      .mockResolvedValueOnce(status())
      .mockResolvedValue(status({ running: false, live_order_mode: 'BLOCK_ALL' }))
    const drainError = new AxiosError('drain pending')
    Object.assign(drainError, {
      response: {
        status: 503,
        data: {
          detail: {
            error_code: 'ORDER_GATE_DRAIN_PENDING',
            message: 'SUBMITTING 주문 확인 중',
          },
        },
      },
    })
    apiMocks.stopBot
      .mockRejectedValueOnce(drainError)
      .mockResolvedValueOnce(status({ running: false, live_order_mode: 'BLOCK_ALL' }))

    renderWithQueryClient(<BotControlPanel />)
    const stopButton = await screen.findByRole('button', { name: '봇 정지' })
    await waitFor(() => expect((stopButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(stopButton)

    expect(await screen.findByText(/BLOCK_ALL은 적용됐습니다/)).toBeTruthy()
    const retryButton = screen.getByRole('button', { name: '정지 상태 재확인' })
    expect((retryButton as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(retryButton)

    await waitFor(() => expect(apiMocks.stopBot).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/BLOCK_ALL.*완료되었습니다/)).toBeTruthy()
    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: '봇 정지' }) as HTMLButtonElement).disabled,
      ).toBe(true),
    )
  })

  it('block drain pending이면 동일 idempotency key 재확인을 유지한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(status({ live_order_mode: 'ARMED' }))
    vi.spyOn(window, 'prompt').mockReturnValue('운영자가 미확정 제출 확인을 위해 즉시 차단합니다.')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const drainError = new AxiosError('drain pending')
    Object.assign(drainError, {
      response: {
        status: 503,
        data: {
          detail: {
            error_code: 'ORDER_GATE_DRAIN_PENDING',
            message: 'SUBMITTING 주문 확인 중',
          },
        },
      },
    })
    apiMocks.blockLiveOrderGate.mockRejectedValueOnce(drainError).mockResolvedValueOnce({
      mode: 'BLOCK_ALL',
      generation: 4,
      version: 8,
      reason_code: 'OPERATOR_BLOCK',
      reason: '운영자가 미확정 제출 확인을 위해 즉시 차단합니다.',
      source: 'REST',
      changed_at: '2026-07-10T00:02:00Z',
      active_liquidation_operation_id: null,
      rollout_enabled: true,
      state_available: true,
    })

    renderWithQueryClient(<BotControlPanel />)
    const blockButton = await screen.findByRole('button', { name: '실주문 즉시 차단' })
    await waitFor(() => expect((blockButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(blockButton)

    expect(await screen.findByText(/동일 차단 키로 다시 확인/)).toBeTruthy()
    const retryButton = screen.getByRole('button', { name: '동일 차단 재확인' })
    fireEvent.click(retryButton)

    await waitFor(() => expect(apiMocks.blockLiveOrderGate).toHaveBeenCalledTimes(2))
    expect(apiMocks.blockLiveOrderGate.mock.calls[1]).toEqual(
      apiMocks.blockLiveOrderGate.mock.calls[0],
    )
  })

  it('거래 모드가 unavailable이면 live fallback과 Gate 재무장을 차단한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(
      status({
        trading_mode: 'paper',
        trading_mode_state_available: false,
        trading_mode_mirror_consistent: false,
        trading_mode_unavailable_reason: 'legacy mirror mismatch',
      }),
    )
    apiMocks.getTradingMode.mockResolvedValue(
      modeStatus({
        mode: 'paper',
        state_available: false,
        mirror_consistent: false,
        unavailable_reason: 'legacy mirror mismatch',
      }),
    )

    renderWithQueryClient(<BotControlPanel />)

    expect(await screen.findByText('UNAVAILABLE')).toBeTruthy()
    expect(screen.getByText(/live로 간주하지 않으며 실주문을 차단/)).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: '실주문 재무장' }) as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(
      (screen.getByRole('button', { name: 'LIVE 모드 전환' }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it('정상 live 조회 뒤 polling이 실패하면 stale live를 폐기하고 Gate 재무장을 차단한다', async () => {
    apiMocks.getBotStatus
      .mockResolvedValueOnce(status())
      .mockRejectedValue(new Error('status polling failed'))

    const { queryClient } = renderWithQueryClient(<BotControlPanel />)
    expect(await screen.findByText('LIVE')).toBeTruthy()
    const armButton = screen.getByRole('button', { name: '실주문 재무장' })
    await waitFor(() => expect((armButton as HTMLButtonElement).disabled).toBe(false))

    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['bot-status'] })
    })

    await waitFor(() => expect(screen.getByText('UNAVAILABLE')).toBeTruthy())
    expect((armButton as HTMLButtonElement).disabled).toBe(true)
  })

  it.each([
    ['network error', new AxiosError('network error')],
    ['HTTP 503', axiosResponseError(503)],
  ])('%s 뒤 live 전환은 동일 proof, key, payload로 재시도한다', async (_case, firstError) => {
    apiMocks.getBotStatus.mockResolvedValue(
      status({
        running: false,
        trading_mode: 'paper',
        trading_mode_reason_code: 'DEFAULT_PAPER',
        trading_mode_reason: '안전 기본 모드입니다.',
      }),
    )
    apiMocks.getTradingMode.mockResolvedValue(
      modeStatus({
        mode: 'paper',
        reason_code: 'DEFAULT_PAPER',
        reason: '안전 기본 모드입니다.',
      }),
    )
    apiMocks.enableLiveTrading
      .mockRejectedValueOnce(firstError)
      .mockResolvedValueOnce(modeStatus())

    renderWithQueryClient(<BotControlPanel />)
    const liveButton = await screen.findByRole('button', { name: 'LIVE 모드 전환' })
    await waitFor(() => expect((liveButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(liveButton)
    fireEvent.change(screen.getByLabelText('운영 사유 (10자 이상)'), {
      target: { value: '운영자가 모든 안전 조건을 직접 확인했습니다.' },
    })
    fireEvent.change(screen.getByLabelText('확인 문구: ENABLE_LIVE_TRADING'), {
      target: { value: 'ENABLE_LIVE_TRADING' },
    })
    fireEvent.click(screen.getByRole('button', { name: '재인증 후 LIVE 전환' }))

    await waitFor(() => expect(apiMocks.enableLiveTrading).toHaveBeenCalledTimes(1))
    expect(apiMocks.requestAdminToken).toHaveBeenCalledWith('live 거래 모드 전환 재인증', {
      forcePrompt: true,
      persistent: false,
    })
    expect(apiMocks.reauthAdminForLiveTrading).toHaveBeenCalledWith('one-time-admin-token')
    const firstCall = apiMocks.enableLiveTrading.mock.calls[0]
    expect(firstCall).toEqual([
      {
        expected_version: 5,
        expected_gate_generation: 3,
        expected_gate_version: 7,
        reason: '운영자가 모든 안전 조건을 직접 확인했습니다.',
        confirmation: 'ENABLE_LIVE_TRADING',
        reauth_proof: 'reauth-proof',
      },
      '11111111-1111-4111-8111-111111111111',
      'one-time-admin-token',
    ])

    fireEvent.click(await screen.findByRole('button', { name: '동일 요청 재시도' }))
    await waitFor(() => expect(apiMocks.enableLiveTrading).toHaveBeenCalledTimes(2))
    expect(apiMocks.enableLiveTrading.mock.calls[1]).toEqual(firstCall)
    expect(apiMocks.requestAdminToken).toHaveBeenCalledTimes(2)
    expect(apiMocks.reauthAdminForLiveTrading).toHaveBeenCalledTimes(1)
    expect(apiMocks.startBot).not.toHaveBeenCalled()
    expect(apiMocks.armLiveOrderGate).not.toHaveBeenCalled()
    expect(await screen.findByText(/런타임 시작과 Gate 재무장은 별도로/)).toBeTruthy()
  })

  it('paper 전환도 HTTP 503 뒤 동일 key와 payload로 재시도한다', async () => {
    apiMocks.enablePaperTrading
      .mockRejectedValueOnce(axiosResponseError(503))
      .mockResolvedValueOnce(
        modeStatus({
          mode: 'paper',
          version: 6,
          reason_code: 'OPERATOR_PAPER',
          reason: '안전 모드로 복귀합니다.',
        }),
      )

    renderWithQueryClient(<BotControlPanel />)
    const paperButton = await screen.findByRole('button', { name: 'PAPER 모드 전환' })
    await waitFor(() => expect((paperButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(paperButton)
    fireEvent.change(screen.getByLabelText('운영 사유 (10자 이상)'), {
      target: { value: '실거래 운영을 종료하고 안전 모드로 복귀합니다.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'PAPER 전환' }))

    await waitFor(() => expect(apiMocks.enablePaperTrading).toHaveBeenCalledTimes(1))
    const firstCall = apiMocks.enablePaperTrading.mock.calls[0]
    expect(firstCall).toEqual([
      {
        expected_version: 5,
        reason: '실거래 운영을 종료하고 안전 모드로 복귀합니다.',
      },
      '11111111-1111-4111-8111-111111111111',
    ])
    fireEvent.click(await screen.findByRole('button', { name: '동일 요청 재시도' }))
    await waitFor(() => expect(apiMocks.enablePaperTrading).toHaveBeenCalledTimes(2))
    expect(apiMocks.enablePaperTrading.mock.calls[1]).toEqual(firstCall)
    expect(apiMocks.reauthAdminForLiveTrading).not.toHaveBeenCalled()
    expect(apiMocks.startBot).not.toHaveBeenCalled()
    expect(apiMocks.stopBot).not.toHaveBeenCalled()
    expect(apiMocks.armLiveOrderGate).not.toHaveBeenCalled()
  })
})
