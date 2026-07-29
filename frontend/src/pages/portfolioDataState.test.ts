import { describe, expect, it } from 'vitest'

import type { PortfolioSummary } from '../services/portfolioService'
import { resolvePortfolioDataState, resolvePortfolioUnavailableMessage } from './portfolioDataState'

function buildPortfolio(overrides: Partial<PortfolioSummary> = {}): PortfolioSummary {
  return {
    total_net_worth: 12_500_000,
    total_pnl: 250_000,
    items: [
      {
        broker: 'UPBIT',
        currency: 'KRW',
        balance: 5_000_000,
        locked: 0,
        avg_buy_price: 1,
        current_price: 1,
        total_value: 5_000_000,
        pnl_percentage: 0,
      },
    ],
    source: 'live',
    is_stale: false,
    updated_at: '2026-07-15T03:00:00Z',
    error: null,
    ...overrides,
  }
}

describe('resolvePortfolioDataState', () => {
  it('초기 조회 중에는 금액과 AI context를 모두 숨긴다', () => {
    const state = resolvePortfolioDataState({
      data: null,
      isError: false,
      isLoading: true,
    })

    expect(state.kind).toBe('loading')
    expect(state.canDisplayAmounts).toBe(false)
    expect(state.canUseAiContext).toBe(false)
  })

  it('live 응답만 정상 실시간 금액으로 판정한다', () => {
    const state = resolvePortfolioDataState({
      data: buildPortfolio(),
      isError: false,
      isLoading: false,
    })

    expect(state.kind).toBe('live')
    expect(state.canDisplayAmounts).toBe(true)
    expect(state.canUseAiContext).toBe(true)
    expect(state.isStale).toBe(false)
  })

  it('snapshot은 마지막 금액과 오류·갱신 시각을 보존한다', () => {
    const state = resolvePortfolioDataState({
      data: buildPortfolio({
        source: 'snapshot',
        is_stale: true,
        error: 'UPBIT_AUTH_FAILED',
      }),
      isError: false,
      isLoading: false,
    })

    expect(state.kind).toBe('snapshot')
    expect(state.canDisplayAmounts).toBe(true)
    expect(state.isStale).toBe(true)
    expect(state.errorCode).toBe('UPBIT_AUTH_FAILED')
    expect(state.updatedAt).toBe('2026-07-15T03:00:00Z')
  })

  it('캐시가 있는 refetch 오류는 마지막 수치를 유지하고 stale로 판정한다', () => {
    const portfolio = buildPortfolio()
    const state = resolvePortfolioDataState({
      data: portfolio,
      error: new Error('network failed'),
      isError: true,
      isLoading: false,
      isRefetchError: true,
    })

    expect(state.kind).toBe('cached-refetch-error')
    expect(state.portfolio).toBe(portfolio)
    expect(state.canDisplayAmounts).toBe(true)
    expect(state.canUseAiContext).toBe(true)
    expect(state.isStale).toBe(true)
    expect(state.errorCode).toBe('network failed')
  })

  it('empty를 정상 0원으로 취급하지 않는다', () => {
    const state = resolvePortfolioDataState({
      data: buildPortfolio({
        source: 'empty',
        total_net_worth: 0,
        total_pnl: 0,
        items: [],
      }),
      isError: false,
      isLoading: false,
    })

    expect(state.kind).toBe('empty')
    expect(state.canDisplayAmounts).toBe(false)
    expect(state.canUseAiContext).toBe(false)
  })

  it('캐시 없는 오류와 비유한 숫자는 hard-error로 fail-closed한다', () => {
    const fetchErrorState = resolvePortfolioDataState({
      data: null,
      error: new Error('UPBIT_IP_NOT_ALLOWED'),
      isError: true,
      isLoading: false,
    })
    const invalidDataState = resolvePortfolioDataState({
      data: buildPortfolio({ total_net_worth: Number.NaN }),
      isError: false,
      isLoading: false,
    })

    expect(fetchErrorState.kind).toBe('hard-error')
    expect(fetchErrorState.errorCode).toBe('UPBIT_IP_NOT_ALLOWED')
    expect(fetchErrorState.canDisplayAmounts).toBe(false)
    expect(invalidDataState.kind).toBe('hard-error')
    expect(invalidDataState.errorCode).toBe('PORTFOLIO_INVALID_DATA')
    expect(invalidDataState.canUseAiContext).toBe(false)
  })

  it('복합 인증 오류에서도 IP 제한을 일반 인증보다 우선 안내한다', () => {
    const state = resolvePortfolioDataState({
      data: null,
      error: new Error('UPBIT_AUTH_IP_NOT_ALLOWED'),
      isError: true,
      isLoading: false,
    })

    expect(resolvePortfolioUnavailableMessage(state)).toContain('허용 IP')
  })
})
