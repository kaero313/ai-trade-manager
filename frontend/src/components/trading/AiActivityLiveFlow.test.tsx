// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AiActivityLiveFlow from './AiActivityLiveFlow'

const apiMocks = vi.hoisted(() => ({
  getBotStatus: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)

describe('AiActivityLiveFlow', () => {
  afterEach(() => {
    cleanup()
    apiMocks.getBotStatus.mockReset()
  })

  it('거래 모드로 오인할 수 있는 LIVE 명칭과 Runtime 중복을 제거한다', async () => {
    apiMocks.getBotStatus.mockResolvedValue({
      running: true,
      latest_action: 'BTC 분석 대기 중',
      last_heartbeat: '2026-07-16T00:00:00Z',
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <AiActivityLiveFlow />
      </QueryClientProvider>,
    )

    const region = screen.getByRole('region', { name: 'AI 활동 상태' })

    expect(region).toBeTruthy()
    expect(screen.getByText('AI ACTIVITY')).toBeTruthy()
    expect((await screen.findAllByText('BTC 분석 대기 중')).length).toBe(4)
    expect(screen.queryByText('LIVE FLOW')).toBeNull()
    expect(screen.queryByText('ENGINE')).toBeNull()
    expect(region.querySelector('.quantum-ticker-scroll > [aria-hidden="true"]')).toBeTruthy()
  })
})
