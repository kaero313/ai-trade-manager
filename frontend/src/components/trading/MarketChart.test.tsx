// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MarketChart from './MarketChart'

const chartMocks = vi.hoisted(() => {
  const series = {
    createPriceLine: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
    setData: vi.fn(),
  }
  const timeScale = {
    fitContent: vi.fn(),
    setVisibleLogicalRange: vi.fn(),
    subscribeVisibleLogicalRangeChange: vi.fn(),
    unsubscribeVisibleLogicalRangeChange: vi.fn(),
  }
  const chart = {
    addSeries: vi.fn(() => series),
    remove: vi.fn(),
    resize: vi.fn(),
    timeScale: () => timeScale,
  }
  return { chart, series }
})

const queryMock = vi.hoisted(() => vi.fn())

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMock,
}))

vi.mock('../../contexts/useTheme', () => ({
  useTheme: () => ({ theme: 'dark' }),
}))

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'CandlestickSeries',
  ColorType: { Solid: 'Solid' },
  createChart: vi.fn(() => chartMocks.chart),
  HistogramSeries: 'HistogramSeries',
  LineSeries: 'LineSeries',
  LineStyle: { Dashed: 2 },
}))

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

describe('MarketChart 표시 계약', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    queryMock.mockReturnValue({
      data: undefined,
      error: null,
      isError: false,
      isLoading: false,
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('종목 미선택 상태를 명시하고 동작하지 않는 AI 예측선 제어를 노출하지 않는다', () => {
    render(<MarketChart symbol={null} />)

    expect(screen.getByRole('status').textContent).toContain('종목을 선택')
    expect(screen.queryByRole('button', { name: 'AI 예측선' })).toBeNull()
  })

  it('캔들 조회 오류를 alert로 노출한다', () => {
    queryMock.mockReturnValue({
      data: undefined,
      error: new Error('candle failed'),
      isError: true,
      isLoading: false,
    })

    render(<MarketChart symbol="KRW-BTC" />)

    expect(screen.getByRole('alert').textContent).toContain('캔들 데이터를 불러오지 못했습니다')
  })
})
