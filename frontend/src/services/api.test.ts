// @vitest-environment jsdom

import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ADMIN_SESSION_INVALIDATED_EVENT,
  ADMIN_TOKEN_REQUIRED_EVENT,
  apiClient,
  approveChatConfigChange,
  clearAdminToken,
  ensureAdminSession,
  getStoredAdminToken,
  invalidateAdminSession,
  reauthAdminForLiveTrading,
  requestAdminToken,
  resetAiProviderStatus,
  storeAdminToken,
  streamChatMessage,
  updateSystemConfigs,
  type AdminTokenRequestDetail,
} from './api'

function axiosRequestError(status: number, config: InternalAxiosRequestConfig): AxiosError {
  return new AxiosError(`HTTP ${status}`, AxiosError.ERR_BAD_REQUEST, config, null, {
    data: null,
    status,
    statusText: String(status),
    headers: {},
    config,
  })
}

function axiosResponseError(status?: number): Error & {
  isAxiosError: true
  response?: { status: number }
} {
  return Object.assign(new Error(status === undefined ? 'network error' : `HTTP ${status}`), {
    isAxiosError: true as const,
    response: status === undefined ? undefined : { status },
  })
}

describe('관리자 토큰 요청 경계', () => {
  afterEach(() => {
    clearAdminToken()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('forcePrompt는 저장 토큰을 재사용하지 않고 persistent=false를 전달한다', async () => {
    storeAdminToken('stored-token')
    const requestDetails: AdminTokenRequestDetail[] = []
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<AdminTokenRequestDetail>).detail
      requestDetails.push(detail)
      detail.resolve('one-time-token')
    }
    window.addEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener, { once: true })

    await expect(
      requestAdminToken('live 거래 모드 전환', { forcePrompt: true, persistent: false }),
    ).resolves.toBe('one-time-token')
    expect(requestDetails[0]?.persistent).toBe(false)
  })

  it('reauth 토큰은 JSON body가 아니라 명시적 header로만 전달한다', async () => {
    storeAdminToken('stored-token')
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { reauth_proof: 'proof', expires_at: '2026-07-11T00:05:00Z' },
    })

    await reauthAdminForLiveTrading('one-time-token')

    expect(postSpy).toHaveBeenCalledWith(
      '/admin/reauth',
      { purpose: 'ENABLE_LIVE_TRADING' },
      { headers: { 'X-Admin-Token': 'one-time-token' } },
    )
  })

  it('SystemConfig 갱신은 각 키의 expected_version을 그대로 전달한다', async () => {
    storeAdminToken('stored-token')
    const payload = [
      {
        config_key: 'max_allocation_pct',
        config_value: '25',
        expected_version: 7,
      },
    ]
    const putSpy = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: [] })

    await updateSystemConfigs(payload)

    expect(putSpy).toHaveBeenCalledWith('/system/configs', payload)
  })

  it('AI Banker 설정 승인은 제안 시점 expected_version을 포함한다', async () => {
    storeAdminToken('stored-token')
    const payload = {
      config_key: 'ai_entry_score_threshold',
      config_value: '65',
      expected_version: 11,
    }
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: [] })

    await approveChatConfigChange('session-1', payload)

    expect(postSpy).toHaveBeenCalledWith('/chat/sessions/session-1/approve', payload)
  })

  it('provider 상태 초기화는 일반 설정 PUT이 아닌 전용 CAS endpoint를 사용한다', async () => {
    storeAdminToken('stored-token')
    const response = {
      id: 1,
      config_key: 'ai_provider_status',
      config_value: '{}',
      description: null,
      version: 4,
    }
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: response })

    await expect(resetAiProviderStatus(3)).resolves.toEqual(response)
    expect(postSpy).toHaveBeenCalledWith('/system/ai/providers/status/reset', {
      expected_version: 3,
    })
  })

  it('request interceptor는 명시적 일회성 X-Admin-Token을 저장 토큰으로 덮지 않는다', async () => {
    storeAdminToken('stored-token')
    let observedToken: unknown = null

    await apiClient.get('/interceptor-test', {
      headers: { 'X-Admin-Token': 'one-time-token' },
      adapter: async (config) => {
        observedToken = AxiosHeaders.from(config.headers).get('X-Admin-Token')
        return {
          data: null,
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        }
      },
    })

    expect(observedToken).toBe('one-time-token')
  })

  it('저장된 토큰을 관리자 세션 API의 명시적 header로 검증한다', async () => {
    storeAdminToken('stored-token')
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { authenticated: true } })

    await ensureAdminSession()

    expect(getSpy).toHaveBeenCalledWith('/admin/session', {
      headers: { 'X-Admin-Token': 'stored-token' },
      timeout: 6000,
    })
  })

  it('수동 세션 초기화도 저장 토큰을 지우고 전역 무효화 이벤트를 발행한다', () => {
    storeAdminToken('stored-token')
    let invalidationCount = 0
    const listener = () => {
      invalidationCount += 1
    }
    window.addEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)

    try {
      invalidateAdminSession()
    } finally {
      window.removeEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)
    }

    expect(getStoredAdminToken()).toBeNull()
    expect(invalidationCount).toBe(1)
  })

  it('동시에 세션 확인을 요청해도 관리자 토큰 프롬프트와 검증은 한 번만 수행한다', async () => {
    let promptCount = 0
    const listener = (event: Event) => {
      promptCount += 1
      const detail = (event as CustomEvent<AdminTokenRequestDetail>).detail
      detail.resolve('prompted-token')
    }
    window.addEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener)
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { authenticated: true } })

    try {
      await Promise.all([ensureAdminSession(), ensureAdminSession(), ensureAdminSession()])
    } finally {
      window.removeEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener)
    }

    expect(promptCount).toBe(1)
    expect(getSpy).toHaveBeenCalledTimes(1)
    expect(getSpy).toHaveBeenCalledWith('/admin/session', {
      headers: { 'X-Admin-Token': 'prompted-token' },
      timeout: 6000,
    })
  })

  it.each([
    { label: '503', validationError: axiosResponseError(503) },
    { label: 'transport 오류', validationError: axiosResponseError() },
  ])('저장 토큰 검증의 $label는 재입력 없이 Gate로 전달한다', async ({ validationError }) => {
    storeAdminToken('stored-token')
    let promptCount = 0
    const listener = () => {
      promptCount += 1
    }
    window.addEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener)
    vi.spyOn(apiClient, 'get').mockRejectedValue(validationError)

    try {
      await expect(ensureAdminSession()).rejects.toBe(validationError)
    } finally {
      window.removeEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener)
    }

    expect(promptCount).toBe(0)
    expect(getStoredAdminToken()).toBe('stored-token')
  })

  it('저장 토큰이 401/403으로 거절된 경우에만 폐기하고 한 번 다시 입력받는다', async () => {
    storeAdminToken('expired-token')
    let promptCount = 0
    const listener = (event: Event) => {
      promptCount += 1
      storeAdminToken('replacement-token')
      const detail = (event as CustomEvent<AdminTokenRequestDetail>).detail
      detail.resolve('replacement-token')
    }
    window.addEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener)
    const getSpy = vi
      .spyOn(apiClient, 'get')
      .mockRejectedValueOnce(axiosResponseError(403))
      .mockResolvedValueOnce({ data: { authenticated: true } })

    try {
      await ensureAdminSession()
    } finally {
      window.removeEventListener(ADMIN_TOKEN_REQUIRED_EVENT, listener)
    }

    expect(promptCount).toBe(1)
    expect(getStoredAdminToken()).toBe('replacement-token')
    expect(getSpy).toHaveBeenNthCalledWith(2, '/admin/session', {
      headers: { 'X-Admin-Token': 'replacement-token' },
      timeout: 6000,
    })
  })

  it('Axios 401/403이 현재 저장 토큰을 거절하면 토큰 폐기와 세션 무효화를 함께 알린다', async () => {
    storeAdminToken('rejected-token')
    let invalidationCount = 0
    const listener = () => {
      invalidationCount += 1
    }
    window.addEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)

    try {
      await expect(
        apiClient.get('/axios-auth-failure', {
          adapter: async (config) => {
            throw axiosRequestError(403, config)
          },
        }),
      ).rejects.toBeInstanceOf(AxiosError)
    } finally {
      window.removeEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)
    }

    expect(getStoredAdminToken()).toBeNull()
    expect(invalidationCount).toBe(1)
  })

  it('늦은 Axios 401/403은 이미 교체된 새 토큰을 폐기하거나 무효화하지 않는다', async () => {
    storeAdminToken('old-token')
    let rejectRequest!: () => void
    let invalidationCount = 0
    const listener = () => {
      invalidationCount += 1
    }
    window.addEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)

    const requestPromise = apiClient.get('/slow-axios-auth-failure', {
      adapter: (config) =>
        new Promise((_resolve, reject) => {
          rejectRequest = () => reject(axiosRequestError(403, config))
        }),
    })

    await vi.waitFor(() => expect(rejectRequest).toBeTypeOf('function'))
    storeAdminToken('new-token')
    rejectRequest()

    try {
      await expect(requestPromise).rejects.toBeInstanceOf(AxiosError)
    } finally {
      window.removeEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)
    }

    expect(getStoredAdminToken()).toBe('new-token')
    expect(invalidationCount).toBe(0)
  })

  it('채팅 SSE 요청에 저장 토큰을 첨부하고 401/403 응답이면 토큰을 폐기한다', async () => {
    storeAdminToken('stream-token')
    let invalidationCount = 0
    const listener = () => {
      invalidationCount += 1
    }
    window.addEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)
    const fetchMock = vi.fn().mockResolvedValue({
      status: 403,
      ok: false,
      text: async () => JSON.stringify({ detail: '인증이 만료되었습니다.' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    try {
      await expect(streamChatMessage('session-1', '안녕하세요', vi.fn())).rejects.toThrow(
        '인증이 만료되었습니다.',
      )
    } finally {
      window.removeEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)
    }

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/chat/sessions/session-1/messages'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Accept: 'text/event-stream',
          'Content-Type': 'application/json',
          'X-Admin-Token': 'stream-token',
        }),
      }),
    )
    expect(getStoredAdminToken()).toBeNull()
    expect(invalidationCount).toBe(1)
  })

  it('늦은 SSE 401/403은 이미 교체된 새 토큰을 폐기하거나 무효화하지 않는다', async () => {
    storeAdminToken('old-stream-token')
    let resolveFetch!: (response: {
      status: number
      ok: boolean
      text: () => Promise<string>
    }) => void
    const fetchMock = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    let invalidationCount = 0
    const listener = () => {
      invalidationCount += 1
    }
    window.addEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)

    const streamPromise = streamChatMessage('session-2', '지연 응답', vi.fn())
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    storeAdminToken('new-stream-token')
    resolveFetch({
      status: 403,
      ok: false,
      text: async () => JSON.stringify({ detail: '이전 요청이 거절되었습니다.' }),
    })

    try {
      await expect(streamPromise).rejects.toThrow('이전 요청이 거절되었습니다.')
    } finally {
      window.removeEventListener(ADMIN_SESSION_INVALIDATED_EVENT, listener)
    }

    expect(getStoredAdminToken()).toBe('new-stream-token')
    expect(invalidationCount).toBe(0)
  })
})
