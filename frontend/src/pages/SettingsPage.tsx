import { isAxiosError } from 'axios'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import InfoTooltip from '../components/common/InfoTooltip'
import BotConfigForm from '../components/trading/BotConfigForm'
import {
  useAiProviderRuntimeStatus,
  useSystemConfigs,
  useUpdateSystemConfigs,
} from '../hooks/useSystemConfigs'
import {
  clearAdminToken,
  type AiProviderRuntimeStatusItem,
  type SystemConfigItem,
  type SystemConfigUpdateItem,
} from '../services/api'

interface AiRuntimeDraft {
  newsIntervalHours: string
  autonomousAiIntervalMinutes: string
  maxAllocationPct: string
  hardTakeProfitPct: string
  hardStopLossPct: string
  aiBriefingTime: string
  aiMinConfidenceTrade: string
  aiEntryScoreThreshold: string
  aiAnalysisMaxAgeMinutes: string
  liveBuyEnabled: boolean
  aiEntryShadowMode: boolean
  ragScheduledOpenaiTranslationFallbackEnabled: boolean
  ragBuyPrecheckNewsRefreshEnabled: boolean
  ragBuyPrecheckNewsMaxAgeMinutes: string
  aiCustomPersonaPrompt: string
  aiProviderPriority: AiProviderName[]
  aiProviderSettings: AiProviderSettings
  aiProviderStatus: AiProviderStatus
  slackPortfolioAlertSettings: SlackPortfolioAlertSettings
}

interface NoticeState {
  type: 'success' | 'error' | 'info'
  message: string
}

type AiProviderName = 'gemini' | 'openai'
type BuySafetyMode = 'locked' | 'shadow' | 'live'
type AiModelPurpose =
  | 'trade_analysis'
  | 'buy_precheck'
  | 'portfolio_briefing'
  | 'chat'
  | 'news_sentiment'
  | 'news_translation'
  | 'backtest_briefing'

interface AiProviderConfig {
  enabled: boolean
  model: string
  models: Partial<Record<AiModelPurpose, string>>
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
type SlackAlertMode = 'preset' | 'advanced'
type SlackAlertPreset =
  | 'daily_once'
  | 'daily_twice'
  | 'weekday_once'
  | 'weekday_twice'
  | 'weekend_once'
  | 'weekly_once'
  | 'mon_wed_fri'
  | 'tue_thu'
type SlackAlertWeekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
type SlackAlertSection = 'portfolio' | 'fear_index' | 'favorite_ai_signals' | 'market_impact_news'
type SlackAlertDecision = 'BUY' | 'SELL' | 'HOLD'

interface SlackAlertRule {
  id: string
  enabled: boolean
  weekdays: SlackAlertWeekday[]
  times: string[]
  sections: SlackAlertSection[]
  signal_decisions: SlackAlertDecision[]
  min_confidence: number
}

interface SlackPortfolioAlertSettings {
  enabled: boolean
  mode: SlackAlertMode
  preset: SlackAlertPreset
  rules: SlackAlertRule[]
}

const AUTONOMOUS_AI_INTERVAL_MINUTES_KEY = 'autonomous_ai_interval_minutes'
const NEWS_INTERVAL_HOURS_KEY = 'news_interval_hours'
const MAX_ALLOCATION_PCT_KEY = 'max_allocation_pct'
const HARD_TAKE_PROFIT_PCT_KEY = 'hard_take_profit_pct'
const HARD_STOP_LOSS_PCT_KEY = 'hard_stop_loss_pct'
const AI_BRIEFING_TIME_KEY = 'ai_briefing_time'
const AI_MIN_CONFIDENCE_TRADE_KEY = 'ai_min_confidence_trade'
const AI_ENTRY_SCORE_THRESHOLD_KEY = 'ai_entry_score_threshold'
const AI_ANALYSIS_MAX_AGE_MINUTES_KEY = 'ai_analysis_max_age_minutes'
const LIVE_BUY_ENABLED_KEY = 'live_buy_enabled'
const AI_ENTRY_SHADOW_MODE_KEY = 'ai_entry_shadow_mode'
const RAG_SCHEDULED_OPENAI_TRANSLATION_FALLBACK_ENABLED_KEY =
  'rag_scheduled_openai_translation_fallback_enabled'
const RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY = 'rag_buy_precheck_news_refresh_enabled'
const RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY = 'rag_buy_precheck_news_max_age_minutes'
const AI_CUSTOM_PERSONA_PROMPT_KEY = 'ai_custom_persona_prompt'
const AI_PROVIDER_PRIORITY_KEY = 'ai_provider_priority'
const AI_PROVIDER_SETTINGS_KEY = 'ai_provider_settings'
const AI_PROVIDER_STATUS_KEY = 'ai_provider_status'
const SLACK_PORTFOLIO_ALERT_SETTINGS_KEY = 'slack_portfolio_alert_settings'

const AUTONOMOUS_AI_INTERVAL_OPTIONS = ['15', '30', '60', '120', '240']
const AI_PROVIDERS: AiProviderName[] = ['gemini', 'openai']
const DEFAULT_AI_PROVIDER_PRIORITY: AiProviderName[] = ['gemini', 'openai']
const AI_MODEL_SUGGESTIONS = ['gpt-5-nano', 'gpt-4.1-nano', 'gpt-4o-mini', 'gpt-4.1-mini', 'gpt-5-mini']
const AI_MODEL_PURPOSES: Array<{
  key: AiModelPurpose
  label: string
  description: string
}> = [
  {
    key: 'trade_analysis',
    label: '1차 매매 판단',
    description: '정기 자율 분석에 사용하는 저비용 모델',
  },
  {
    key: 'buy_precheck',
    label: 'BUY 직전 검증',
    description: 'Entry Gate 통과 후 주문 직전 2차 검증 모델',
  },
  {
    key: 'portfolio_briefing',
    label: '포트폴리오 브리핑',
    description: '포트폴리오 요약과 리스크 설명',
  },
  {
    key: 'chat',
    label: 'AI Banker',
    description: 'AI Banker 대화와 도구 호출 판단',
  },
  {
    key: 'news_sentiment',
    label: '뉴스 감성',
    description: '수집 뉴스의 시장 감성 요약',
  },
  {
    key: 'news_translation',
    label: '뉴스 번역',
    description: 'RAG 저장 전 한국어 번역 fallback',
  },
  {
    key: 'backtest_briefing',
    label: '백테스트 브리핑',
    description: '백테스트 결과 해석 요약',
  },
]
const DEFAULT_OPENAI_PURPOSE_MODELS: Record<AiModelPurpose, string> = {
  trade_analysis: 'gpt-5-nano',
  buy_precheck: 'gpt-4.1-mini',
  portfolio_briefing: 'gpt-5-nano',
  chat: 'gpt-5-nano',
  news_sentiment: 'gpt-5-nano',
  news_translation: 'gpt-5-nano',
  backtest_briefing: 'gpt-5-nano',
}
const DEFAULT_AI_PROVIDER_SETTINGS: AiProviderSettings = {
  gemini: { enabled: true, model: 'gemini-3-flash-preview', models: {} },
  openai: { enabled: true, model: 'gpt-5-nano', models: DEFAULT_OPENAI_PURPOSE_MODELS },
}
const BUY_SAFETY_MODE_OPTIONS: Array<{
  key: BuySafetyMode
  eyebrow: string
  label: string
  description: string
  badge: string
}> = [
  {
    key: 'locked',
    eyebrow: 'LOCKED',
    label: 'BUY 주문 잠금',
    description: 'AI가 BUY를 판단해도 신규 실거래 매수 주문을 전송하지 않습니다.',
    badge: '차단',
  },
  {
    key: 'shadow',
    eyebrow: 'SHADOW MODE',
    label: 'BUY 후보 기록 전용',
    description: 'BUY 후보를 주문하지 않고 AI 추론 로그로만 남깁니다.',
    badge: '기록 전용',
  },
  {
    key: 'live',
    eyebrow: 'LIVE BUY',
    label: '실거래 신규 매수 허용',
    description: 'Entry Gate를 통과한 BUY 후보가 실제 주문 단계로 이동할 수 있습니다.',
    badge: '허용',
  },
]
const SLACK_ALERT_WEEKDAY_OPTIONS: Array<{ key: SlackAlertWeekday; label: string }> = [
  { key: 'mon', label: '월' },
  { key: 'tue', label: '화' },
  { key: 'wed', label: '수' },
  { key: 'thu', label: '목' },
  { key: 'fri', label: '금' },
  { key: 'sat', label: '토' },
  { key: 'sun', label: '일' },
]
const SLACK_ALERT_PRESET_OPTIONS: Array<{
  key: SlackAlertPreset
  label: string
  weekdays: SlackAlertWeekday[]
  times: string[]
}> = [
  {
    key: 'daily_once',
    label: '매일 1회',
    weekdays: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
    times: ['08:30'],
  },
  {
    key: 'daily_twice',
    label: '매일 2회',
    weekdays: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
    times: ['08:30', '18:30'],
  },
  {
    key: 'weekday_once',
    label: '평일 1회',
    weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
    times: ['08:30'],
  },
  {
    key: 'weekday_twice',
    label: '평일 2회',
    weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
    times: ['08:30', '18:30'],
  },
  { key: 'weekend_once', label: '주말 1회', weekdays: ['sat', 'sun'], times: ['10:00'] },
  { key: 'weekly_once', label: '주 1회', weekdays: ['mon'], times: ['09:00'] },
  { key: 'mon_wed_fri', label: '월/수/금', weekdays: ['mon', 'wed', 'fri'], times: ['08:30'] },
  { key: 'tue_thu', label: '화/목', weekdays: ['tue', 'thu'], times: ['08:30'] },
]
const SLACK_ALERT_SECTION_OPTIONS: Array<{ key: SlackAlertSection; label: string }> = [
  { key: 'portfolio', label: '포트폴리오' },
  { key: 'fear_index', label: '오늘 공포지수' },
  { key: 'favorite_ai_signals', label: '관심종목 AI 신호' },
  { key: 'market_impact_news', label: '가격 영향 뉴스' },
]
const SLACK_ALERT_DECISION_OPTIONS: Array<{ key: SlackAlertDecision; label: string }> = [
  { key: 'BUY', label: 'BUY' },
  { key: 'SELL', label: 'SELL' },
  { key: 'HOLD', label: 'HOLD' },
]
const DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS: SlackPortfolioAlertSettings = {
  enabled: false,
  mode: 'preset',
  preset: 'daily_once',
  rules: [
    {
      id: 'daily_once',
      enabled: true,
      weekdays: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
      times: ['08:30'],
      sections: ['portfolio', 'fear_index', 'favorite_ai_signals', 'market_impact_news'],
      signal_decisions: ['BUY', 'SELL'],
      min_confidence: 70,
    },
  ],
}

const SETTINGS_CARD_CLASS = 'quantum-card rounded-xl p-5 text-[#dfe2eb] sm:p-6'
const SETTINGS_PANEL_CLASS = 'quantum-panel rounded-lg border border-[#3b494b]/30 p-4'
const SETTINGS_FIELD_CLASS =
  'w-full rounded-lg border border-[#3b494b]/45 bg-[#0a0e14]/70 px-3 py-2 text-sm text-[#dfe2eb] outline-none transition placeholder:text-[#849495] focus:border-[#00dbe9]/70 focus:ring-2 focus:ring-[#00dbe9]/20 disabled:cursor-not-allowed disabled:bg-[#262a31]/60 disabled:text-[#849495]'
const SETTINGS_PRIMARY_BUTTON_CLASS =
  'inline-flex items-center justify-center gap-2 rounded-lg bg-[#00dbe9]/16 px-4 py-2 text-sm font-bold text-[#7df4ff] transition hover:bg-[#00dbe9]/24 disabled:cursor-not-allowed disabled:opacity-60'
const SETTINGS_SECONDARY_BUTTON_CLASS =
  'inline-flex items-center justify-center gap-2 rounded-lg border border-[#3b494b]/50 bg-[#0a0e14]/70 px-3 py-2 text-sm font-bold text-[#dfe2eb] transition hover:border-[#00dbe9]/45 hover:text-[#7df4ff]'
const SETTINGS_LABEL_CLASS = 'mb-2 flex items-center gap-2 text-sm font-bold text-[#dfe2eb]'
const SETTINGS_HINT_CLASS = 'mt-2 text-xs text-[#849495]'

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
    const rawModels =
      providerSettings.models && typeof providerSettings.models === 'object'
        ? providerSettings.models
        : {}
    const defaultModels = DEFAULT_AI_PROVIDER_SETTINGS[provider].models
    acc[provider] = {
      enabled: providerSettings.enabled ?? DEFAULT_AI_PROVIDER_SETTINGS[provider].enabled,
      model: String(providerSettings.model ?? DEFAULT_AI_PROVIDER_SETTINGS[provider].model),
      models: AI_MODEL_PURPOSES.reduce((models, purpose) => {
        const rawModel = rawModels[purpose.key]
        const defaultModel = defaultModels[purpose.key]
        if (rawModel || defaultModel) {
          models[purpose.key] = String(rawModel ?? defaultModel)
        }
        return models
      }, {} as Partial<Record<AiModelPurpose, string>>),
    }
    return acc
  }, {} as AiProviderSettings)
}

function normalizeSlackAlertTime(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }
  const match = value.trim().match(/^(\d{1,2}):(\d{1,2})$/)
  if (!match) {
    return null
  }
  const hour = Number(match[1])
  const minute = Number(match[2])
  if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return null
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function uniqueValues<T extends string>(values: T[]): T[] {
  return values.filter((value, index) => values.indexOf(value) === index)
}

function normalizeSlackAlertWeekdays(value: unknown): SlackAlertWeekday[] {
  if (!Array.isArray(value)) {
    return []
  }
  const allowed = SLACK_ALERT_WEEKDAY_OPTIONS.map((item) => item.key)
  return uniqueValues(
    value.filter((item): item is SlackAlertWeekday => allowed.includes(item as SlackAlertWeekday)),
  )
}

function normalizeSlackAlertSections(value: unknown): SlackAlertSection[] {
  if (!Array.isArray(value)) {
    return ['portfolio', 'fear_index', 'favorite_ai_signals', 'market_impact_news']
  }
  const allowed = SLACK_ALERT_SECTION_OPTIONS.map((item) => item.key)
  const sections = value.filter((item): item is SlackAlertSection => allowed.includes(item as SlackAlertSection))
  return uniqueValues(sections).length > 0
    ? uniqueValues(sections)
    : ['portfolio', 'fear_index', 'favorite_ai_signals', 'market_impact_news']
}

function normalizeSlackAlertDecisions(value: unknown): SlackAlertDecision[] {
  if (!Array.isArray(value)) {
    return ['BUY', 'SELL']
  }
  const allowed = SLACK_ALERT_DECISION_OPTIONS.map((item) => item.key)
  const decisions = value.filter((item): item is SlackAlertDecision => allowed.includes(item as SlackAlertDecision))
  return uniqueValues(decisions).length > 0 ? uniqueValues(decisions) : ['BUY', 'SELL']
}

function normalizeSlackAlertConfidence(value: unknown): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return 70
  }
  return Math.max(0, Math.min(100, Math.round(parsed)))
}

function sanitizeSlackRuleId(value: unknown, fallback: string): string {
  const sanitized = String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return sanitized || fallback
}

function buildPresetSlackAlertRules(
  preset: SlackAlertPreset,
  template?: Partial<SlackAlertRule>,
): SlackAlertRule[] {
  const presetOption =
    SLACK_ALERT_PRESET_OPTIONS.find((option) => option.key === preset) ?? SLACK_ALERT_PRESET_OPTIONS[0]
  return [
    {
      id: preset,
      enabled: template?.enabled ?? true,
      weekdays: [...presetOption.weekdays],
      times: [...presetOption.times],
      sections: template?.sections ?? [
        'portfolio',
        'fear_index',
        'favorite_ai_signals',
        'market_impact_news',
      ],
      signal_decisions: template?.signal_decisions ?? ['BUY', 'SELL'],
      min_confidence: template?.min_confidence ?? 70,
    },
  ]
}

function createSlackAlertRule(index: number): SlackAlertRule {
  return {
    id: `custom_${index + 1}`,
    enabled: true,
    weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'],
    times: ['08:30'],
    sections: ['portfolio', 'fear_index', 'market_impact_news'],
    signal_decisions: ['BUY', 'SELL'],
    min_confidence: 70,
  }
}

function normalizeSlackAlertRule(value: unknown, index: number): SlackAlertRule | null {
  if (!value || typeof value !== 'object') {
    return null
  }
  const rawRule = value as Partial<SlackAlertRule>
  const weekdays = normalizeSlackAlertWeekdays(rawRule.weekdays)
  const times = Array.isArray(rawRule.times)
    ? uniqueValues(
        rawRule.times
          .map((time) => normalizeSlackAlertTime(time))
          .filter((time): time is string => time !== null),
      )
    : []
  if (weekdays.length === 0 || times.length === 0) {
    return null
  }
  return {
    id: sanitizeSlackRuleId(rawRule.id, `rule_${index + 1}`),
    enabled: rawRule.enabled ?? true,
    weekdays,
    times,
    sections: normalizeSlackAlertSections(rawRule.sections),
    signal_decisions: normalizeSlackAlertDecisions(rawRule.signal_decisions),
    min_confidence: normalizeSlackAlertConfidence(rawRule.min_confidence),
  }
}

function normalizeSlackPortfolioAlertSettings(rawValue: string): SlackPortfolioAlertSettings {
  const parsed = parseJsonConfig<Partial<SlackPortfolioAlertSettings>>(
    rawValue,
    DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS,
  )
  const mode: SlackAlertMode = parsed.mode === 'advanced' ? 'advanced' : 'preset'
  const preset = SLACK_ALERT_PRESET_OPTIONS.some((option) => option.key === parsed.preset)
    ? (parsed.preset as SlackAlertPreset)
    : 'daily_once'
  const rawRules = Array.isArray(parsed.rules) ? parsed.rules : []
  const normalizedRules = rawRules
    .map((rule, index) => normalizeSlackAlertRule(rule, index))
    .filter((rule): rule is SlackAlertRule => rule !== null)
  return {
    enabled: parsed.enabled ?? false,
    mode,
    preset,
    rules: normalizedRules.length > 0 ? normalizedRules : buildPresetSlackAlertRules(preset),
  }
}

function toggleArrayValue<T extends string>(values: T[], value: T, checked: boolean): T[] {
  if (checked) {
    return values.includes(value) ? values : [...values, value]
  }
  const nextValues = values.filter((item) => item !== value)
  return nextValues.length > 0 ? nextValues : values
}

function resolveBuySafetyMode(draft: Pick<AiRuntimeDraft, 'liveBuyEnabled' | 'aiEntryShadowMode'>): BuySafetyMode {
  if (draft.aiEntryShadowMode) {
    return 'shadow'
  }
  if (draft.liveBuyEnabled) {
    return 'live'
  }
  return 'locked'
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

function parseBooleanConfig(rawValue: string, fallback: boolean): boolean {
  const normalized = rawValue.trim().toLowerCase()
  if (['true', '1', 'yes', 'on'].includes(normalized)) {
    return true
  }
  if (['false', '0', 'no', 'off'].includes(normalized)) {
    return false
  }
  return fallback
}

function stringifyBooleanConfig(value: boolean): string {
  return value ? 'true' : 'false'
}

function buildAiRuntimeDraft(items: SystemConfigItem[] | undefined): AiRuntimeDraft {
  return {
    newsIntervalHours: findConfigValue(items, NEWS_INTERVAL_HOURS_KEY, '12'),
    autonomousAiIntervalMinutes: findConfigValue(items, AUTONOMOUS_AI_INTERVAL_MINUTES_KEY, '60'),
    maxAllocationPct: findConfigValue(items, MAX_ALLOCATION_PCT_KEY, '10'),
    hardTakeProfitPct: findConfigValue(items, HARD_TAKE_PROFIT_PCT_KEY, '5.0'),
    hardStopLossPct: findConfigValue(items, HARD_STOP_LOSS_PCT_KEY, '-3.0'),
    aiBriefingTime: findConfigValue(items, AI_BRIEFING_TIME_KEY, '08:30'),
    aiMinConfidenceTrade: findConfigValue(items, AI_MIN_CONFIDENCE_TRADE_KEY, '75'),
    aiEntryScoreThreshold: findConfigValue(items, AI_ENTRY_SCORE_THRESHOLD_KEY, '60'),
    aiAnalysisMaxAgeMinutes: findConfigValue(items, AI_ANALYSIS_MAX_AGE_MINUTES_KEY, '90'),
    liveBuyEnabled: parseBooleanConfig(findConfigValue(items, LIVE_BUY_ENABLED_KEY, 'false'), false),
    aiEntryShadowMode: parseBooleanConfig(findConfigValue(items, AI_ENTRY_SHADOW_MODE_KEY, 'true'), true),
    ragScheduledOpenaiTranslationFallbackEnabled: parseBooleanConfig(
      findConfigValue(items, RAG_SCHEDULED_OPENAI_TRANSLATION_FALLBACK_ENABLED_KEY, 'false'),
      false,
    ),
    ragBuyPrecheckNewsRefreshEnabled: parseBooleanConfig(
      findConfigValue(items, RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY, 'true'),
      true,
    ),
    ragBuyPrecheckNewsMaxAgeMinutes: findConfigValue(
      items,
      RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY,
      '60',
    ),
    aiCustomPersonaPrompt: findConfigValue(items, AI_CUSTOM_PERSONA_PROMPT_KEY, ''),
    aiProviderPriority: normalizeProviderPriority(
      findConfigValue(items, AI_PROVIDER_PRIORITY_KEY, stringifyJson(DEFAULT_AI_PROVIDER_PRIORITY)),
    ),
    aiProviderSettings: normalizeProviderSettings(
      findConfigValue(items, AI_PROVIDER_SETTINGS_KEY, stringifyJson(DEFAULT_AI_PROVIDER_SETTINGS)),
    ),
    aiProviderStatus: normalizeProviderStatus(findConfigValue(items, AI_PROVIDER_STATUS_KEY, '{}')),
    slackPortfolioAlertSettings: normalizeSlackPortfolioAlertSettings(
      findConfigValue(
        items,
        SLACK_PORTFOLIO_ALERT_SETTINGS_KEY,
        stringifyJson(DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS),
      ),
    ),
  }
}

function NoticeMessage({ notice }: { notice: NoticeState }) {
  return (
    <div
      className={`rounded-xl px-4 py-3 text-sm ${
        notice.type === 'success'
          ? 'bg-[#00dbe9]/10 font-semibold text-[#7df4ff]'
          : notice.type === 'info'
            ? 'bg-[#262a31]/70 text-[#dfe2eb]'
            : 'bg-[#ffb4ab]/10 font-semibold text-[#ffb4ab]'
      }`}
    >
      {notice.message}
    </div>
  )
}

function formatDateTime(value: string | null | undefined): string {
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

function resolveRuntimeStatusLabel(status: AiProviderRuntimeStatusItem['status']): string {
  if (status === 'active') {
    return '다음 요청 1순위'
  }
  if (status === 'fallback_ready') {
    return 'Fallback 후보'
  }
  if (status === 'blocked') {
    return '차단 중'
  }
  if (status === 'disabled') {
    return '비활성'
  }
  if (status === 'missing_key') {
    return 'API 키 없음'
  }
  if (status === 'error') {
    return '오류 확인'
  }
  return '대기'
}

function resolveRuntimeStatusClassName(status: AiProviderRuntimeStatusItem['status']): string {
  if (status === 'active') {
    return 'bg-[#00dbe9]/12 text-[#7df4ff]'
  }
  if (status === 'fallback_ready') {
    return 'bg-[#cdbdff]/12 text-[#cdbdff]'
  }
  if (status === 'blocked') {
    return 'bg-[#eac324]/12 text-[#ffe179]'
  }
  if (status === 'missing_key' || status === 'error') {
    return 'bg-[#ffb4ab]/12 text-[#ffb4ab]'
  }
  return 'bg-[#262a31]/70 text-[#b9cacb]'
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
      ? 'bg-[#eac324]/12 text-[#ffe179]'
      : resolved.tone === 'error'
        ? 'bg-[#ffb4ab]/12 text-[#ffb4ab]'
        : resolved.tone === 'ready'
          ? 'bg-[#00dbe9]/12 text-[#7df4ff]'
          : 'bg-[#262a31]/70 text-[#b9cacb]'

  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${toneClass}`}>
      {resolved.label}
    </span>
  )
}

function ProviderRuntimeInsight({
  runtimeStatus,
  status,
}: {
  runtimeStatus: AiProviderRuntimeStatusItem | undefined
  status: AiProviderStatusItem | undefined
}) {
  if (!runtimeStatus) {
    return (
      <div className="space-y-2">
        <ProviderStatusBadge status={status} />
        <p className="text-xs text-[#849495]">실행 상태를 확인하는 중입니다.</p>
      </div>
    )
  }

  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${resolveRuntimeStatusClassName(
            runtimeStatus.status,
          )}`}
        >
          {resolveRuntimeStatusLabel(runtimeStatus.status)}
        </span>
        <span className="inline-flex items-center rounded-full bg-[#262a31]/70 px-2.5 py-1 text-xs font-bold text-[#b9cacb]">
          키 {runtimeStatus.api_key_configured ? '설정됨' : '없음'}
        </span>
      </div>

      <div className="space-y-1 text-xs leading-5 text-[#849495]">
        <p>실행 모델: {runtimeStatus.model}</p>
        {runtimeStatus.skip_reason && <p>제외 사유: {runtimeStatus.skip_reason}</p>}
        {runtimeStatus.reason && <p>차단 사유: {runtimeStatus.reason}</p>}
        {runtimeStatus.blocked_until && <p>재시도 가능: {formatDateTime(runtimeStatus.blocked_until)}</p>}
        {runtimeStatus.last_success_at && <p>마지막 성공: {formatDateTime(runtimeStatus.last_success_at)}</p>}
        {runtimeStatus.last_error_at && <p>최근 오류: {formatDateTime(runtimeStatus.last_error_at)}</p>}
        {runtimeStatus.last_error && (
          <p className="line-clamp-2 break-words text-[#ffb4ab]">
            {runtimeStatus.last_error}
          </p>
        )}
      </div>
    </div>
  )
}

function SlackAlertRuleEditor({
  rule,
  ruleIndex,
  mode,
  onChange,
  onRemove,
}: {
  rule: SlackAlertRule
  ruleIndex: number
  mode: SlackAlertMode
  onChange: (rule: SlackAlertRule) => void
  onRemove: () => void
}) {
  const updateTimes = (times: string[]) => {
    onChange({
      ...rule,
      times: times
        .map((time) => normalizeSlackAlertTime(time))
        .filter((time): time is string => time !== null),
    })
  }

  return (
    <div className="rounded-lg border border-[#3b494b]/35 bg-[#0a0e14]/70 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <label className="inline-flex items-center gap-2 text-sm font-bold text-[#dfe2eb]">
          <input
            type="checkbox"
            checked={rule.enabled}
            onChange={(event) => onChange({ ...rule, enabled: event.target.checked })}
            className="h-4 w-4 rounded border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
          />
          알림 규칙 {ruleIndex + 1}
        </label>
        {mode === 'advanced' && (
          <button
            type="button"
            onClick={onRemove}
            className="inline-flex w-fit items-center gap-2 rounded-lg border border-[#ffb4ab]/35 bg-[#ffb4ab]/10 px-3 py-2 text-xs font-bold text-[#ffb4ab] transition hover:bg-[#ffb4ab]/16"
          >
            <Trash2 className="h-3.5 w-3.5" />
            삭제
          </button>
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(180px,260px)]">
        <label className="block">
          <span className={SETTINGS_LABEL_CLASS}>규칙 ID</span>
          <input
            value={rule.id}
            disabled={mode === 'preset'}
            onChange={(event) =>
              onChange({ ...rule, id: sanitizeSlackRuleId(event.target.value, `rule_${ruleIndex + 1}`) })
            }
            className={SETTINGS_FIELD_CLASS}
          />
          <p className={SETTINGS_HINT_CLASS}>job id에 사용되는 영문/숫자 식별자입니다.</p>
        </label>

        <label className="block">
          <span className={SETTINGS_LABEL_CLASS}>최소 확신도</span>
          <input
            type="number"
            min="0"
            max="100"
            value={rule.min_confidence}
            onChange={(event) =>
              onChange({ ...rule, min_confidence: normalizeSlackAlertConfidence(event.target.value) })
            }
            className={SETTINGS_FIELD_CLASS}
          />
          <p className={SETTINGS_HINT_CLASS}>관심종목 AI 신호 필터입니다.</p>
        </label>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <span className={SETTINGS_LABEL_CLASS}>요일</span>
          <div className="grid grid-cols-7 gap-2">
            {SLACK_ALERT_WEEKDAY_OPTIONS.map((option) => (
              <label
                key={option.key}
                className={`flex cursor-pointer items-center justify-center rounded-lg border px-2 py-2 text-xs font-bold transition ${
                  rule.weekdays.includes(option.key)
                    ? 'border-[#00dbe9]/55 bg-[#00dbe9]/12 text-[#7df4ff]'
                    : 'border-[#3b494b]/35 bg-[#10141a]/70 text-[#b9cacb]'
                }`}
              >
                <input
                  type="checkbox"
                  checked={rule.weekdays.includes(option.key)}
                  onChange={(event) =>
                    onChange({
                      ...rule,
                      weekdays: toggleArrayValue(rule.weekdays, option.key, event.target.checked),
                    })
                  }
                  className="sr-only"
                />
                {option.label}
              </label>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between gap-3">
            <span className={SETTINGS_LABEL_CLASS}>시간</span>
            <button
              type="button"
              onClick={() => updateTimes([...rule.times, '09:00'])}
              className="inline-flex items-center gap-1 rounded-lg bg-[#00dbe9]/12 px-2.5 py-1 text-xs font-bold text-[#7df4ff] transition hover:bg-[#00dbe9]/18"
            >
              <Plus className="h-3.5 w-3.5" />
              추가
            </button>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {rule.times.map((time, timeIndex) => (
              <div key={`${rule.id}-${timeIndex}`} className="flex items-center gap-2">
                <input
                  type="time"
                  value={time}
                  onChange={(event) => {
                    const nextTimes = rule.times.map((item, index) =>
                      index === timeIndex ? event.target.value : item,
                    )
                    updateTimes(nextTimes)
                  }}
                  className={SETTINGS_FIELD_CLASS}
                />
                <button
                  type="button"
                  onClick={() =>
                    rule.times.length > 1 && updateTimes(rule.times.filter((_, index) => index !== timeIndex))
                  }
                  disabled={rule.times.length <= 1}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[#3b494b]/45 text-[#b9cacb] transition hover:border-[#ffb4ab]/45 hover:text-[#ffb4ab] disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="시간 삭제"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <span className={SETTINGS_LABEL_CLASS}>알림 종류</span>
          <div className="grid gap-2 sm:grid-cols-3">
            {SLACK_ALERT_SECTION_OPTIONS.map((option) => (
              <label key={option.key} className="inline-flex items-center gap-2 text-sm text-[#b9cacb]">
                <input
                  type="checkbox"
                  checked={rule.sections.includes(option.key)}
                  onChange={(event) =>
                    onChange({
                      ...rule,
                      sections: toggleArrayValue(rule.sections, option.key, event.target.checked),
                    })
                  }
                  className="h-4 w-4 rounded border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
                />
                {option.label}
              </label>
            ))}
          </div>
        </div>

        <div>
          <span className={SETTINGS_LABEL_CLASS}>AI 신호</span>
          <div className="grid grid-cols-3 gap-2">
            {SLACK_ALERT_DECISION_OPTIONS.map((option) => (
              <label
                key={option.key}
                className={`flex cursor-pointer items-center justify-center rounded-lg border px-3 py-2 text-xs font-bold transition ${
                  rule.signal_decisions.includes(option.key)
                    ? 'border-[#cdbdff]/55 bg-[#cdbdff]/12 text-[#cdbdff]'
                    : 'border-[#3b494b]/35 bg-[#10141a]/70 text-[#b9cacb]'
                }`}
              >
                <input
                  type="checkbox"
                  checked={rule.signal_decisions.includes(option.key)}
                  onChange={(event) =>
                    onChange({
                      ...rule,
                      signal_decisions: toggleArrayValue(
                        rule.signal_decisions,
                        option.key,
                        event.target.checked,
                      ),
                    })
                  }
                  className="sr-only"
                />
                {option.label}
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function AiRuntimeSettingsPanel() {
  const systemConfigsQuery = useSystemConfigs()
  const aiProviderRuntimeStatusQuery = useAiProviderRuntimeStatus()
  const updateSystemConfigsMutation = useUpdateSystemConfigs()
  const [draftPatch, setDraftPatch] = useState<Partial<AiRuntimeDraft>>({})
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const serverDraft = useMemo(() => buildAiRuntimeDraft(systemConfigsQuery.data), [systemConfigsQuery.data])
  const draft = useMemo(() => ({ ...serverDraft, ...draftPatch }), [serverDraft, draftPatch])
  const runtimeStatusByProvider = useMemo(() => {
    const entries = aiProviderRuntimeStatusQuery.data?.providers.map((item) => [item.provider, item])
    return new Map<AiProviderName, AiProviderRuntimeStatusItem>(
      (entries ?? []) as Array<[AiProviderName, AiProviderRuntimeStatusItem]>,
    )
  }, [aiProviderRuntimeStatusQuery.data?.providers])
  const activeProvider = aiProviderRuntimeStatusQuery.data?.active_provider ?? null
  const buySafetyMode = resolveBuySafetyMode(draft)
  const candidateProviders =
    aiProviderRuntimeStatusQuery.data?.providers
      .filter((item) => item.is_candidate)
      .map((item) => item.provider.toUpperCase())
      .join(' → ') ?? ''

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

  const setProviderPurposeModel = (
    provider: AiProviderName,
    purpose: AiModelPurpose,
    model: string,
  ) => {
    setDraftValue('aiProviderSettings', {
      ...draft.aiProviderSettings,
      [provider]: {
        ...draft.aiProviderSettings[provider],
        models: {
          ...draft.aiProviderSettings[provider].models,
          [purpose]: model,
        },
      },
    })
  }

  const setBuySafetyMode = (mode: BuySafetyMode) => {
    setDraftValue('liveBuyEnabled', mode === 'live')
    setDraftValue('aiEntryShadowMode', mode === 'shadow')
  }

  const clearProviderStatus = () => {
    setDraftValue('aiProviderStatus', {})
    setNotice({ type: 'info', message: '차단 상태 초기화가 대기 중입니다. 저장하면 즉시 반영됩니다.' })
  }

  const setSlackAlertSettings = (settings: SlackPortfolioAlertSettings) => {
    setDraftValue('slackPortfolioAlertSettings', settings)
  }

  const updateSlackAlertRule = (ruleIndex: number, nextRule: SlackAlertRule) => {
    setSlackAlertSettings({
      ...draft.slackPortfolioAlertSettings,
      rules: draft.slackPortfolioAlertSettings.rules.map((rule, index) =>
        index === ruleIndex ? nextRule : rule,
      ),
    })
  }

  const setSlackAlertMode = (mode: SlackAlertMode) => {
    const presetRules = buildPresetSlackAlertRules(
      draft.slackPortfolioAlertSettings.preset,
      draft.slackPortfolioAlertSettings.rules[0],
    )
    setSlackAlertSettings({
      ...draft.slackPortfolioAlertSettings,
      mode,
      rules: mode === 'preset' ? presetRules : draft.slackPortfolioAlertSettings.rules,
    })
  }

  const setSlackAlertPreset = (preset: SlackAlertPreset) => {
    setSlackAlertSettings({
      ...draft.slackPortfolioAlertSettings,
      mode: 'preset',
      preset,
      rules: buildPresetSlackAlertRules(preset, draft.slackPortfolioAlertSettings.rules[0]),
    })
  }

  const addSlackAlertRule = () => {
    setSlackAlertSettings({
      ...draft.slackPortfolioAlertSettings,
      mode: 'advanced',
      rules: [
        ...draft.slackPortfolioAlertSettings.rules,
        createSlackAlertRule(draft.slackPortfolioAlertSettings.rules.length),
      ],
    })
  }

  const removeSlackAlertRule = (ruleIndex: number) => {
    const nextRules = draft.slackPortfolioAlertSettings.rules.filter((_, index) => index !== ruleIndex)
    setSlackAlertSettings({
      ...draft.slackPortfolioAlertSettings,
      rules: nextRules.length > 0 ? nextRules : [createSlackAlertRule(0)],
    })
  }

  const handleSave = async () => {
    const updates: SystemConfigUpdateItem[] = []

    if (draft.newsIntervalHours !== serverDraft.newsIntervalHours) {
      updates.push({
        config_key: NEWS_INTERVAL_HOURS_KEY,
        config_value: draft.newsIntervalHours,
      })
    }
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
    if (draft.aiEntryScoreThreshold !== serverDraft.aiEntryScoreThreshold) {
      updates.push({
        config_key: AI_ENTRY_SCORE_THRESHOLD_KEY,
        config_value: draft.aiEntryScoreThreshold,
      })
    }
    if (draft.aiAnalysisMaxAgeMinutes !== serverDraft.aiAnalysisMaxAgeMinutes) {
      updates.push({
        config_key: AI_ANALYSIS_MAX_AGE_MINUTES_KEY,
        config_value: draft.aiAnalysisMaxAgeMinutes,
      })
    }
    if (
      draft.ragScheduledOpenaiTranslationFallbackEnabled !==
      serverDraft.ragScheduledOpenaiTranslationFallbackEnabled
    ) {
      updates.push({
        config_key: RAG_SCHEDULED_OPENAI_TRANSLATION_FALLBACK_ENABLED_KEY,
        config_value: stringifyBooleanConfig(draft.ragScheduledOpenaiTranslationFallbackEnabled),
      })
    }
    if (draft.ragBuyPrecheckNewsRefreshEnabled !== serverDraft.ragBuyPrecheckNewsRefreshEnabled) {
      updates.push({
        config_key: RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY,
        config_value: stringifyBooleanConfig(draft.ragBuyPrecheckNewsRefreshEnabled),
      })
    }
    if (draft.ragBuyPrecheckNewsMaxAgeMinutes !== serverDraft.ragBuyPrecheckNewsMaxAgeMinutes) {
      updates.push({
        config_key: RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY,
        config_value: draft.ragBuyPrecheckNewsMaxAgeMinutes,
      })
    }
    if (draft.liveBuyEnabled !== serverDraft.liveBuyEnabled) {
      updates.push({
        config_key: LIVE_BUY_ENABLED_KEY,
        config_value: stringifyBooleanConfig(draft.liveBuyEnabled),
      })
    }
    if (draft.aiEntryShadowMode !== serverDraft.aiEntryShadowMode) {
      updates.push({
        config_key: AI_ENTRY_SHADOW_MODE_KEY,
        config_value: stringifyBooleanConfig(draft.aiEntryShadowMode),
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
    if (
      stringifyJson(draft.slackPortfolioAlertSettings) !==
      stringifyJson(serverDraft.slackPortfolioAlertSettings)
    ) {
      updates.push({
        config_key: SLACK_PORTFOLIO_ALERT_SETTINGS_KEY,
        config_value: stringifyJson(draft.slackPortfolioAlertSettings),
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
    <section className={SETTINGS_CARD_CLASS}>
      <header className="border-b border-[#3b494b]/35 pb-5">
        <div className="flex items-center gap-2">
          <h2 className="text-2xl font-bold text-[#dfe2eb]">AI 운용 설정</h2>
          <InfoTooltip
            title="AI 운용 설정"
            content="AI 분석 주기, 체결 기준, 강제 익절·손절, 페르소나처럼 실제 AI 자동매매에 직접 쓰이는 값만 모았습니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#b9cacb]">
          AI 호출 주기, 뉴스 갱신, BUY 안전락, 모델 라우팅을 한 화면에서 조정합니다.
        </p>
      </header>

      <div className="mt-6 space-y-6">
        {systemConfigsQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-[#b9cacb]">
            <Loader2 className="h-5 w-5 animate-spin text-[#00dbe9]" />
            AI 운용 설정을 불러오는 중입니다.
          </div>
        )}

        {systemConfigsQuery.isError && (
          <div className="rounded-lg bg-[#ffb4ab]/10 px-4 py-3 text-sm font-semibold text-[#ffb4ab]">
            AI 운용 설정을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </div>
        )}

        {!systemConfigsQuery.isLoading && !systemConfigsQuery.isError && (
          <>
            <div className={SETTINGS_PANEL_CLASS}>
              <div className="flex flex-col gap-3 border-b border-[#3b494b]/35 pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-[#dfe2eb]">AI Provider</h3>
                    <InfoTooltip
                      title="AI Provider 우선순위"
                      content="한도에 도달한 provider는 SystemConfig 상태에 기록되고, 해제 시각 전까지 다음 순위 provider를 먼저 사용합니다."
                    />
                  </div>
                  <p className="mt-1 text-sm leading-6 text-[#b9cacb]">
                    API 키는 환경변수에서만 읽고, 여기서는 호출 순서와 모델명만 관리합니다.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={clearProviderStatus}
                  className={SETTINGS_SECONDARY_BUTTON_CLASS}
                >
                  차단 상태 초기화
                </button>
              </div>

              <div className="mt-4 rounded-lg bg-[#00dbe9]/10 px-4 py-3 text-sm text-[#b9cacb]">
                {aiProviderRuntimeStatusQuery.isError ? (
                  <p>Provider 실행 상태를 불러오지 못했습니다. 저장된 설정값은 계속 표시됩니다.</p>
                ) : (
                  <div className="grid gap-1">
                    <p className="font-bold text-[#7df4ff]">
                      다음 AI 요청 시작점:{' '}
                      {activeProvider ? activeProvider.toUpperCase() : '사용 가능한 provider 없음'}
                    </p>
                    <p>
                      현재 fallback 후보:{' '}
                      {candidateProviders || '환경변수 키, 사용 여부, 차단 상태를 확인해야 합니다.'}
                    </p>
                  </div>
                )}
              </div>

              <div className="mt-4 grid gap-3">
                {AI_PROVIDERS.map((provider) => {
                  const providerSettings = draft.aiProviderSettings[provider]
                  const rank = draft.aiProviderPriority.indexOf(provider) + 1
                  const runtimeStatus = runtimeStatusByProvider.get(provider)
                  return (
                    <div
                      key={provider}
                      className="grid gap-3 rounded-lg bg-[#0a0e14]/70 p-4 lg:grid-cols-[130px_120px_minmax(180px,1fr)_minmax(220px,1fr)]"
                    >
                      <div className="flex items-center justify-between gap-3 lg:block">
                        <div className="text-sm font-bold uppercase text-[#dfe2eb]">
                          {provider}
                        </div>
                        <label className="inline-flex items-center gap-2 text-xs font-bold text-[#b9cacb] lg:mt-3">
                          <input
                            type="checkbox"
                            checked={providerSettings.enabled}
                            onChange={(event) => setProviderEnabled(provider, event.target.checked)}
                            className="h-4 w-4 rounded border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
                          />
                          사용
                        </label>
                      </div>

                      <label className="block">
                        <span className="mb-1 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                          우선순위
                        </span>
                        <select
                          value={rank}
                          onChange={(event) => setProviderPriority(provider, Number(event.target.value))}
                          className={SETTINGS_FIELD_CLASS}
                        >
                          {AI_PROVIDERS.map((_, index) => (
                            <option key={index + 1} value={index + 1}>
                              {index + 1}순위
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="block">
                        <span className="mb-1 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                          모델명
                        </span>
                        <input
                          value={providerSettings.model}
                          onChange={(event) => setProviderModel(provider, event.target.value)}
                          className={SETTINGS_FIELD_CLASS}
                        />
                      </label>

                      <div className="min-w-0">
                        <span className="mb-1 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                          실행 상태
                        </span>
                        <ProviderRuntimeInsight
                          runtimeStatus={runtimeStatus}
                          status={draft.aiProviderStatus[provider]}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="mt-5 rounded-lg bg-[#0a0e14]/70 p-4">
                <datalist id="ai-model-routing-options">
                  {AI_MODEL_SUGGESTIONS.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
                <div className="flex flex-col gap-2 border-b border-[#3b494b]/30 pb-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h4 className="text-base font-bold text-[#dfe2eb]">용도별 모델 라우팅</h4>
                    <p className="mt-1 text-sm leading-6 text-[#b9cacb]">
                      OpenAI 호출 목적별 모델을 분리합니다. 비어 있는 값은 provider 기본 모델로 fallback됩니다.
                    </p>
                  </div>
                  <span className="inline-flex w-fit rounded-full bg-[#00dbe9]/12 px-3 py-1 text-xs font-bold text-[#7df4ff]">
                    비용 최적화
                  </span>
                </div>

                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  <label className="block rounded-lg bg-[#10141a]/80 p-3">
                    <span className="mb-1 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                      기본 모델
                    </span>
                    <input
                      list="ai-model-routing-options"
                      value={draft.aiProviderSettings.openai.model}
                      onChange={(event) => setProviderModel('openai', event.target.value)}
                      className={SETTINGS_FIELD_CLASS}
                    />
                    <span className="mt-2 block text-xs leading-5 text-[#849495]">
                      목적별 모델이 없는 OpenAI 호출의 기본 fallback입니다.
                    </span>
                  </label>

                  {AI_MODEL_PURPOSES.map((purpose) => (
                    <label key={purpose.key} className="block rounded-lg bg-[#10141a]/80 p-3">
                      <span className="mb-1 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                        {purpose.label}
                      </span>
                      <input
                        list="ai-model-routing-options"
                        value={draft.aiProviderSettings.openai.models[purpose.key] ?? ''}
                        onChange={(event) =>
                          setProviderPurposeModel('openai', purpose.key, event.target.value)
                        }
                        className={SETTINGS_FIELD_CLASS}
                      />
                      <span className="mt-2 block text-xs leading-5 text-[#849495]">
                        {purpose.description}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className={SETTINGS_PANEL_CLASS}>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-[#dfe2eb]">실거래 BUY 안전락</h3>
                    <InfoTooltip
                      title="실거래 BUY 안전락"
                      content="AI 판단 성향과 별개로 실제 신규 매수 주문을 허용할지 결정하는 최상위 안전 스위치입니다."
                    />
                  </div>
                  <p className="mt-1 text-sm leading-6 text-[#b9cacb]">
                    공격형 설정을 사용해도 아래 안전락이 잠겨 있으면 신규 BUY 주문은 전송되지 않습니다.
                  </p>
                </div>
                <span
                  className={`inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-bold ${
                    buySafetyMode === 'live'
                      ? 'bg-[#00dbe9]/12 text-[#7df4ff]'
                      : buySafetyMode === 'shadow'
                        ? 'bg-[#ffe179]/12 text-[#ffe179]'
                        : 'bg-[#ffb4ab]/12 text-[#ffb4ab]'
                  }`}
                >
                  {buySafetyMode === 'live'
                    ? 'LIVE BUY 가능'
                    : buySafetyMode === 'shadow'
                      ? 'SHADOW 기록 중'
                      : 'BUY 잠금'}
                </span>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-3" role="radiogroup" aria-label="실거래 BUY 운용 모드">
                {BUY_SAFETY_MODE_OPTIONS.map((option) => {
                  const isSelected = buySafetyMode === option.key
                  const selectedClassName =
                    option.key === 'live'
                      ? 'border-[#00dbe9]/55 bg-[#00dbe9]/10'
                      : option.key === 'shadow'
                        ? 'border-[#ffe179]/50 bg-[#ffe179]/10'
                        : 'border-[#ffb4ab]/45 bg-[#ffb4ab]/10'
                  const badgeClassName =
                    option.key === 'live'
                      ? 'bg-[#00dbe9]/14 text-[#7df4ff]'
                      : option.key === 'shadow'
                        ? 'bg-[#ffe179]/14 text-[#ffe179]'
                        : 'bg-[#ffb4ab]/12 text-[#ffb4ab]'

                  return (
                    <label
                      key={option.key}
                      className={`flex min-h-[156px] cursor-pointer flex-col justify-between rounded-lg border p-4 transition ${
                        isSelected
                          ? selectedClassName
                          : 'border-[#3b494b]/30 bg-[#0a0e14]/70 hover:border-[#00dbe9]/35'
                      }`}
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span>
                          <span className="block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
                            {option.eyebrow}
                          </span>
                          <span className="mt-2 block text-base font-bold text-[#dfe2eb]">
                            {option.label}
                          </span>
                        </span>
                        <input
                          type="radio"
                          name="buy-safety-mode"
                          checked={isSelected}
                          onChange={() => setBuySafetyMode(option.key)}
                          className="h-4 w-4 border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
                        />
                      </span>
                      <span className="mt-4 text-sm leading-6 text-[#b9cacb]">
                        {option.description}
                      </span>
                      <span className={`mt-4 inline-flex w-fit rounded-full px-2.5 py-1 text-xs font-bold ${badgeClassName}`}>
                        {option.badge}
                      </span>
                    </label>
                  )
                })}
              </div>

              <p className="mt-4 rounded-lg bg-[#ffb4ab]/10 px-4 py-3 text-xs font-semibold leading-6 text-[#ffdad6]">
                실제 매수는 이 스위치 외에도 Entry Gate, 최소 확신도, 자산 조회, 봇 런타임 상태를 모두 통과해야 실행됩니다.
              </p>
            </div>

            <div className={SETTINGS_PANEL_CLASS}>
              <div className="flex flex-col gap-3 border-b border-[#3b494b]/35 pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-[#dfe2eb]">RAG 뉴스 비용 제어</h3>
                    <InfoTooltip
                      title="정기 수집과 BUY 직전 갱신"
                      content="정기 뉴스 수집은 비용을 줄이는 방향으로 운용하고, 실제 BUY 후보가 생긴 경우에만 주문 직전 뉴스 최신화를 허용합니다."
                    />
                  </div>
                  <p className="mt-1 text-sm leading-6 text-[#b9cacb]">
                    평소에는 12시간 단위로 수집하고, Gemini 한도 초과 시 OpenAI 번역 fallback을 막아 비용 폭주를 줄입니다.
                  </p>
                </div>
                <span className="inline-flex w-fit rounded-full bg-[#00dbe9]/12 px-3 py-1 text-xs font-bold text-[#7df4ff]">
                  COST GUARD
                </span>
              </div>

              <div className="mt-4 grid gap-4 md:grid-cols-3">
                <label className="block">
                  <span className={SETTINGS_LABEL_CLASS}>뉴스 수집 주기(시간)</span>
                  <input
                    type="number"
                    min="1"
                    max="24"
                    value={draft.newsIntervalHours}
                    onChange={(event) => setDraftValue('newsIntervalHours', event.target.value)}
                    className={SETTINGS_FIELD_CLASS}
                  />
                  <p className={SETTINGS_HINT_CLASS}>추천값: 12시간</p>
                </label>

                <label className="flex h-full flex-col justify-between rounded-lg bg-[#10141a]/80 p-3">
                  <span>
                    <span className={SETTINGS_LABEL_CLASS}>정기 번역 fallback</span>
                    <span className="mt-2 block text-sm leading-6 text-[#b9cacb]">
                      정기 수집에서 Gemini rate limit 시 OpenAI 번역 fallback 허용
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    checked={draft.ragScheduledOpenaiTranslationFallbackEnabled}
                    onChange={(event) =>
                      setDraftValue(
                        'ragScheduledOpenaiTranslationFallbackEnabled',
                        event.target.checked,
                      )
                    }
                    className="mt-4 h-4 w-4 rounded border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
                  />
                </label>

                <label className="flex h-full flex-col justify-between rounded-lg bg-[#10141a]/80 p-3">
                  <span>
                    <span className={SETTINGS_LABEL_CLASS}>BUY 직전 뉴스 갱신</span>
                    <span className="mt-2 block text-sm leading-6 text-[#b9cacb]">
                      Entry Gate 통과 BUY 후보에만 최신 뉴스 갱신 허용
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    checked={draft.ragBuyPrecheckNewsRefreshEnabled}
                    onChange={(event) =>
                      setDraftValue('ragBuyPrecheckNewsRefreshEnabled', event.target.checked)
                    }
                    className="mt-4 h-4 w-4 rounded border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
                  />
                </label>
              </div>

              <label className="mt-4 block max-w-xs">
                <span className={SETTINGS_LABEL_CLASS}>BUY 직전 뉴스 허용 나이(분)</span>
                <input
                  type="number"
                  min="1"
                  max="1440"
                  value={draft.ragBuyPrecheckNewsMaxAgeMinutes}
                  onChange={(event) =>
                    setDraftValue('ragBuyPrecheckNewsMaxAgeMinutes', event.target.value)
                  }
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>추천값: 60분</p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
                  <span>AI 자율 분석 주기 (분)</span>
                  <InfoTooltip
                    title="AI 자율 분석 주기"
                    content="AI 자율 분석과 실전 집행 루프가 몇 분마다 한 번씩 동작할지 정합니다."
                  />
                </span>
                <select
                  value={draft.autonomousAiIntervalMinutes}
                  onChange={(event) => setDraftValue('autonomousAiIntervalMinutes', event.target.value)}
                  className={SETTINGS_FIELD_CLASS}
                >
                  {AUTONOMOUS_AI_INTERVAL_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}분마다
                    </option>
                  ))}
                </select>
                <p className={SETTINGS_HINT_CLASS}>비용 절감 추천값: 60분</p>
              </label>

              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
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
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>추천값: 10%</p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
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
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>0이면 비활성화, 예: 5.0</p>
              </label>

              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
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
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>0이면 비활성화, 예: -3.0</p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
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
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>균형형 추천값: 75</p>
              </label>

              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
                  <span>Entry Gate 점수 기준</span>
                  <InfoTooltip
                    title="Entry Gate 점수 기준"
                    content="AI가 BUY를 제안해도 기술 지표, 리스크, 보유 상태를 합산한 진입 점수가 이 값보다 낮으면 주문 직전 단계로 넘기지 않습니다."
                  />
                </span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={draft.aiEntryScoreThreshold}
                  onChange={(event) => setDraftValue('aiEntryScoreThreshold', event.target.value)}
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>균형형 추천값: 60</p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className={SETTINGS_PANEL_CLASS}>
                <span className={SETTINGS_LABEL_CLASS}>
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
                  className={SETTINGS_FIELD_CLASS}
                />
                <p className={SETTINGS_HINT_CLASS}>추천값: 90분</p>
              </label>
            </div>

            <label className={SETTINGS_PANEL_CLASS}>
              <span className={SETTINGS_LABEL_CLASS}>
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
                className={`${SETTINGS_FIELD_CLASS} max-w-[220px]`}
              />
              <p className={SETTINGS_HINT_CLASS}>예: 08:30</p>
            </label>

            <div className={SETTINGS_PANEL_CLASS}>
              <div className="flex flex-col gap-3 border-b border-[#3b494b]/35 pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-[#dfe2eb]">Slack 포트폴리오 알림</h3>
                    <InfoTooltip
                      title="Slack 포트폴리오 알림"
                      content="포트폴리오, 공포지수, 관심종목 AI 신호를 선택한 반복 규칙에 맞춰 Slack 채널로 보냅니다."
                    />
                  </div>
                  <p className="mt-1 text-sm leading-6 text-[#b9cacb]">
                    빠른 설정은 대표 반복 패턴을 바로 만들고, 고급 설정은 규칙별 요일·시간·알림 종류를 따로 지정합니다.
                  </p>
                </div>
                <label className="inline-flex items-center gap-2 text-sm font-bold text-[#dfe2eb]">
                  <input
                    type="checkbox"
                    checked={draft.slackPortfolioAlertSettings.enabled}
                    onChange={(event) =>
                      setSlackAlertSettings({
                        ...draft.slackPortfolioAlertSettings,
                        enabled: event.target.checked,
                      })
                    }
                    className="h-4 w-4 rounded border-[#3b494b] bg-[#10141a] text-[#00dbe9] focus:ring-[#00dbe9]/30"
                  />
                  알림 사용
                </label>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
                <label className="block">
                  <span className={SETTINGS_LABEL_CLASS}>설정 방식</span>
                  <select
                    value={draft.slackPortfolioAlertSettings.mode}
                    onChange={(event) => setSlackAlertMode(event.target.value as SlackAlertMode)}
                    className={SETTINGS_FIELD_CLASS}
                  >
                    <option value="preset">빠른 설정</option>
                    <option value="advanced">고급 설정</option>
                  </select>
                </label>

                {draft.slackPortfolioAlertSettings.mode === 'preset' ? (
                  <label className="block">
                    <span className={SETTINGS_LABEL_CLASS}>프리셋</span>
                    <select
                      value={draft.slackPortfolioAlertSettings.preset}
                      onChange={(event) => setSlackAlertPreset(event.target.value as SlackAlertPreset)}
                      className={SETTINGS_FIELD_CLASS}
                    >
                      {SLACK_ALERT_PRESET_OPTIONS.map((option) => (
                        <option key={option.key} value={option.key}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <p className={SETTINGS_HINT_CLASS}>
                      프리셋도 아래 규칙 카드에서 시간과 알림 종류를 조정할 수 있습니다.
                    </p>
                  </label>
                ) : (
                  <div className="flex items-end justify-start">
                    <button
                      type="button"
                      onClick={addSlackAlertRule}
                      className={SETTINGS_SECONDARY_BUTTON_CLASS}
                    >
                      <Plus className="h-4 w-4" />
                      알림 규칙 추가
                    </button>
                  </div>
                )}
              </div>

              <div className="mt-4 space-y-3">
                {draft.slackPortfolioAlertSettings.rules.map((rule, ruleIndex) => (
                  <SlackAlertRuleEditor
                    key={`${rule.id}-${ruleIndex}`}
                    rule={rule}
                    ruleIndex={ruleIndex}
                    mode={draft.slackPortfolioAlertSettings.mode}
                    onChange={(nextRule) => updateSlackAlertRule(ruleIndex, nextRule)}
                    onRemove={() => removeSlackAlertRule(ruleIndex)}
                  />
                ))}
              </div>
            </div>

            <div className={SETTINGS_PANEL_CLASS}>
              <div className="flex flex-col gap-3 border-b border-[#3b494b]/35 pb-4">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-bold text-[#dfe2eb]">
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
                      className="inline-flex items-center rounded-lg bg-[#cdbdff]/10 px-3 py-1.5 text-xs font-bold text-[#cdbdff] transition hover:bg-[#cdbdff]/16"
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
                  className={`${SETTINGS_FIELD_CLASS} min-h-[220px] resize-y leading-6`}
                />
              </div>
            </div>

            {notice && <NoticeMessage notice={notice} />}

            <div className="flex flex-col gap-3 border-t border-[#3b494b]/35 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-[#849495]">
                저장 즉시 SystemConfig에 반영되고 스케줄러 대상 값은 재등록됩니다.
              </div>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={updateSystemConfigsMutation.isPending}
                className={SETTINGS_PRIMARY_BUTTON_CLASS}
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
  const [adminTokenNotice, setAdminTokenNotice] = useState<string | null>(null)

  const handleClearAdminToken = () => {
    clearAdminToken()
    setAdminTokenNotice('이 브라우저 세션에 저장된 운영 관리 토큰을 초기화했습니다.')
  }

  return (
    <div className="dashboard-quantum flex h-full min-h-0 min-w-0 flex-col gap-5">
      <section className={SETTINGS_CARD_CLASS}>
        <h1 className="text-3xl font-bold tracking-tight text-[#dfe2eb]">
          설정
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#b9cacb]">
          자동매매에 필요한 종목, 배분, 운용 기준을 조정합니다.
        </p>
        <div className="mt-4 flex flex-col gap-3 rounded-lg bg-[#0a0e14]/75 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-bold text-[#dfe2eb]">운영 관리 토큰</p>
            <p className="mt-1 text-xs leading-5 text-[#849495]">
              관리 토큰은 sessionStorage에만 저장되며 브라우저 세션 단위로 사용됩니다.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClearAdminToken}
            className={SETTINGS_SECONDARY_BUTTON_CLASS}
          >
            관리 토큰 초기화
          </button>
        </div>
        {adminTokenNotice && (
          <p className="mt-3 rounded-lg bg-[#00dbe9]/10 px-3 py-2 text-xs font-semibold text-[#7df4ff]">
            {adminTokenNotice}
          </p>
        )}
      </section>

      <div className="min-h-0 min-w-0 flex-1 space-y-5 overflow-y-auto pr-1">
        <BotConfigForm />
        <AiRuntimeSettingsPanel />
      </div>
    </div>
  )
}

export default SettingsPage
