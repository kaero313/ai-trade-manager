// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  apiClient,
  getStoredAdminToken,
  requestAdminToken,
  storeAdminToken,
} from '../../services/api'
import AdminAuthProvider from './AdminAuthProvider'
import AdminSessionGate from './AdminSessionGate'

describe('AdminAuthProvider 일회성 재인증', () => {
  afterEach(() => {
    cleanup()
    window.sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('persistent=false 토큰을 브라우저 저장소에 기록하지 않는다', async () => {
    storeAdminToken('stored-token')
    render(
      <AdminAuthProvider>
        <div>content</div>
      </AdminAuthProvider>,
    )

    let tokenPromise!: Promise<string>
    act(() => {
      tokenPromise = requestAdminToken('live 거래 모드 전환 재인증', {
        forcePrompt: true,
        persistent: false,
      })
    })

    expect(await screen.findByText(/브라우저에 저장하지 않습니다/)).toBeTruthy()
    fireEvent.change(screen.getByPlaceholderText('ADMIN_API_TOKEN'), {
      target: { value: 'one-time-token' },
    })
    fireEvent.click(screen.getByRole('button', { name: '토큰 적용' }))

    await expect(tokenPromise).resolves.toBe('one-time-token')
    expect(getStoredAdminToken()).toBe('stored-token')
  })

  it('StrictMode에서도 관리 화면 접근 프롬프트를 하나만 열고 검증 전 private 화면을 숨긴다', async () => {
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { authenticated: true } })

    render(
      <StrictMode>
        <AdminAuthProvider>
          <AdminSessionGate>
            <div>private-query-screen</div>
          </AdminSessionGate>
        </AdminAuthProvider>
      </StrictMode>,
    )

    const tokenInput = await screen.findByPlaceholderText('ADMIN_API_TOKEN')
    expect(screen.getAllByPlaceholderText('ADMIN_API_TOKEN')).toHaveLength(1)
    expect(screen.queryByText('private-query-screen')).toBeNull()

    fireEvent.change(tokenInput, { target: { value: 'admin-token' } })
    fireEvent.click(screen.getByRole('button', { name: '토큰 적용' }))

    expect(await screen.findByText('private-query-screen')).toBeTruthy()
    expect(getSpy).toHaveBeenCalledTimes(1)
  })

  it('관리 토큰 입력을 focus trap이 있는 modal로 열고 Escape 취소를 전달한다', async () => {
    render(
      <AdminAuthProvider>
        <button type="button">배경 작업</button>
      </AdminAuthProvider>,
    )

    let tokenPromise!: Promise<string>
    act(() => {
      tokenPromise = requestAdminToken('보호 작업', { forcePrompt: true, persistent: false })
    })
    const rejectedPromise = expect(tokenPromise).rejects.toThrow('취소')

    const dialog = await screen.findByRole('dialog', { name: '운영 관리 토큰' })
    const input = screen.getByPlaceholderText('ADMIN_API_TOKEN')
    expect(dialog).toBeTruthy()
    expect(document.activeElement).toBe(input)

    fireEvent.keyDown(document, { key: 'Escape' })

    await rejectedPromise
    expect(screen.queryByRole('dialog', { name: '운영 관리 토큰' })).toBeNull()
  })
})
