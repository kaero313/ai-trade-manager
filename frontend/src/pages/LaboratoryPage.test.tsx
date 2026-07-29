// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LaboratoryPage from './LaboratoryPage'

const mocks = vi.hoisted(() => ({
  fetchMarkets: vi.fn(),
  getBotConfig: vi.fn(),
  getSystemConfigs: vi.fn(),
  runBacktest: vi.fn(),
}))

vi.mock('../api/markets', () => ({ fetchMarkets: mocks.fetchMarkets }))
vi.mock('../contexts/useTheme', () => ({ useTheme: () => ({ theme: 'dark' }) }))
vi.mock('../services/api', () => ({
  getBotConfig: mocks.getBotConfig,
  getSystemConfigs: mocks.getSystemConfigs,
}))
vi.mock('../services/backtestService', () => ({ runBacktest: mocks.runBacktest }))

class ResizeObserverStub {
  observe() {}
  disconnect() {}
  unobserve() {}
}

const backtestResult = {
  summary: {
    total_return_pct: 4.25,
    max_drawdown_pct: 2.4,
    win_rate: 60,
    number_of_trades: 5,
  },
  candles: [],
  markers: [],
  trades: [],
  equity_curve: [],
  drawdown_curve: [],
  meta: {
    market: 'KRW-BTC',
    timeframe: '240m',
    start_date: '2025-07-15T00:00:00Z',
    end_date: '2026-07-15T23:59:59Z',
    bars_processed: 120,
    last_timestamp: '2026-07-15T20:00:00Z',
    initial_balance: 1_000_000,
    final_balance: 1_042_500,
    position_qty: 0,
  },
  ai_briefing: {
    content: '규칙 기반 결과를 참고용으로 해설했습니다.',
    provider: 'test',
    model: 'test-model',
    fallback: false,
  },
}

describe('Strategy Laboratory 참고 전략 표시', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    mocks.fetchMarkets.mockResolvedValue([
      { market: 'KRW-BTC', korean_name: '비트코인', english_name: 'Bitcoin' },
    ])
    mocks.getBotConfig.mockResolvedValue({ symbols: [] })
    mocks.getSystemConfigs.mockResolvedValue([
      { config_key: 'ai_min_confidence_trade', config_value: '70' },
      { config_key: 'max_allocation_pct', config_value: '30' },
      { config_key: 'hard_take_profit_pct', config_value: '5' },
      { config_key: 'hard_stop_loss_pct', config_value: '-3' },
    ])
    mocks.runBacktest.mockResolvedValue(backtestResult)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    Object.values(mocks).forEach((mock) => mock.mockReset())
  })

  it('운영 LLM 재현이 아닌 규칙 기반 참고 백테스트임을 명시한다', async () => {
    render(<LaboratoryPage />)

    expect(screen.getByRole('heading', { name: '규칙 기반 참고 백테스트' })).toBeTruthy()
    expect(screen.getByText('운영 LLM 전략 과거 재현이 아님')).toBeTruthy()
    expect(screen.getByText('검증할 규칙 기반 정책')).toBeTruthy()
    expect(screen.queryByText('AI 매매 정책 검증실')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '전문가 설정 열기' }))

    expect(screen.getByText('결정론적 지표')).toBeTruthy()
    expect(screen.getByText('신뢰도 기준')).toBeTruthy()
    expect(screen.getByRole('button', { name: '1시간' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '4시간' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '일봉' })).toBeTruthy()
    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: '규칙 기반 정책 실행' }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )
  })

  it('기존 결정론적 설정을 그대로 전달하고 결과 AI 해설과 KPI를 표시한다', async () => {
    render(<LaboratoryPage />)

    fireEvent.click(screen.getByRole('button', { name: '4시간' }))
    const runButton = screen.getByRole('button', { name: '규칙 기반 정책 실행' })
    await waitFor(() => expect((runButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(runButton)

    await waitFor(() => {
      expect(screen.queryByRole('alert')?.textContent ?? null).toBeNull()
      expect(mocks.runBacktest).toHaveBeenCalledWith(
        expect.objectContaining({
          market: 'KRW-BTC',
          timeframe: '240m',
          initial_balance: 1_000_000,
          strategy: {
            ema_fast: 12,
            ema_slow: 26,
            rsi_period: 14,
            rsi_min: 50,
            trailing_stop_pct: 0.03,
          },
          policy: {
            min_confidence: 70,
            max_allocation_pct: 30,
            take_profit_pct: 5,
            stop_loss_pct: -3,
            cooldown_minutes: 60,
          },
        }),
      )
    })

    expect(await screen.findByText('결과 AI 해설')).toBeTruthy()
    expect(screen.getByText('규칙 기반 결과를 참고용으로 해설했습니다.')).toBeTruthy()
    expect(screen.getByText('총 수익률')).toBeTruthy()
    expect(screen.getByText('+4.25%')).toBeTruthy()
    const equityTab = screen.getByRole('tab', { name: '자산 곡선' })
    const drawdownTab = screen.getByRole('tab', { name: '낙폭' })
    expect(equityTab.getAttribute('aria-selected')).toBe('true')
    expect(drawdownTab.getAttribute('aria-selected')).toBe('false')
    expect(screen.getByRole('tab', { name: '거래 내역' })).toBeTruthy()
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(
      'laboratory-result-tab-equity',
    )

    fireEvent.click(drawdownTab)

    expect(drawdownTab.getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(
      'laboratory-result-tab-drawdown',
    )
  })

  it('빈 날짜나 잘못된 날짜는 payload 생성 전에 화면 오류로 차단한다', async () => {
    render(<LaboratoryPage />)

    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: '' } })
    const runButton = screen.getByRole('button', { name: '규칙 기반 정책 실행' })
    await waitFor(() => expect((runButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(runButton)

    expect(screen.getByRole('alert').textContent).toContain(
      '시작일과 종료일을 올바른 날짜로 입력해야 합니다.',
    )
    expect(mocks.runBacktest).not.toHaveBeenCalled()
  })

  it('시작일이 종료일보다 늦으면 payload를 전송하지 않는다', async () => {
    render(<LaboratoryPage />)

    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: '2026-07-16' } })
    fireEvent.change(screen.getByLabelText('종료일'), { target: { value: '2026-07-15' } })
    const runButton = screen.getByRole('button', { name: '규칙 기반 정책 실행' })
    await waitFor(() => expect((runButton as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(runButton)

    expect(screen.getByRole('alert').textContent).toContain(
      '시작일은 종료일보다 늦을 수 없습니다.',
    )
    expect(mocks.runBacktest).not.toHaveBeenCalled()
  })
})
