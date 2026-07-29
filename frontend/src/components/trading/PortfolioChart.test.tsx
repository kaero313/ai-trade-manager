// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import PortfolioChart from './PortfolioChart'

describe('PortfolioChart 계좌 사실성', () => {
  afterEach(() => {
    cleanup()
  })

  it('empty 응답을 정상 0원이나 risk score 0으로 표시하지 않는다', () => {
    render(
      <PortfolioChart
        items={[]}
        isLoading={false}
        source="empty"
        isStale={false}
        updatedAt={null}
        errorCode="UPBIT_KEY_MISSING"
        totalNetWorth={0}
        totalPnl={0}
      />,
    )

    expect(screen.getByText('UNAVAILABLE')).toBeTruthy()
    expect(screen.queryByText('₩0')).toBeNull()
    expect(screen.queryByText('0', { selector: '.font-mono' })).toBeNull()
    expect(screen.getByText(/AI 브리핑 비활성화/)).toBeTruthy()
  })

  it('검증 가능한 live 응답만 실제 금액과 손익으로 표시한다', () => {
    render(
      <PortfolioChart
        items={[
          {
            broker: 'UPBIT',
            currency: 'KRW',
            balance: 1_250_000,
            locked: 0,
            avg_buy_price: 1,
            current_price: 1,
            total_value: 1_250_000,
            pnl_percentage: 0,
          },
        ]}
        isLoading={false}
        source="live"
        isStale={false}
        updatedAt="2026-07-15T03:00:00Z"
        totalNetWorth={1_250_000}
        totalPnl={25_000}
      />,
    )

    expect(screen.getByText('SYNCED')).toBeTruthy()
    expect(screen.getByText('₩1,250,000')).toBeTruthy()
    expect(screen.getByText('+₩25,000')).toBeTruthy()
    expect(screen.queryByText(/AI 브리핑 비활성화/)).toBeNull()
  })
})
