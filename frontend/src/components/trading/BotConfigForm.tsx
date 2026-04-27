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
type GridConfig = NonNullable<BotConfig['grid']>

interface NormalizedBotConfig {
  symbols: string[]
  allocation_pct_per_symbol: number[]
  strategy: StrategyConfig
  risk: RiskConfig
  schedule: ScheduleConfig
  grid: GridConfig
}

interface BotConfigDraft {
  symbols: string
  allocationPctPerSymbol: string
}

const BOT_CONFIG_QUERY_KEY = ['bot-config'] as const

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
  grid: {
    target_coin: 'BTC',
    grid_upper_bound: 100000000,
    grid_lower_bound: 80000000,
    grid_order_krw: 10000,
    grid_sell_pct: 100,
    grid_cooldown_seconds: 60,
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
    grid: {
      target_coin: config?.grid?.target_coin ?? DEFAULT_BOT_CONFIG.grid.target_coin,
      grid_upper_bound: config?.grid?.grid_upper_bound ?? DEFAULT_BOT_CONFIG.grid.grid_upper_bound,
      grid_lower_bound: config?.grid?.grid_lower_bound ?? DEFAULT_BOT_CONFIG.grid.grid_lower_bound,
      grid_order_krw: config?.grid?.grid_order_krw ?? DEFAULT_BOT_CONFIG.grid.grid_order_krw,
      grid_sell_pct: config?.grid?.grid_sell_pct ?? DEFAULT_BOT_CONFIG.grid.grid_sell_pct,
      grid_cooldown_seconds:
        config?.grid?.grid_cooldown_seconds ?? DEFAULT_BOT_CONFIG.grid.grid_cooldown_seconds,
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

function buildPayload(draft: BotConfigDraft, baseConfig: NormalizedBotConfig): BotConfig {
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
    grid: baseConfig.grid,
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
      <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
        {label}
      </span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder:text-gray-400 dark:focus:border-blue-400 dark:focus:ring-blue-400 dark:disabled:bg-gray-600 dark:disabled:text-gray-400"
      />
      {hint && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{hint}</p>}
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
      const payload = buildPayload(draft, initialConfig)
      setIsSaving(true)
      const savedConfig = await updateBotConfig(payload)
      queryClient.setQueryData(BOT_CONFIG_QUERY_KEY, savedConfig)
      void queryClient.invalidateQueries({ queryKey: BOT_CONFIG_QUERY_KEY })
      setSaveNotice('AI 매매 대상 설정이 저장되었고 봇 모드는 AI로 고정되었습니다.')
    } catch (error) {
      setSaveError(resolveErrorMessage(error, 'AI 매매 대상 설정을 저장하지 못했습니다.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-4 text-sm text-sky-900 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-100">
        <p className="font-semibold">AI 자동매매 대상</p>
        <p className="mt-2 leading-6">
          이 화면에서는 AI가 분석하고 주문 후보로 삼을 종목과 기본 배분만 관리합니다. 과거 그리드 전략과
          기술지표 세부값은 화면에서 제외했고, 저장 시 봇 실행 모드는 항상 AI로 고정됩니다.
        </p>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-4 dark:border-gray-700 dark:bg-gray-700/40">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">대상 종목과 배분</h3>
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
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200">
          {saveNotice}
        </p>
      )}

      {saveError && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
          {saveError}
        </p>
      )}

      <footer className="flex flex-col gap-3 border-t border-gray-200 pt-4 dark:border-gray-700 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          저장 payload에는 `trade_mode: ai`가 함께 포함됩니다.
        </p>
        <button
          type="submit"
          disabled={isSaving}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
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
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="border-b border-gray-200 pb-5 dark:border-gray-700">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-300">
          AI Trading Scope
        </p>
        <div className="mt-3 flex items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">AI 매매 대상 설정</h2>
          <InfoTooltip
            title="AI 매매 대상 설정"
            content="AI 자동매매가 실제로 바라볼 종목과 기본 배분만 남긴 간소화 설정입니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          그리드 방식과 레거시 기술지표 입력은 제거하고, AI 운용에 직접 필요한 대상 종목만 조정합니다.
        </p>
      </header>

      <div className="mt-6">
        {botConfigQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-gray-500 dark:text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin" />
            현재 저장된 AI 매매 대상 설정을 불러오는 중입니다.
          </div>
        )}
        {botConfigQuery.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
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
