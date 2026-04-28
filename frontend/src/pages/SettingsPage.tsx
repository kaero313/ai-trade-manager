import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import InfoTooltip from '../components/common/InfoTooltip'
import BotConfigForm from '../components/trading/BotConfigForm'
import { useSystemConfigs, useUpdateSystemConfigs } from '../hooks/useSystemConfigs'
import type { SystemConfigItem, SystemConfigUpdateItem } from '../services/api'

interface AiRuntimeDraft {
  autonomousAiIntervalMinutes: string
  maxAllocationPct: string
  hardTakeProfitPct: string
  hardStopLossPct: string
  aiBriefingTime: string
  aiMinConfidenceTrade: string
  aiAnalysisMaxAgeMinutes: string
  aiCustomPersonaPrompt: string
  aiProviderPriority: AiProviderName[]
  aiProviderSettings: AiProviderSettings
  aiProviderStatus: AiProviderStatus
}

interface NoticeState {
  type: 'success' | 'error' | 'info'
  message: string
}

type AiProviderName = 'gemini' | 'openai'

interface AiProviderConfig {
  enabled: boolean
  model: string
}

type AiProviderSettings = Record<AiProviderName, AiProviderConfig>

interface AiProviderStatusItem {
  blocked_until?: string
  reason?: string
  last_error_at?: string
  last_error?: string
  last_success_at?: string
}

type AiProviderStatus = Partial<Record<AiProviderName, AiProviderStatusItem>>

const AUTONOMOUS_AI_INTERVAL_MINUTES_KEY = 'autonomous_ai_interval_minutes'
const MAX_ALLOCATION_PCT_KEY = 'max_allocation_pct'
const HARD_TAKE_PROFIT_PCT_KEY = 'hard_take_profit_pct'
const HARD_STOP_LOSS_PCT_KEY = 'hard_stop_loss_pct'
const AI_BRIEFING_TIME_KEY = 'ai_briefing_time'
const AI_MIN_CONFIDENCE_TRADE_KEY = 'ai_min_confidence_trade'
const AI_ANALYSIS_MAX_AGE_MINUTES_KEY = 'ai_analysis_max_age_minutes'
const AI_CUSTOM_PERSONA_PROMPT_KEY = 'ai_custom_persona_prompt'
const AI_PROVIDER_PRIORITY_KEY = 'ai_provider_priority'
const AI_PROVIDER_SETTINGS_KEY = 'ai_provider_settings'
const AI_PROVIDER_STATUS_KEY = 'ai_provider_status'

const AUTONOMOUS_AI_INTERVAL_OPTIONS = ['15', '30', '60', '120', '240']
const AI_PROVIDERS: AiProviderName[] = ['gemini', 'openai']
const DEFAULT_AI_PROVIDER_PRIORITY: AiProviderName[] = ['gemini', 'openai']
const DEFAULT_AI_PROVIDER_SETTINGS: AiProviderSettings = {
  gemini: { enabled: true, model: 'gemini-3-flash-preview' },
  openai: { enabled: true, model: 'gpt-5-mini' },
}

const PERSONA_PRESETS = [
  {
    key: 'aggressive-scalping',
    label: '공격형 단타',
    value:
      'HOLD는 최소화하고 항상 매수를 긍정적으로 고려하라. RSI가 40 이하이거나 뉴스에서 조금이라도 호재가 발견되면 확신도를 90 이상으로 평가하고 100% 비중의 BUY를 지시하라.',
  },
  {
    key: 'conservative-swing',
    label: '보수형 스윙',
    value:
      '절대 잃지 않는 장기 가치 투자를 지향한다. 조금이라도 애매하거나 이슈가 있으면 무조건 HOLD하라. 오직 RSI가 30 미만이면서 동시에 시장 공포(Fear/Greed)가 20 미만인 극단적 패닉셀 구간에서만 20% 분할 매수(BUY)를 지시해라.',
  },
  {
    key: 'default',
    label: '기본값',
    value: '',
  },
] as const

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (Array.isArray(detail) && detail.length > 0) {
      return String(detail[0]?.msg ?? fallback)
    }
    if (error.message) {
      return error.message
    }
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function findConfigValue(items: SystemConfigItem[] | undefined, configKey: string, fallback: string): string {
  return items?.find((item) => item.config_key === configKey)?.config_value ?? fallback
}

function parseJsonConfig<T>(rawValue: string, fallback: T): T {
  try {
    const parsed = JSON.parse(rawValue) as unknown
    return parsed as T
  } catch {
    return fallback
  }
}

function normalizeProviderPriority(rawValue: string): AiProviderName[] {
  const parsed = parseJsonConfig<unknown>(rawValue, DEFAULT_AI_PROVIDER_PRIORITY)
  const priority = Array.isArray(parsed)
    ? parsed.filter((item): item is AiProviderName => AI_PROVIDERS.includes(item as AiProviderName))
    : DEFAULT_AI_PROVIDER_PRIORITY
  const deduped = priority.filter((provider, index) => priority.indexOf(provider) === index)
  return [...deduped, ...AI_PROVIDERS.filter((provider) => !deduped.includes(provider))]
}

function normalizeProviderSettings(rawValue: string): AiProviderSettings {
  const parsed = parseJsonConfig<Partial<Record<AiProviderName, Partial<AiProviderConfig>>>>(
    rawValue,
    DEFAULT_AI_PROVIDER_SETTINGS,
  )

  return AI_PROVIDERS.reduce((acc, provider) => {
    const providerSettings = parsed[provider] ?? {}
    acc[provider] = {
      enabled: providerSettings.enabled ?? DEFAULT_AI_PROVIDER_SETTINGS[provider].enabled,
      model: String(providerSettings.model ?? DEFAULT_AI_PROVIDER_SETTINGS[provider].model),
    }
    return acc
  }, {} as AiProviderSettings)
}

function normalizeProviderStatus(rawValue: string): AiProviderStatus {
  const parsed = parseJsonConfig<AiProviderStatus>(rawValue, {})
  if (!parsed || typeof parsed !== 'object') {
    return {}
  }
  return parsed
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value)
}

function buildAiRuntimeDraft(items: SystemConfigItem[] | undefined): AiRuntimeDraft {
  return {
    autonomousAiIntervalMinutes: findConfigValue(items, AUTONOMOUS_AI_INTERVAL_MINUTES_KEY, '15'),
    maxAllocationPct: findConfigValue(items, MAX_ALLOCATION_PCT_KEY, '10'),
    hardTakeProfitPct: findConfigValue(items, HARD_TAKE_PROFIT_PCT_KEY, '5.0'),
    hardStopLossPct: findConfigValue(items, HARD_STOP_LOSS_PCT_KEY, '-3.0'),
    aiBriefingTime: findConfigValue(items, AI_BRIEFING_TIME_KEY, '08:30'),
    aiMinConfidenceTrade: findConfigValue(items, AI_MIN_CONFIDENCE_TRADE_KEY, '70'),
    aiAnalysisMaxAgeMinutes: findConfigValue(items, AI_ANALYSIS_MAX_AGE_MINUTES_KEY, '90'),
    aiCustomPersonaPrompt: findConfigValue(items, AI_CUSTOM_PERSONA_PROMPT_KEY, ''),
    aiProviderPriority: normalizeProviderPriority(
      findConfigValue(items, AI_PROVIDER_PRIORITY_KEY, stringifyJson(DEFAULT_AI_PROVIDER_PRIORITY)),
    ),
    aiProviderSettings: normalizeProviderSettings(
      findConfigValue(items, AI_PROVIDER_SETTINGS_KEY, stringifyJson(DEFAULT_AI_PROVIDER_SETTINGS)),
    ),
    aiProviderStatus: normalizeProviderStatus(findConfigValue(items, AI_PROVIDER_STATUS_KEY, '{}')),
  }
}

function NoticeMessage({ notice }: { notice: NoticeState }) {
  return (
    <div
      className={`rounded-xl px-4 py-3 text-sm ${
        notice.type === 'success'
          ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200'
          : notice.type === 'info'
            ? 'border border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-700/40 dark:text-gray-200'
            : 'border border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200'
      }`}
    >
      {notice.message}
    </div>
  )
}

function formatDateTime(value: string | undefined): string {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function resolveProviderStatusLabel(status: AiProviderStatusItem | undefined): {
  tone: 'ready' | 'blocked' | 'error' | 'idle'
  label: string
} {
  const blockedUntil = status?.blocked_until ? new Date(status.blocked_until) : null
  if (blockedUntil && blockedUntil.getTime() > Date.now()) {
    return {
      tone: 'blocked',
      label: `차단 중 · ${formatDateTime(status?.blocked_until)}까지`,
    }
  }
  if (status?.last_error_at) {
    return {
      tone: 'error',
      label: `최근 오류 · ${formatDateTime(status.last_error_at)}`,
    }
  }
  if (status?.last_success_at) {
    return {
      tone: 'ready',
      label: `정상 · ${formatDateTime(status.last_success_at)}`,
    }
  }
  return { tone: 'idle', label: '대기' }
}

function ProviderStatusBadge({ status }: { status: AiProviderStatusItem | undefined }) {
  const resolved = resolveProviderStatusLabel(status)
  const toneClass =
    resolved.tone === 'blocked'
      ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200'
      : resolved.tone === 'error'
        ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200'
        : resolved.tone === 'ready'
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200'
          : 'border-gray-200 bg-white text-gray-600 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300'

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${toneClass}`}>
      {resolved.label}
    </span>
  )
}

function AiRuntimeSettingsPanel() {
  const systemConfigsQuery = useSystemConfigs()
  const updateSystemConfigsMutation = useUpdateSystemConfigs()
  const [draftPatch, setDraftPatch] = useState<Partial<AiRuntimeDraft>>({})
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const serverDraft = useMemo(() => buildAiRuntimeDraft(systemConfigsQuery.data), [systemConfigsQuery.data])
  const draft = useMemo(() => ({ ...serverDraft, ...draftPatch }), [serverDraft, draftPatch])

  const setDraftValue = <K extends keyof AiRuntimeDraft>(key: K, value: AiRuntimeDraft[K]) => {
    setDraftPatch((current) => {
      if (serverDraft[key] === value) {
        const next = { ...current }
        delete next[key]
        return next
      }

      return {
        ...current,
        [key]: value,
      }
    })
  }

  const setProviderPriority = (provider: AiProviderName, nextRank: number) => {
    const others = draft.aiProviderPriority.filter((item) => item !== provider)
    const nextPriority = [...others]
    nextPriority.splice(nextRank - 1, 0, provider)
    setDraftValue('aiProviderPriority', nextPriority)
  }

  const setProviderEnabled = (provider: AiProviderName, enabled: boolean) => {
    setDraftValue('aiProviderSettings', {
      ...draft.aiProviderSettings,
      [provider]: {
        ...draft.aiProviderSettings[provider],
        enabled,
      },
    })
  }

  const setProviderModel = (provider: AiProviderName, model: string) => {
    setDraftValue('aiProviderSettings', {
      ...draft.aiProviderSettings,
      [provider]: {
        ...draft.aiProviderSettings[provider],
        model,
      },
    })
  }

  const clearProviderStatus = () => {
    setDraftValue('aiProviderStatus', {})
  }

  const handleSave = async () => {
    const updates: SystemConfigUpdateItem[] = []

    if (draft.autonomousAiIntervalMinutes !== serverDraft.autonomousAiIntervalMinutes) {
      updates.push({
        config_key: AUTONOMOUS_AI_INTERVAL_MINUTES_KEY,
        config_value: draft.autonomousAiIntervalMinutes,
      })
    }
    if (draft.maxAllocationPct !== serverDraft.maxAllocationPct) {
      updates.push({
        config_key: MAX_ALLOCATION_PCT_KEY,
        config_value: draft.maxAllocationPct,
      })
    }
    if (draft.hardTakeProfitPct !== serverDraft.hardTakeProfitPct) {
      updates.push({
        config_key: HARD_TAKE_PROFIT_PCT_KEY,
        config_value: draft.hardTakeProfitPct,
      })
    }
    if (draft.hardStopLossPct !== serverDraft.hardStopLossPct) {
      updates.push({
        config_key: HARD_STOP_LOSS_PCT_KEY,
        config_value: draft.hardStopLossPct,
      })
    }
    if (draft.aiBriefingTime !== serverDraft.aiBriefingTime) {
      updates.push({
        config_key: AI_BRIEFING_TIME_KEY,
        config_value: draft.aiBriefingTime,
      })
    }
    if (draft.aiMinConfidenceTrade !== serverDraft.aiMinConfidenceTrade) {
      updates.push({
        config_key: AI_MIN_CONFIDENCE_TRADE_KEY,
        config_value: draft.aiMinConfidenceTrade,
      })
    }
    if (draft.aiAnalysisMaxAgeMinutes !== serverDraft.aiAnalysisMaxAgeMinutes) {
      updates.push({
        config_key: AI_ANALYSIS_MAX_AGE_MINUTES_KEY,
        config_value: draft.aiAnalysisMaxAgeMinutes,
      })
    }
    if (draft.aiCustomPersonaPrompt !== serverDraft.aiCustomPersonaPrompt) {
      updates.push({
        config_key: AI_CUSTOM_PERSONA_PROMPT_KEY,
        config_value: draft.aiCustomPersonaPrompt,
      })
    }
    if (stringifyJson(draft.aiProviderPriority) !== stringifyJson(serverDraft.aiProviderPriority)) {
      updates.push({
        config_key: AI_PROVIDER_PRIORITY_KEY,
        config_value: stringifyJson(draft.aiProviderPriority),
      })
    }
    if (stringifyJson(draft.aiProviderSettings) !== stringifyJson(serverDraft.aiProviderSettings)) {
      updates.push({
        config_key: AI_PROVIDER_SETTINGS_KEY,
        config_value: stringifyJson(draft.aiProviderSettings),
      })
    }
    if (stringifyJson(draft.aiProviderStatus) !== stringifyJson(serverDraft.aiProviderStatus)) {
      updates.push({
        config_key: AI_PROVIDER_STATUS_KEY,
        config_value: stringifyJson(draft.aiProviderStatus),
      })
    }

    if (updates.length === 0) {
      setNotice({ type: 'info', message: '변경된 AI 운용 설정이 없습니다.' })
      return
    }

    try {
      await updateSystemConfigsMutation.mutateAsync(updates)
      setDraftPatch({})
      setNotice({
        type: 'success',
        message: 'AI 운용 설정이 저장되었고 백그라운드 워커에 즉시 반영되었습니다.',
      })
    } catch (error) {
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, 'AI 운용 설정을 저장하지 못했습니다.'),
      })
    }
  }

  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="border-b border-gray-200 pb-5 dark:border-gray-700">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-600 dark:text-sky-300">
          AI Runtime Control
        </p>
        <div className="mt-3 flex items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">AI 운용 설정</h2>
          <InfoTooltip
            title="AI 운용 설정"
            content="AI 분석 주기, 체결 기준, 강제 익절·손절, 페르소나처럼 실제 AI 자동매매에 직접 쓰이는 값만 모았습니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          뉴스 수집 주기와 심리지수 캐싱 주기처럼 일반 사용자가 자주 만질 필요가 없는 운영값은 제외했습니다.
        </p>
      </header>

      <div className="mt-6 space-y-6">
        {systemConfigsQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-gray-500 dark:text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin" />
            AI 운용 설정을 불러오는 중입니다.
          </div>
        )}

        {systemConfigsQuery.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            AI 운용 설정을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </div>
        )}

        {!systemConfigsQuery.isLoading && !systemConfigsQuery.isError && (
          <>
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-5 dark:border-gray-700 dark:bg-gray-700/30">
              <div className="flex flex-col gap-3 border-b border-gray-200 pb-4 dark:border-gray-700 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">AI Provider</h3>
                    <InfoTooltip
                      title="AI Provider 우선순위"
                      content="한도에 도달한 provider는 SystemConfig 상태에 기록되고, 해제 시각 전까지 다음 순위 provider를 먼저 사용합니다."
                    />
                  </div>
                  <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
                    API 키는 환경변수에서만 읽고, 여기서는 호출 순서와 모델명만 관리합니다.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={clearProviderStatus}
                  className="inline-flex items-center justify-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  차단 상태 초기화
                </button>
              </div>

              <div className="mt-4 grid gap-3">
                {AI_PROVIDERS.map((provider) => {
                  const providerSettings = draft.aiProviderSettings[provider]
                  const rank = draft.aiProviderPriority.indexOf(provider) + 1
                  return (
                    <div
                      key={provider}
                      className="grid gap-3 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800 lg:grid-cols-[130px_120px_minmax(180px,1fr)_auto]"
                    >
                      <div className="flex items-center justify-between gap-3 lg:block">
                        <div className="text-sm font-semibold uppercase text-gray-900 dark:text-gray-100">
                          {provider}
                        </div>
                        <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-600 dark:text-gray-300 lg:mt-3">
                          <input
                            type="checkbox"
                            checked={providerSettings.enabled}
                            onChange={(event) => setProviderEnabled(provider, event.target.checked)}
                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                          사용
                        </label>
                      </div>

                      <label className="block">
                        <span className="mb-1 block text-xs font-semibold text-gray-500 dark:text-gray-400">
                          우선순위
                        </span>
                        <select
                          value={rank}
                          onChange={(event) => setProviderPriority(provider, Number(event.target.value))}
                          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                        >
                          {AI_PROVIDERS.map((_, index) => (
                            <option key={index + 1} value={index + 1}>
                              {index + 1}순위
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="block">
                        <span className="mb-1 block text-xs font-semibold text-gray-500 dark:text-gray-400">
                          모델명
                        </span>
                        <input
                          value={providerSettings.model}
                          onChange={(event) => setProviderModel(provider, event.target.value)}
                          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                        />
                      </label>

                      <div className="flex min-w-0 items-end">
                        <ProviderStatusBadge status={draft.aiProviderStatus[provider]} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>AI 자율 분석 주기 (분)</span>
                  <InfoTooltip
                    title="AI 자율 분석 주기"
                    content="AI 자율 분석과 실전 집행 루프가 몇 분마다 한 번씩 동작할지 정합니다."
                  />
                </span>
                <select
                  value={draft.autonomousAiIntervalMinutes}
                  onChange={(event) => setDraftValue('autonomousAiIntervalMinutes', event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                >
                  {AUTONOMOUS_AI_INTERVAL_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}분마다
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">추천값: 15분</p>
              </label>

              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>종목당 최대 배팅 비중 (%)</span>
                  <InfoTooltip
                    title="종목당 최대 배팅 비중"
                    content="AI 매수 예산을 계산할 때 총 순자산 대비 종목별 최대 노출 상한으로 쓰입니다."
                  />
                </span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={draft.maxAllocationPct}
                  onChange={(event) => setDraftValue('maxAllocationPct', event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">추천값: 10%</p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>하드 익절 기준 (%)</span>
                  <InfoTooltip
                    title="하드 익절 기준"
                    content="이 값 이상 수익이 난 포지션은 AI 판단을 기다리지 않고 즉시 전량 시장가 매도로 정리합니다. 0이면 비활성화됩니다."
                  />
                </span>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={draft.hardTakeProfitPct}
                  onChange={(event) => setDraftValue('hardTakeProfitPct', event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">0이면 비활성화, 예: 5.0</p>
              </label>

              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>하드 손절 기준 (%)</span>
                  <InfoTooltip
                    title="하드 손절 기준"
                    content="손실률이 이 값 이하로 내려가면 AI 판단을 기다리지 않고 전량 시장가 매도합니다. 0이면 비활성화됩니다."
                  />
                </span>
                <input
                  type="number"
                  max="0"
                  step="0.1"
                  value={draft.hardStopLossPct}
                  onChange={(event) => setDraftValue('hardStopLossPct', event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">0이면 비활성화, 예: -3.0</p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>AI 자율 체결 최소 확신도</span>
                  <InfoTooltip
                    title="AI 자율 체결 최소 확신도"
                    content="AI가 지시한 확신 점수(0~100)가 이 값보다 낮으면 실제 주문을 내지 않고 스킵합니다."
                  />
                </span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={draft.aiMinConfidenceTrade}
                  onChange={(event) => setDraftValue('aiMinConfidenceTrade', event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">추천값: 70~80</p>
              </label>

              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>AI 분석 로그 유효 기간 (분)</span>
                  <InfoTooltip
                    title="AI 분석 로그 유효 기간"
                    content="스케줄러가 분석한 리포트가 생성된 지 몇 분 이내여야 주문을 실행할지 결정합니다."
                  />
                </span>
                <input
                  type="number"
                  min="1"
                  value={draft.aiAnalysisMaxAgeMinutes}
                  onChange={(event) => setDraftValue('aiAnalysisMaxAgeMinutes', event.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">추천값: 90분</p>
              </label>
            </div>

            <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
              <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                <span>일일 AI 브리핑 실행 시각</span>
                <InfoTooltip
                  title="일일 AI 브리핑 실행 시각"
                  content="슬랙/메신저용 일일 브리핑 배치가 매일 몇 시에 동작할지 정합니다."
                />
              </span>
              <input
                type="time"
                value={draft.aiBriefingTime}
                onChange={(event) => setDraftValue('aiBriefingTime', event.target.value)}
                className="w-full max-w-[220px] rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
              />
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">예: 08:30</p>
            </label>

            <div className="rounded-2xl border border-violet-200 bg-violet-50/70 p-5 dark:border-violet-500/20 dark:bg-violet-500/10">
              <div className="flex flex-col gap-3 border-b border-violet-200 pb-4 dark:border-violet-500/20">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    AI 매매 철학 및 페르소나
                  </h3>
                  <InfoTooltip
                    title="AI 매매 철학 및 페르소나"
                    content="여기에 입력한 텍스트는 SystemConfig의 ai_custom_persona_prompt로 저장되고, 백엔드 AI 분석 System Prompt에 추가됩니다."
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {PERSONA_PRESETS.map((preset) => (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={() => setDraftValue('aiCustomPersonaPrompt', preset.value)}
                      className="inline-flex items-center rounded-full border border-violet-200 bg-white px-3 py-1.5 text-xs font-semibold text-violet-700 transition hover:border-violet-300 hover:bg-violet-100 dark:border-violet-400/20 dark:bg-gray-800 dark:text-violet-200 dark:hover:border-violet-300/40 dark:hover:bg-violet-500/10"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4">
                <textarea
                  value={draft.aiCustomPersonaPrompt}
                  onChange={(event) => setDraftValue('aiCustomPersonaPrompt', event.target.value)}
                  placeholder="예: 손실 회피를 최우선으로 삼고, 뉴스 리스크가 있으면 HOLD를 우선하라."
                  className="min-h-[220px] w-full rounded-2xl border border-violet-200 bg-white px-4 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-300 dark:border-violet-400/20 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500 dark:focus:border-violet-300 dark:focus:ring-violet-400/30"
                />
              </div>
            </div>

            {notice && <NoticeMessage notice={notice} />}

            <div className="flex flex-col gap-3 border-t border-gray-200 pt-4 dark:border-gray-700 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-gray-500 dark:text-gray-400">
                저장 즉시 SystemConfig에 반영되고 스케줄러 대상 값은 재등록됩니다.
              </div>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={updateSystemConfigsMutation.isPending}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {updateSystemConfigsMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>{updateSystemConfigsMutation.isPending ? '저장 중...' : 'AI 운용 설정 저장'}</span>
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function SettingsPage() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-6">
      <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <h1 className="text-3xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
          설정
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          자동매매에 필요한 종목, 배분, 운용 기준을 조정합니다.
        </p>
      </section>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-1">
        <BotConfigForm />
        <AiRuntimeSettingsPanel />
      </div>
    </div>
  )
}

export default SettingsPage
