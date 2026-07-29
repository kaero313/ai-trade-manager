// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PortfolioAiBriefing from './PortfolioAiBriefing'
import PortfolioMiniChat from './PortfolioMiniChat'

const mocks = vi.hoisted(() => ({
  fetchPortfolioBriefing: vi.fn(),
  streamChatMessage: vi.fn(),
}))

vi.mock('../../services/portfolioService', () => ({
  fetchPortfolioBriefing: mocks.fetchPortfolioBriefing,
}))
vi.mock('../../services/api', () => ({
  streamChatMessage: mocks.streamChatMessage,
}))

describe('Portfolio AI unavailable 차단', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('포트폴리오 unavailable이면 브리핑을 자동 요청하지 않는다', () => {
    render(
      <PortfolioAiBriefing
        items={[]}
        snapshots={[]}
        totalNetWorth={0}
        totalPnl={0}
        aiAnalysisMap={{}}
        isPortfolioLoading={false}
        isPortfolioAvailable={false}
        unavailableMessage="계좌 조회 실패"
      />,
    )

    expect(screen.getByText('AI 브리핑을 사용할 수 없습니다')).toBeTruthy()
    expect(screen.getByText('계좌 조회 실패')).toBeTruthy()
    expect((screen.getByRole('button', { name: /다시 분석/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(mocks.fetchPortfolioBriefing).not.toHaveBeenCalled()
  })

  it('포트폴리오 unavailable이면 세션 생성과 메시지 전송 UI를 차단한다', () => {
    const onCreateSession = vi.fn()

    render(
      <PortfolioMiniChat
        sessionId="existing-session"
        onCreateSession={onCreateSession}
        isPortfolioAvailable={false}
        unavailableMessage="계좌 조회 실패"
      />,
    )

    expect(screen.getByText('포트폴리오 확인이 필요합니다')).toBeTruthy()
    expect((screen.getByRole('textbox') as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: /전송/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(onCreateSession).not.toHaveBeenCalled()
    expect(mocks.streamChatMessage).not.toHaveBeenCalled()
  })

  it('포트폴리오가 확인되면 기존 브리핑 자동 요청을 유지한다', async () => {
    mocks.fetchPortfolioBriefing.mockResolvedValue({
      provider: 'openai',
      model: 'test-model',
      report: '현재 배분을 유지합니다.',
      fallback: false,
    })

    render(
      <PortfolioAiBriefing
        items={[]}
        snapshots={[]}
        totalNetWorth={1_000_000}
        totalPnl={10_000}
        aiAnalysisMap={{}}
        isPortfolioLoading={false}
        isPortfolioAvailable
        unavailableMessage={null}
      />,
    )

    await waitFor(() => expect(mocks.fetchPortfolioBriefing).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('현재 배분을 유지합니다.')).toBeTruthy()
  })

  it('unavailable 전환은 진행 요청과 과거 결과를 폐기하고 복구 시 한 번 다시 요청한다', async () => {
    let resolveOldRequest: ((value: {
      provider: string
      model: string
      report: string
      fallback: boolean
    }) => void) | null = null
    const oldRequest = new Promise<{
      provider: string
      model: string
      report: string
      fallback: boolean
    }>((resolve) => {
      resolveOldRequest = resolve
    })
    mocks.fetchPortfolioBriefing
      .mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce({
        provider: 'openai',
        model: 'test-model',
        report: '복구된 포트폴리오의 최신 해설',
        fallback: false,
      })

    const { rerender } = render(
      <PortfolioAiBriefing
        items={[]}
        snapshots={[]}
        totalNetWorth={1_000_000}
        totalPnl={10_000}
        aiAnalysisMap={{}}
        isPortfolioLoading={false}
        isPortfolioAvailable
        unavailableMessage={null}
      />,
    )

    await waitFor(() => expect(mocks.fetchPortfolioBriefing).toHaveBeenCalledTimes(1))
    rerender(
      <PortfolioAiBriefing
        items={[]}
        snapshots={[]}
        totalNetWorth={0}
        totalPnl={0}
        aiAnalysisMap={{}}
        isPortfolioLoading={false}
        isPortfolioAvailable={false}
        unavailableMessage="계좌 조회 실패"
      />,
    )

    await act(async () => {
      resolveOldRequest?.({
        provider: 'openai',
        model: 'test-model',
        report: '폐기해야 하는 과거 해설',
        fallback: false,
      })
      await oldRequest
    })
    expect(screen.queryByText('폐기해야 하는 과거 해설')).toBeNull()

    rerender(
      <PortfolioAiBriefing
        items={[]}
        snapshots={[]}
        totalNetWorth={2_000_000}
        totalPnl={20_000}
        aiAnalysisMap={{}}
        isPortfolioLoading={false}
        isPortfolioAvailable
        unavailableMessage={null}
      />,
    )

    await waitFor(() => expect(mocks.fetchPortfolioBriefing).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('복구된 포트폴리오의 최신 해설')).toBeTruthy()
    expect(screen.queryByText('폐기해야 하는 과거 해설')).toBeNull()
  })
})
