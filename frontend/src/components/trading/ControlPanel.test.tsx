// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AxiosError } from 'axios'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ControlPanel from './ControlPanel'


const apiMocks = vi.hoisted(() => ({
  getBotStatus: vi.fn(),
  getLiquidation: vi.fn(),
  liquidateAll: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)

function botStatus(overrides: Record<string, unknown> = {}) {
  return {
    running: false,
    live_order_mode: 'BLOCK_ALL',
    live_order_generation: 3,
    live_order_version: 7,
    live_order_reason: '운영자 차단',
    live_order_rollout_enabled: true,
    live_order_state_available: true,
    trading_mode: 'live',
    trading_mode_version: 2,
    trading_mode_state_available: true,
    trading_mode_mirror_consistent: true,
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

async function clickNewLiquidationButton() {
  fireEvent.change(
    screen.getByLabelText('확인 문구: CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL'),
    { target: { value: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL' } },
  )
  const button = screen.getByRole('button', { name: '계정 전체 청산 시작' })
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(button)
}

describe('ControlPanel 전량 청산 멱등성 키', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('crypto', { randomUUID: () => '11111111-1111-4111-8111-111111111111' })
    apiMocks.getBotStatus.mockResolvedValue(botStatus())
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    apiMocks.getLiquidation.mockReset()
    apiMocks.liquidateAll.mockReset()
    apiMocks.getBotStatus.mockReset()
  })

  it('응답 유실 뒤 같은 Idempotency-Key로 재시도한다', async () => {
    apiMocks.liquidateAll
      .mockRejectedValueOnce(new AxiosError('network error'))
      .mockResolvedValueOnce({
        id: 7,
        idempotency_key: '11111111-1111-4111-8111-111111111111',
        status: 'IN_PROGRESS',
        items: [],
        created_at: '2026-07-10T00:00:00Z',
        updated_at: '2026-07-10T00:00:00Z',
        completed_at: null,
      })

    renderWithQueryClient(<ControlPanel />)
    await clickNewLiquidationButton()

    await waitFor(() => expect(apiMocks.liquidateAll).toHaveBeenCalledTimes(1))
    expect(apiMocks.liquidateAll).toHaveBeenLastCalledWith(
      '11111111-1111-4111-8111-111111111111',
      {
        scope: 'ACCOUNT_ALL',
        confirmation: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL',
      },
    )

    fireEvent.click(await screen.findByRole('button', { name: '동일 요청 재시도' }))

    await waitFor(() => expect(apiMocks.liquidateAll).toHaveBeenCalledTimes(2))
    expect(apiMocks.liquidateAll).toHaveBeenLastCalledWith(
      '11111111-1111-4111-8111-111111111111',
      {
        scope: 'ACCOUNT_ALL',
        confirmation: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL',
      },
    )
    expect(await screen.findByText(/청산 작업 #7: 상태 확인 단계가 진행 중/)).toBeTruthy()
  })

  it.each(['EMERGENCY_AUTH_REVOKED', 'ORDER_GATE_REQUEST_SUPERSEDED'])(
    '%s 청산 권한은 기존 키를 버리고 새 확인에서 새 UUID를 사용한다',
    async (errorCode) => {
      const randomUUID = vi
        .fn()
        .mockReturnValueOnce('11111111-1111-4111-8111-111111111111')
        .mockReturnValueOnce('22222222-2222-4222-8222-222222222222')
      vi.stubGlobal('crypto', { randomUUID })

      const revokedError = new AxiosError('authorization revoked')
      Object.assign(revokedError, {
        response: {
          status: 409,
          data: {
            detail: {
              error_code: errorCode,
              message: '청산 권한이 폐기되었습니다.',
            },
          },
        },
      })
      apiMocks.liquidateAll.mockRejectedValueOnce(revokedError).mockResolvedValueOnce({
        id: 8,
        idempotency_key: '22222222-2222-4222-8222-222222222222',
        status: 'IN_PROGRESS',
        items: [],
        created_at: '2026-07-10T00:00:00Z',
        updated_at: '2026-07-10T00:00:00Z',
        completed_at: null,
      })

      renderWithQueryClient(<ControlPanel />)
      await clickNewLiquidationButton()

      expect(
        await screen.findByText(/같은 요청 키를 더 이상 사용하지 않습니다/),
      ).toBeTruthy()
      expect(apiMocks.liquidateAll).toHaveBeenLastCalledWith(
        '11111111-1111-4111-8111-111111111111',
        {
          scope: 'ACCOUNT_ALL',
          confirmation: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL',
        },
      )

      fireEvent.change(
        screen.getByLabelText('확인 문구: CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL'),
        { target: { value: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL' } },
      )
      fireEvent.click(screen.getByRole('button', { name: '새 청산 요청 (새 UUID)' }))

      await waitFor(() => expect(apiMocks.liquidateAll).toHaveBeenCalledTimes(2))
      expect(apiMocks.liquidateAll).toHaveBeenLastCalledWith(
        '22222222-2222-4222-8222-222222222222',
        {
          scope: 'ACCOUNT_ALL',
          confirmation: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL',
        },
      )
      expect(window.confirm).toHaveBeenLastCalledWith(expect.stringContaining('수동·외부'))
    },
  )

  it.each(['ORDER_GATE_GENERATION_CONFLICT', 'ACTIVE_LIQUIDATION_EXISTS'])(
    '%s 충돌이면 서버가 반환한 활성 operation으로 전환한다',
    async (errorCode) => {
      const activeOperation = {
        id: 9,
        idempotency_key: '99999999-9999-4999-8999-999999999999',
        status: 'IN_PROGRESS',
        items: [],
        created_at: '2026-07-10T00:00:00Z',
        updated_at: '2026-07-10T00:00:00Z',
        completed_at: null,
      }
      const conflictError = new AxiosError('another liquidation is active')
      Object.assign(conflictError, {
        response: {
          status: 409,
          data: {
            detail: {
              error_code: errorCode,
              message: '다른 청산 작업이 진행 중입니다.',
              active_liquidation_operation: activeOperation,
            },
          },
        },
      })
      apiMocks.liquidateAll.mockRejectedValueOnce(conflictError)
      apiMocks.getLiquidation.mockResolvedValueOnce(activeOperation)

      renderWithQueryClient(<ControlPanel />)
      await clickNewLiquidationButton()

      expect(await screen.findByText(/청산 작업 #9: 상태 확인 단계가 진행 중/)).toBeTruthy()
      expect(screen.getByRole('button', { name: '청산 상태 확인' })).toBeTruthy()

      fireEvent.click(screen.getByRole('button', { name: '청산 상태 확인' }))
      await waitFor(() => expect(apiMocks.getLiquidation).toHaveBeenCalledWith(9))
      expect(window.sessionStorage.getItem('ai-trade-manager-liquidation-operation-key')).toBe(
        activeOperation.idempotency_key,
      )
    },
  )

  it('PAPER 모드에서는 신규 실자산 청산 operation 생성을 차단한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue(
      botStatus({
        trading_mode: 'paper',
      }),
    )

    renderWithQueryClient(<ControlPanel />)

    expect(await screen.findByText(/PAPER 모드에서는 신규 실자산 청산 요청/)).toBeTruthy()
    const button = screen.getByRole('button', { name: '계정 전체 청산 시작' })
    expect((button as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(button)
    expect(apiMocks.liquidateAll).not.toHaveBeenCalled()
  })

  it('정상 LIVE 뒤 polling이 실패하면 stale LIVE로 신규 청산을 허용하지 않는다', async () => {
    apiMocks.getBotStatus
      .mockResolvedValueOnce(botStatus())
      .mockRejectedValue(new Error('status polling failed'))

    const { queryClient } = renderWithQueryClient(<ControlPanel />)
    const button = screen.getByRole('button', { name: '계정 전체 청산 시작' })
    fireEvent.change(
      screen.getByLabelText('확인 문구: CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL'),
      { target: { value: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL' } },
    )
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))

    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['bot-status'] })
    })

    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true))
    expect(screen.getByText(/봇 상태 조회에 실패해 신규 실자산 청산 요청을 차단/)).toBeTruthy()
    fireEvent.click(button)
    expect(apiMocks.liquidateAll).not.toHaveBeenCalled()
  })

  it('polling 실패 상태에서도 저장된 pending operation 재확인은 유지한다', async () => {
    window.sessionStorage.setItem(
      'ai-trade-manager-liquidation-operation-key',
      '77777777-7777-4777-8777-777777777777',
    )
    apiMocks.getBotStatus.mockRejectedValue(new Error('status polling failed'))
    apiMocks.liquidateAll.mockResolvedValue({
      id: 17,
      idempotency_key: '77777777-7777-4777-8777-777777777777',
      status: 'IN_PROGRESS',
      items: [],
      created_at: '2026-07-11T00:00:00Z',
      updated_at: '2026-07-11T00:00:00Z',
      completed_at: null,
    })

    renderWithQueryClient(<ControlPanel />)
    const retryButton = await screen.findByRole('button', { name: '동일 요청 재시도' })
    expect((retryButton as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(retryButton)

    await waitFor(() => expect(apiMocks.liquidateAll).toHaveBeenCalledTimes(1))
    expect(apiMocks.liquidateAll).toHaveBeenCalledWith(
      '77777777-7777-4777-8777-777777777777',
      {
        scope: 'ACCOUNT_ALL',
        confirmation: 'CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL',
      },
    )
  })

  it('정확한 확인 문구 전에는 신규 계정 청산을 활성화하지 않는다', async () => {
    renderWithQueryClient(<ControlPanel />)

    expect(await screen.findByText(/수동·외부 wait\/watch 주문도 모두 취소/)).toBeTruthy()
    const button = screen.getByRole('button', { name: '계정 전체 청산 시작' })
    expect((button as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(
      screen.getByLabelText('확인 문구: CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL'),
      { target: { value: 'LIQUIDATE_ALL' } },
    )
    expect((button as HTMLButtonElement).disabled).toBe(true)
    expect(apiMocks.liquidateAll).not.toHaveBeenCalled()
  })

  it('종결 결과와 요청 키를 보존하고 사용자가 닫을 때만 제거한다', async () => {
    apiMocks.liquidateAll.mockResolvedValue({
      id: 27,
      idempotency_key: '11111111-1111-4111-8111-111111111111',
      status: 'PARTIAL',
      contract_version: 2,
      phase: 'TERMINAL',
      verification_status: 'VERIFIED',
      summary: {
        discovered_orders: 2,
        cancel_confirmed: 1,
        cancel_unknown: 1,
        attempted: 1,
        succeeded: 0,
        failed: 1,
        remaining: 1,
      },
      cancellations: [
        {
          exchange_uuid: 'external-order',
          market: 'KRW-BTC',
          ownership: 'EXTERNAL',
          status: 'UNKNOWN',
          attempt_count: 1,
          error_code: null,
        },
      ],
      items: [
        {
          currency: 'BTC',
          market: 'KRW-BTC',
          requested_volume: '0.01',
          intent_id: null,
          identifier: null,
          exchange_uuid: null,
          submission_status: null,
          exchange_state: null,
          projection_status: null,
          executed_volume: '0',
          remaining_volume: '0.01',
          initial_balance: '0.01',
          initial_locked: '0.003',
          final_balance: '0.01',
          final_locked: '0.003',
          estimated_value_krw: '4500',
          result_code: 'DUST_REMAINING',
          error_code: null,
        },
      ],
      created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:01:00Z',
      completed_at: '2026-07-12T00:01:00Z',
    })

    renderWithQueryClient(<ControlPanel />)
    await clickNewLiquidationButton()

    const partial = await screen.findByText(/잔여 자산 또는 원장 불일치로 부분 종결/)
    expect(partial.className).toContain('text-warning')
    expect(partial.className).not.toContain('text-status-success')
    expect(screen.getByText('최소 주문액 미만 잔여')).toBeTruthy()
    expect(screen.getByText(/수동\/외부 주문/)).toBeTruthy()
    expect(screen.getByText('1 / 1')).toBeTruthy()
    expect(window.sessionStorage.getItem('ai-trade-manager-liquidation-operation-key')).toBe(
      '11111111-1111-4111-8111-111111111111',
    )
    expect(screen.getByRole('button', { name: '청산 결과 다시 확인' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '결과 닫고 새 청산 준비' }))
    expect(window.sessionStorage.getItem('ai-trade-manager-liquidation-operation-key')).toBeNull()
    expect(screen.getByRole('button', { name: '계정 전체 청산 시작' })).toBeTruthy()
  })

  it('COMPLETED라도 VERIFIED가 아니면 성공색 대신 legacy 경고를 표시한다', async () => {
    const legacyOperation = {
      id: 31,
      idempotency_key: '31313131-3131-4131-8131-313131313131',
      status: 'COMPLETED',
      contract_version: 1,
      cancel_scope: 'LEGACY_NONE',
      phase: 'TERMINAL',
      verification_status: 'LEGACY_UNVERIFIED',
      items: [],
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
      completed_at: '2026-07-10T00:00:00Z',
    }
    window.sessionStorage.setItem(
      'ai-trade-manager-liquidation-operation-key',
      legacyOperation.idempotency_key,
    )
    window.sessionStorage.setItem(
      'ai-trade-manager-liquidation-operation',
      JSON.stringify(legacyOperation),
    )

    renderWithQueryClient(<ControlPanel />)

    const legacyWarning = screen.getByText(/완료 기록이지만 최종 검증 증거가 없습니다/)
    expect(legacyWarning.className).toContain('text-warning')
    expect(legacyWarning.className).not.toContain('text-status-success')
    expect(screen.getByText(/이전 계약으로 생성된 작업/)).toBeTruthy()
    expect(screen.queryByText(/거래소 잔고와 내부 원장 검증까지 완료/)).toBeNull()
  })

  it('COMPLETED와 VERIFIED가 함께 확인된 경우에만 성공 상태를 표시한다', async () => {
    apiMocks.liquidateAll.mockResolvedValue({
      id: 32,
      idempotency_key: '11111111-1111-4111-8111-111111111111',
      status: 'COMPLETED',
      contract_version: 2,
      cancel_scope: 'ACCOUNT_ALL',
      phase: 'TERMINAL',
      verification_status: 'VERIFIED',
      summary: {
        discovered_orders: 0,
        cancel_confirmed: 0,
        cancel_unknown: 0,
        attempted: 1,
        succeeded: 1,
        failed: 0,
        remaining: 0,
      },
      cancellations: [],
      items: [],
      created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:01:00Z',
      completed_at: '2026-07-12T00:01:00Z',
    })

    renderWithQueryClient(<ControlPanel />)
    await clickNewLiquidationButton()

    const success = await screen.findByText(/거래소 잔고와 내부 원장 검증까지 완료/)
    expect(success.className).toContain('text-status-success')
    expect(screen.getByText('검증 VERIFIED').className).toContain('text-status-success')
  })

  it('NO_ASSETS는 VERIFIED여도 청산 성공색으로 표시하지 않는다', async () => {
    const noAssetsOperation = {
      id: 33,
      idempotency_key: '33333333-3333-4333-8333-333333333333',
      status: 'NO_ASSETS',
      contract_version: 2,
      cancel_scope: 'ACCOUNT_ALL',
      phase: 'TERMINAL',
      verification_status: 'VERIFIED',
      items: [],
      created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:01:00Z',
      completed_at: '2026-07-12T00:01:00Z',
    }
    window.sessionStorage.setItem(
      'ai-trade-manager-liquidation-operation-key',
      noAssetsOperation.idempotency_key,
    )
    window.sessionStorage.setItem(
      'ai-trade-manager-liquidation-operation',
      JSON.stringify(noAssetsOperation),
    )

    renderWithQueryClient(<ControlPanel />)

    const noAssets = screen.getByText(/거래소 조회 결과 청산할 가상자산이 없습니다/)
    expect(noAssets.className).toContain('text-warning')
    expect(noAssets.className).not.toContain('text-status-success')
  })
})
