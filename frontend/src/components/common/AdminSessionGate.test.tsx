// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AdminSessionGate from './AdminSessionGate'

const apiMocks = vi.hoisted(() => ({
  ADMIN_SESSION_INVALIDATED_EVENT: 'ai-trade-manager:admin-session-invalidated',
  ensureAdminSession: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)

function axiosResponseError(status: number): Error & {
  isAxiosError: true
  response: { status: number }
} {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

describe('AdminSessionGate', () => {
  beforeEach(() => {
    apiMocks.ensureAdminSession.mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('관리자 세션 검증이 끝나기 전에는 private 화면을 mount하지 않는다', async () => {
    let resolveSession!: () => void
    apiMocks.ensureAdminSession.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveSession = resolve
      }),
    )

    render(
      <AdminSessionGate>
        <div>private-query-screen</div>
      </AdminSessionGate>,
    )

    expect(screen.queryByText('private-query-screen')).toBeNull()
    expect(screen.getByRole('status')).toBeTruthy()

    await act(async () => {
      resolveSession()
    })

    expect(await screen.findByText('private-query-screen')).toBeTruthy()
  })

  it('503이면 잠금 화면을 유지하고 수동 재시도 성공 뒤에만 화면을 연다', async () => {
    apiMocks.ensureAdminSession
      .mockRejectedValueOnce(axiosResponseError(503))
      .mockResolvedValueOnce(undefined)

    render(
      <AdminSessionGate>
        <div>private-query-screen</div>
      </AdminSessionGate>,
    )

    expect(await screen.findByText(/관리자 인증 서비스를 사용할 수 없습니다/)).toBeTruthy()
    expect(screen.queryByText('private-query-screen')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '다시 인증' }))

    await waitFor(() => expect(apiMocks.ensureAdminSession).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('private-query-screen')).toBeTruthy()
  })

  it('잘못된 토큰이나 입력 취소를 성공으로 간주하지 않는다', async () => {
    apiMocks.ensureAdminSession.mockRejectedValueOnce(axiosResponseError(403))

    render(
      <AdminSessionGate>
        <div>private-query-screen</div>
      </AdminSessionGate>,
    )

    expect(await screen.findByText(/관리자 토큰이 올바르지 않습니다/)).toBeTruthy()
    expect(screen.queryByText('private-query-screen')).toBeNull()

    cleanup()
    apiMocks.ensureAdminSession.mockRejectedValueOnce(new Error('관리자 토큰 입력을 취소하였습니다.'))
    render(
      <AdminSessionGate>
        <div>private-query-screen</div>
      </AdminSessionGate>,
    )

    expect(await screen.findByText(/관리자 인증이 취소되었습니다/)).toBeTruthy()
    expect(screen.queryByText('private-query-screen')).toBeNull()
  })

  it('세션 무효화 이벤트를 받으면 즉시 private 화면을 unmount하고 수동 재인증을 제공한다', async () => {
    apiMocks.ensureAdminSession.mockResolvedValue(undefined)

    render(
      <AdminSessionGate>
        <div>private-query-screen</div>
      </AdminSessionGate>,
    )

    expect(await screen.findByText('private-query-screen')).toBeTruthy()

    act(() => {
      window.dispatchEvent(new Event(apiMocks.ADMIN_SESSION_INVALIDATED_EVENT))
    })

    expect(screen.queryByText('private-query-screen')).toBeNull()
    expect(screen.getByText(/관리자 세션이 만료되었거나 거부되었습니다/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '다시 인증' }))

    await waitFor(() => expect(apiMocks.ensureAdminSession).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('private-query-screen')).toBeTruthy()
  })

  it('StrictMode 재마운트와 최종 unmount에서 무효화 listener를 빠짐없이 정리한다', async () => {
    apiMocks.ensureAdminSession.mockResolvedValue(undefined)
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')

    const { unmount } = render(
      <StrictMode>
        <AdminSessionGate>
          <div>private-query-screen</div>
        </AdminSessionGate>
      </StrictMode>,
    )

    expect(await screen.findByText('private-query-screen')).toBeTruthy()
    const addCount = addSpy.mock.calls.filter(
      ([eventName]) => eventName === apiMocks.ADMIN_SESSION_INVALIDATED_EVENT,
    ).length
    expect(addCount).toBeGreaterThan(0)

    unmount()

    const removeCount = removeSpy.mock.calls.filter(
      ([eventName]) => eventName === apiMocks.ADMIN_SESSION_INVALIDATED_EVENT,
    ).length
    expect(removeCount).toBe(addCount)
  })
})
