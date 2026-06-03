import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'

import InfoTooltip from '../common/InfoTooltip'
import { getBotConfig, updateBotConfig, type BotConfig } from '../../services/api'

type StrategyConfig = NonNullable<BotConfig['strategy']>
type RiskConfig = NonNullable<BotConfig['risk']>
type ScheduleConfig = NonNullable<BotConfig['schedule']>

interface NormalizedBotConfig {
  symbols: string[]
  allocation_pct_per_symbol: number[]
  strategy: StrategyConfig
  risk: RiskConfig
  schedule: ScheduleConfig
}

interface BotConfigDraft {
  symbols: string
  allocationPctPerSymbol: string
}

const BOT_CONFIG_QUERY_KEY = ['bot-config'] as const

const SETTINGS_CARD_CLASS = 'quantum-card rounded-xl p-5 text-[#dfe2eb] sm:p-6'
const SETTINGS_PANEL_CLASS = 'quantum-panel rounded-lg border border-[#3b494b]/30 p-4'
const SETTINGS_FIELD_CLASS =
  'w-full rounded-lg border border-[#3b494b]/45 bg-[#0a0e14]/70 px-3 py-2 text-sm text-[#dfe2eb] outline-none transition placeholder:text-[#849495] focus:border-[#00dbe9]/70 focus:ring-2 focus:ring-[#00dbe9]/20 disabled:cursor-not-allowed disabled:bg-[#262a31]/60 disabled:text-[#849495]'
const SETTINGS_PRIMARY_BUTTON_CLASS =
  'inline-flex items-center justify-center gap-2 rounded-lg bg-[#00dbe9]/16 px-4 py-2 text-sm font-bold text-[#7df4ff] transition hover:bg-[#00dbe9]/24 disabled:cursor-not-allowed disabled:opacity-60'

const DEFAULT_BOT_CONFIG: NormalizedBotConfig = {
  symbols: ['KRW-BTC'],
  allocation_pct_per_symbol: [1.0],
  strategy: {
    ema_fast: 12,
    ema_slow: 26,
    rsi: 14,
    rsi_min: 50,
    trailing_stop_pct: 0.03,
  },
  risk: {
    max_capital_pct: 0.1,
    max_daily_loss_pct: 0.05,
    position_size_pct: 0.2,
    max_concurrent_positions: 3,
    cooldown_minutes: 60,
  },
  schedule: {
    enabled: true,
    start_hour: null,
    end_hour: null,
  },
}

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

function normalizeBotConfig(config: BotConfig | undefined): NormalizedBotConfig {
  return {
    symbols:
      Array.isArray(config?.symbols) && config.symbols.length > 0
        ? config.symbols
        : DEFAULT_BOT_CONFIG.symbols,
    allocation_pct_per_symbol:
      Array.isArray(config?.allocation_pct_per_symbol) && config.allocation_pct_per_symbol.length > 0
        ? config.allocation_pct_per_symbol
        : DEFAULT_BOT_CONFIG.allocation_pct_per_symbol,
    strategy: {
      ema_fast: config?.strategy?.ema_fast ?? DEFAULT_BOT_CONFIG.strategy.ema_fast,
      ema_slow: config?.strategy?.ema_slow ?? DEFAULT_BOT_CONFIG.strategy.ema_slow,
      rsi: config?.strategy?.rsi ?? DEFAULT_BOT_CONFIG.strategy.rsi,
      rsi_min: config?.strategy?.rsi_min ?? DEFAULT_BOT_CONFIG.strategy.rsi_min,
      trailing_stop_pct:
        config?.strategy?.trailing_stop_pct ?? DEFAULT_BOT_CONFIG.strategy.trailing_stop_pct,
    },
    risk: {
      max_capital_pct: config?.risk?.max_capital_pct ?? DEFAULT_BOT_CONFIG.risk.max_capital_pct,
      max_daily_loss_pct:
        config?.risk?.max_daily_loss_pct ?? DEFAULT_BOT_CONFIG.risk.max_daily_loss_pct,
      position_size_pct: config?.risk?.position_size_pct ?? DEFAULT_BOT_CONFIG.risk.position_size_pct,
      max_concurrent_positions:
        config?.risk?.max_concurrent_positions ?? DEFAULT_BOT_CONFIG.risk.max_concurrent_positions,
      cooldown_minutes: config?.risk?.cooldown_minutes ?? DEFAULT_BOT_CONFIG.risk.cooldown_minutes,
    },
    schedule: {
      enabled: config?.schedule?.enabled ?? DEFAULT_BOT_CONFIG.schedule.enabled,
      start_hour: config?.schedule?.start_hour ?? DEFAULT_BOT_CONFIG.schedule.start_hour,
      end_hour: config?.schedule?.end_hour ?? DEFAULT_BOT_CONFIG.schedule.end_hour,
    },
  }
}

function createDraft(config: NormalizedBotConfig): BotConfigDraft {
  return {
    symbols: config.symbols.join(', '),
    allocationPctPerSymbol: config.allocation_pct_per_symbol.join(', '),
  }
}

function parseFiniteNumber(rawValue: string, label: string): number {
  const normalizedValue = rawValue.trim()
  if (!normalizedValue) {
    throw new Error(`${label} 값을 입력해 주세요.`)
  }

  const parsed = Number(normalizedValue)
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label}에는 올바른 숫자를 입력해 주세요.`)
  }
  if (parsed < 0) {
    throw new Error(`${label}은(는) 0 이상이어야 합니다.`)
  }
  return parsed
}

function parseSymbols(rawValue: string): string[] {
  const parsed = rawValue
    .split(',')
    .map((token) => token.trim().toUpperCase())
    .filter(Boolean)

  if (parsed.length === 0) {
    throw new Error('AI 매매 대상 심볼을 최소 1개 이상 입력해 주세요.')
  }

  return parsed
}

function parseAllocationList(rawValue: string): number[] {
  const tokens = rawValue
    .split(',')
    .map((token) => token.trim())
    .filter(Boolean)

  if (tokens.length === 0) {
    throw new Error('종목별 자산 배분 비율을 최소 1개 이상 입력해 주세요.')
  }

  return tokens.map((token, index) => parseFiniteNumber(token, `종목별 자산 배분 비율 ${index + 1}`))
}

function buildBotConfigUpdate(draft: BotConfigDraft, baseConfig: NormalizedBotConfig): BotConfig {
  const symbols = parseSymbols(draft.symbols)
  const allocationPctPerSymbol = parseAllocationList(draft.allocationPctPerSymbol)

  if (symbols.length !== allocationPctPerSymbol.length) {
    throw new Error('AI 매매 대상 심볼과 자산 배분 비율 개수는 반드시 같아야 합니다.')
  }

  return {
    symbols,
    allocation_pct_per_symbol: allocationPctPerSymbol,
    strategy: baseConfig.strategy,
    risk: baseConfig.risk,
    schedule: baseConfig.schedule,
    trade_mode: 'ai',
  }
}

function TextInput({
  label,
  value,
  onChange,
  disabled,
  placeholder,
  hint,
}: {
  label: string
  value: string
  onChange: (nextValue: string) => void
  disabled: boolean
  placeholder?: string
  hint?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-bold uppercase tracking-[0.16em] text-[#849495]">
        {label}
      </span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className={SETTINGS_FIELD_CLASS}
      />
      {hint && <p className="mt-2 text-xs text-[#849495]">{hint}</p>}
    </label>
  )
}

function BotConfigEditor({ initialConfig }: { initialConfig: NormalizedBotConfig }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<BotConfigDraft>(() => createDraft(initialConfig))
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveNotice, setSaveNotice] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaveError(null)
    setSaveNotice(null)

    try {
      const nextConfig = buildBotConfigUpdate(draft, initialConfig)
      setIsSaving(true)
      const savedConfig = await updateBotConfig(nextConfig)
      queryClient.setQueryData(BOT_CONFIG_QUERY_KEY, savedConfig)
      void queryClient.invalidateQueries({ queryKey: BOT_CONFIG_QUERY_KEY })
      setSaveNotice('AI 매매 대상 설정이 저장되었습니다.')
    } catch (error) {
      setSaveError(resolveErrorMessage(error, 'AI 매매 대상 설정을 저장하지 못했습니다.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="rounded-lg bg-[#00dbe9]/10 px-4 py-4 text-sm text-[#b9cacb]">
        <p className="font-bold text-[#7df4ff]">AI 자동매매 대상</p>
        <p className="mt-2 leading-6 text-[#dfe2eb]">
          AI가 분석하고 주문 후보로 삼을 종목과 기본 배분을 관리합니다.
        </p>
      </div>

      <section className={SETTINGS_PANEL_CLASS}>
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-[#dfe2eb]">대상 종목과 배분</h3>
          <InfoTooltip
            title="대상 종목과 배분"
            content="쉼표로 구분한 심볼 목록과 같은 순서의 배분 비율을 입력합니다. 예를 들어 KRW-BTC, KRW-ETH와 0.6, 0.4는 BTC 60%, ETH 40% 기준입니다."
          />
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <TextInput
            label="AI 매매 대상 심볼"
            value={draft.symbols}
            onChange={(nextValue) => setDraft((current) => ({ ...current, symbols: nextValue }))}
            disabled={isSaving}
            placeholder="예: KRW-BTC, KRW-ETH"
            hint="쉼표로 구분해 입력하세요."
          />
          <TextInput
            label="종목별 자산 배분 비율"
            value={draft.allocationPctPerSymbol}
            onChange={(nextValue) =>
              setDraft((current) => ({ ...current, allocationPctPerSymbol: nextValue }))
            }
            disabled={isSaving}
            placeholder="예: 0.6, 0.4"
            hint="심볼 순서와 같은 개수로 입력하세요."
          />
        </div>
      </section>

      {saveNotice && (
        <p className="rounded-lg bg-[#00dbe9]/10 px-4 py-3 text-sm font-semibold text-[#7df4ff]">
          {saveNotice}
        </p>
      )}

      {saveError && (
        <p className="rounded-lg bg-[#ffb4ab]/10 px-4 py-3 text-sm font-semibold text-[#ffb4ab]">
          {saveError}
        </p>
      )}

      <footer className="flex flex-col gap-3 border-t border-[#3b494b]/35 pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-[#849495]">
          저장한 심볼과 배분은 다음 분석 주기부터 반영됩니다.
        </p>
        <button
          type="submit"
          disabled={isSaving}
          className={SETTINGS_PRIMARY_BUTTON_CLASS}
        >
          {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
          <span>{isSaving ? '저장 중...' : 'AI 대상 설정 저장'}</span>
        </button>
      </footer>
    </form>
  )
}

function BotConfigForm() {
  const botConfigQuery = useQuery({
    queryKey: BOT_CONFIG_QUERY_KEY,
    queryFn: getBotConfig,
  })

  const normalizedConfig = normalizeBotConfig(botConfigQuery.data)
  const formKey = JSON.stringify(normalizedConfig)

  return (
    <section className={SETTINGS_CARD_CLASS}>
      <header className="border-b border-[#3b494b]/35 pb-5">
        <div className="flex items-center gap-2">
          <h2 className="text-2xl font-bold text-[#dfe2eb]">AI 매매 대상 설정</h2>
          <InfoTooltip
            title="AI 매매 대상 설정"
            content="AI 자동매매가 실제로 바라볼 종목과 기본 배분만 남긴 간소화 설정입니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[#b9cacb]">
          AI가 사용할 대상 종목과 기본 배분을 조정합니다.
        </p>
      </header>

      <div className="mt-6">
        {botConfigQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-[#b9cacb]">
            <Loader2 className="h-5 w-5 animate-spin text-[#00dbe9]" />
            현재 저장된 AI 매매 대상 설정을 불러오는 중입니다.
          </div>
        )}
        {botConfigQuery.isError && (
          <div className="rounded-lg bg-[#ffb4ab]/10 px-4 py-3 text-sm font-semibold text-[#ffb4ab]">
            AI 매매 대상 설정을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </div>
        )}
        {!botConfigQuery.isLoading && !botConfigQuery.isError && (
          <BotConfigEditor key={formKey} initialConfig={normalizedConfig} />
        )}
      </div>
    </section>
  )
}

export default BotConfigForm
