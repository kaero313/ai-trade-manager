// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsPage from './SettingsPage'

const mocks = vi.hoisted(() => ({
  updateConfigs: vi.fn(),
  resetProviderStatus: vi.fn(),
  refetchConfigs: vi.fn(),
  invalidateAdminSession: vi.fn(),
  isLoading: false,
  isError: false,
  systemConfigs: [
    {
      id: 1,
      config_key: 'ai_trade_target_symbols',
      config_value: '["KRW-BTC","KRW-ETH"]',
      description: '운영 대상 종목',
      version: 3,
    },
  ],
}))

vi.mock('../hooks/useSystemConfigs', () => ({
  useSystemConfigs: () => ({
    data: mocks.systemConfigs,
    isLoading: mocks.isLoading,
    isError: mocks.isError,
    refetch: mocks.refetchConfigs,
  }),
  useAiProviderRuntimeStatus: () => ({
    data: { active_provider: null, providers: [] },
    isError: false,
  }),
  useUpdateSystemConfigs: () => ({
    mutateAsync: mocks.updateConfigs,
    isPending: false,
  }),
  useResetAiProviderStatus: () => ({
    mutateAsync: mocks.resetProviderStatus,
    isPending: false,
  }),
}))

vi.mock('../services/api', () => ({
  invalidateAdminSession: mocks.invalidateAdminSession,
}))

describe('운영 설정 SSOT 화면', () => {
  beforeEach(() => {
    mocks.updateConfigs.mockReset().mockResolvedValue([])
    mocks.resetProviderStatus.mockReset().mockResolvedValue(null)
    mocks.refetchConfigs.mockReset().mockResolvedValue(undefined)
    mocks.invalidateAdminSession.mockReset()
    mocks.isLoading = false
    mocks.isError = false
    mocks.systemConfigs = [
      {
        id: 1,
        config_key: 'ai_trade_target_symbols',
        config_value: '["KRW-BTC","KRW-ETH"]',
        description: '운영 대상 종목',
        version: 3,
      },
    ]
  })

  afterEach(() => {
    cleanup()
  })

  it('설정 loading과 조회 오류를 각각 status와 alert로 알린다', () => {
    mocks.isLoading = true
    const { rerender } = render(<SettingsPage />)

    expect(screen.getByRole('status').textContent).toContain('AI 운용 설정을 불러오는 중입니다.')

    mocks.isLoading = false
    mocks.isError = true
    rerender(<SettingsPage />)

    expect(screen.getByRole('alert').textContent).toContain('AI 운용 설정을 불러오지 못했습니다.')
  })

  it('카테고리 anchor를 사용하면서 모든 실제 설정 editor를 동시에 mount한다', () => {
    render(<SettingsPage />)

    expect(screen.getByRole('navigation').getAttribute('aria-label')).toBe('설정 카테고리')
    expect(screen.getByRole('link', { name: 'AI Provider' }).getAttribute('href')).toBe(
      '#settings-provider',
    )
    expect(screen.getByRole('link', { name: 'Slack 알림' }).getAttribute('href')).toBe(
      '#settings-notifications',
    )
    expect(screen.getByRole('heading', { name: 'AI Provider' })).toBeTruthy()
    expect(screen.getByLabelText(/운영 대상 종목/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Slack 포트폴리오 알림' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'AI 매매 철학 및 페르소나' })).toBeTruthy()
    expect(
      screen.getByText(/거래소와 AI API 키는 서버 환경변수에서만 읽으며/),
    ).toBeTruthy()
    expect(screen.queryByLabelText(/API 키/)).toBeNull()
  })

  it('관리자 토큰의 persistent 저장 범위와 초기화 동작을 정확히 안내한다', () => {
    render(<SettingsPage />)

    expect(screen.getByText(/persistent=true로 발급된 세션 토큰만/)).toBeTruthy()
    expect(screen.getByText(/persistent=false인 1회용 토큰은 저장하지 않고/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '관리 토큰 초기화' }))

    expect(mocks.invalidateAdminSession).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/운영 관리 토큰을 초기화했습니다/)).toBeTruthy()
  })

  it('provider 차단 상태는 일반 설정 저장이 아닌 전용 reset 계약으로 초기화한다', async () => {
    mocks.systemConfigs = [
      ...mocks.systemConfigs,
      {
        id: 2,
        config_key: 'ai_provider_status',
        config_value: '{}',
        description: 'AI provider 상태',
        version: 8,
      },
    ]
    render(<SettingsPage />)

    fireEvent.click(screen.getByRole('button', { name: '차단 상태 초기화' }))

    await waitFor(() => {
      expect(mocks.resetProviderStatus).toHaveBeenCalledWith(8)
      expect(mocks.updateConfigs).not.toHaveBeenCalled()
      expect(mocks.refetchConfigs).toHaveBeenCalled()
    })
  })

  it('운영 대상은 SystemConfig version과 함께 저장하고 legacy 배분 UI는 표시하지 않는다', async () => {
    render(<SettingsPage />)

    expect(screen.queryByText('종목별 자산 배분 비율')).toBeNull()
    const targetInput = screen.getByLabelText(/운영 대상 종목/)
    fireEvent.change(targetInput, { target: { value: 'krw-btc, krw-xrp' } })
    fireEvent.click(screen.getByRole('button', { name: 'AI 운용 설정 저장' }))

    await waitFor(() => {
      expect(mocks.updateConfigs).toHaveBeenCalledWith([
        {
          config_key: 'ai_trade_target_symbols',
          config_value: '["KRW-BTC","KRW-XRP"]',
          expected_version: 3,
        },
      ])
    })
    expect(screen.getByRole('status').textContent).toContain('설정을 저장했습니다.')
  })

  it('저장 후 runtime 재등록 실패는 상세 메시지를 표시하고 stale draft를 폐기한다', async () => {
    const applyFailure = new AxiosError(
      'HTTP 503',
      AxiosError.ERR_BAD_RESPONSE,
      {} as InternalAxiosRequestConfig,
      null,
      {
        status: 503,
        statusText: 'Service Unavailable',
        headers: {},
        config: {} as InternalAxiosRequestConfig,
        data: {
          detail: {
            saved: true,
            message: '설정은 저장됐지만 스케줄러 재등록에 실패했습니다.',
          },
        },
      },
    )
    mocks.updateConfigs.mockRejectedValueOnce(applyFailure)
    render(<SettingsPage />)

    const targetInput = screen.getByLabelText(/운영 대상 종목/) as HTMLInputElement
    fireEvent.change(targetInput, { target: { value: 'KRW-XRP' } })
    fireEvent.click(screen.getByRole('button', { name: 'AI 운용 설정 저장' }))

    await waitFor(() => {
      expect(mocks.refetchConfigs).toHaveBeenCalled()
      expect(
        screen.getByText(/설정은 저장됐지만 스케줄러 재등록에 실패했습니다/),
      ).toBeTruthy()
      expect(screen.getByRole('alert').textContent).toContain(
        '설정은 저장됐지만 스케줄러 재등록에 실패했습니다',
      )
      expect(targetInput.value).toBe('KRW-BTC, KRW-ETH')
    })
  })

  it('편집 중 query version이 바뀌면 최신 version으로 재기반하지 않고 저장을 차단한다', async () => {
    const { rerender } = render(<SettingsPage />)

    const targetInput = screen.getByLabelText(/운영 대상 종목/)
    fireEvent.change(targetInput, { target: { value: 'KRW-XRP' } })
    mocks.systemConfigs = [
      {
        id: 1,
        config_key: 'ai_trade_target_symbols',
        config_value: '["KRW-BTC","KRW-ETH"]',
        description: '운영 대상 종목',
        version: 4,
      },
    ]
    rerender(<SettingsPage />)
    fireEvent.click(screen.getByRole('button', { name: 'AI 운용 설정 저장' }))

    await waitFor(() => {
      expect(mocks.updateConfigs).not.toHaveBeenCalled()
      expect(mocks.refetchConfigs).toHaveBeenCalled()
      expect(screen.getByText(/편집 중 설정이 변경되어 저장하지 않았습니다/)).toBeTruthy()
    })
  })
})
