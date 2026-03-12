import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2, X } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'

import { getBotConfig, updateBotConfig, type BotConfig } from '../../services/api'

interface BotConfigFormProps {
  isOpen: boolean
  onClose: () => void
  onSaveSuccess: (message: string) => void
}

type NormalizedBotConfig = Required<BotConfig>

interface BotConfigDraft {
  symbols: string
  allocationPctPerSymbol: string
  strategy: {
    emaFast: string
    emaSlow: string
    rsi: string
    rsiMin: string
    trailingStopPct: string
  }
  risk: {
    maxCapitalPct: string
    maxDailyLossPct: string
    positionSizePct: string
    maxConcurrentPositions: string
    cooldownMinutes: string
  }
  schedule: {
    enabled: boolean
    startHour: string
    endHour: string
  }
  grid: {
    targetCoin: string
    upperBound: string
    lowerBound: string
    orderKrw: string
    sellPct: string
    cooldownSeconds: string
    tradeMode: string
  }
}

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
    trade_mode: 'grid',
  },
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
      trade_mode: config?.grid?.trade_mode ?? DEFAULT_BOT_CONFIG.grid.trade_mode,
    },
  }
}

function createDraft(config: NormalizedBotConfig): BotConfigDraft {
  return {
    symbols: config.symbols.join(', '),
    allocationPctPerSymbol: config.allocation_pct_per_symbol.join(', '),
    strategy: {
      emaFast: String(config.strategy.ema_fast),
      emaSlow: String(config.strategy.ema_slow),
      rsi: String(config.strategy.rsi),
      rsiMin: String(config.strategy.rsi_min),
      trailingStopPct: String(config.strategy.trailing_stop_pct),
    },
    risk: {
      maxCapitalPct: String(config.risk.max_capital_pct),
      maxDailyLossPct: String(config.risk.max_daily_loss_pct),
      positionSizePct: String(config.risk.position_size_pct),
      maxConcurrentPositions: String(config.risk.max_concurrent_positions),
      cooldownMinutes: String(config.risk.cooldown_minutes),
    },
    schedule: {
      enabled: config.schedule.enabled,
      startHour: config.schedule.start_hour === null ? '' : String(config.schedule.start_hour),
      endHour: config.schedule.end_hour === null ? '' : String(config.schedule.end_hour),
    },
    grid: {
      targetCoin: config.grid.target_coin,
      upperBound: String(config.grid.grid_upper_bound),
      lowerBound: String(config.grid.grid_lower_bound),
      orderKrw: String(config.grid.grid_order_krw),
      sellPct: String(config.grid.grid_sell_pct),
      cooldownSeconds: String(config.grid.grid_cooldown_seconds),
      tradeMode: config.grid.trade_mode,
    },
  }
}

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
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

function parseFiniteNumber(
  rawValue: string,
  label: string,
  options: { integer?: boolean; min?: number; max?: number; exclusiveMin?: number } = {},
): number {
  const normalizedValue = rawValue.trim()
  if (!normalizedValue) {
    throw new Error(`${label} 값을 입력해 주세요.`)
  }

  const parsed = Number(normalizedValue)
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label}은(는) 유효한 숫자여야 합니다.`)
  }
  if (options.integer && !Number.isInteger(parsed)) {
    throw new Error(`${label}은(는) 정수여야 합니다.`)
  }
  if (options.exclusiveMin !== undefined && parsed <= options.exclusiveMin) {
    throw new Error(`${label}은(는) ${options.exclusiveMin}보다 커야 합니다.`)
  }
  if (options.min !== undefined && parsed < options.min) {
    throw new Error(`${label}은(는) ${options.min} 이상이어야 합니다.`)
  }
  if (options.max !== undefined && parsed > options.max) {
    throw new Error(`${label}은(는) ${options.max} 이하여야 합니다.`)
  }

  return options.integer ? Math.trunc(parsed) : parsed
}

function parseNullableHour(rawValue: string, label: string): number | null {
  const normalizedValue = rawValue.trim()
  if (!normalizedValue) {
    return null
  }

  return parseFiniteNumber(normalizedValue, label, {
    integer: true,
    min: 0,
    max: 23,
  })
}

function parseSymbols(rawValue: string): string[] {
  const parsed = rawValue
    .split(',')
    .map((token) => token.trim().toUpperCase())
    .filter(Boolean)

  if (parsed.length === 0) {
    throw new Error('최소 1개 이상의 심볼을 입력해 주세요.')
  }

  return parsed
}

function parseAllocationList(rawValue: string): number[] {
  const tokens = rawValue
    .split(',')
    .map((token) => token.trim())
    .filter(Boolean)

  if (tokens.length === 0) {
    throw new Error('배분 비율을 최소 1개 이상 입력해 주세요.')
  }

  return tokens.map((token, index) =>
    parseFiniteNumber(token, `배분 비율 ${index + 1}`, {
      min: 0,
    }),
  )
}

function buildPayload(draft: BotConfigDraft): BotConfig {
  const symbols = parseSymbols(draft.symbols)
  const allocationPctPerSymbol = parseAllocationList(draft.allocationPctPerSymbol)

  if (symbols.length !== allocationPctPerSymbol.length) {
    throw new Error('심볼 개수와 배분 비율 개수는 반드시 같아야 합니다.')
  }

  const scheduleStartHour = parseNullableHour(draft.schedule.startHour, '시작 시간')
  const scheduleEndHour = parseNullableHour(draft.schedule.endHour, '종료 시간')

  if (
    scheduleStartHour !== null &&
    scheduleEndHour !== null &&
    scheduleStartHour >= scheduleEndHour
  ) {
    throw new Error('종료 시간은 시작 시간보다 커야 합니다.')
  }

  const targetCoin = draft.grid.targetCoin.replace(/^KRW-/i, '').trim().toUpperCase()
  if (!targetCoin) {
    throw new Error('타겟 코인을 입력해 주세요.')
  }

  const gridLowerBound = parseFiniteNumber(draft.grid.lowerBound, 'GRID_LOWER_BOUND', {
    exclusiveMin: 0,
  })
  const gridUpperBound = parseFiniteNumber(draft.grid.upperBound, 'GRID_UPPER_BOUND', {
    exclusiveMin: 0,
  })
  if (gridLowerBound >= gridUpperBound) {
    throw new Error('GRID_LOWER_BOUND는 GRID_UPPER_BOUND보다 작아야 합니다.')
  }

  const gridOrderKrw = parseFiniteNumber(draft.grid.orderKrw, 'GRID_ORDER_KRW', {
    exclusiveMin: 0,
  })
  const gridSellPct = parseFiniteNumber(draft.grid.sellPct, 'GRID_SELL_PCT', {
    exclusiveMin: 0,
    max: 100,
  })
  const gridCooldownSeconds = parseFiniteNumber(draft.grid.cooldownSeconds, 'GRID_COOLDOWN_SECONDS', {
    integer: true,
    min: 1,
  })

  const tradeMode = draft.grid.tradeMode.trim().toLowerCase() || 'grid'

  const payload: BotConfig = {
    symbols,
    allocation_pct_per_symbol: allocationPctPerSymbol,
    strategy: {
      ema_fast: parseFiniteNumber(draft.strategy.emaFast, 'EMA Fast', {
        integer: true,
        min: 1,
      }),
      ema_slow: parseFiniteNumber(draft.strategy.emaSlow, 'EMA Slow', {
        integer: true,
        min: 1,
      }),
      rsi: parseFiniteNumber(draft.strategy.rsi, 'RSI', {
        integer: true,
        min: 1,
      }),
      rsi_min: parseFiniteNumber(draft.strategy.rsiMin, 'RSI Min', {
        integer: true,
        min: 1,
      }),
      trailing_stop_pct: parseFiniteNumber(draft.strategy.trailingStopPct, 'Trailing Stop %', {
        exclusiveMin: 0,
      }),
    },
    risk: {
      max_capital_pct: parseFiniteNumber(draft.risk.maxCapitalPct, 'Max Capital %', {
        exclusiveMin: 0,
      }),
      max_daily_loss_pct: parseFiniteNumber(draft.risk.maxDailyLossPct, 'Max Daily Loss %', {
        exclusiveMin: 0,
      }),
      position_size_pct: parseFiniteNumber(draft.risk.positionSizePct, 'Position Size %', {
        exclusiveMin: 0,
      }),
      max_concurrent_positions: parseFiniteNumber(
        draft.risk.maxConcurrentPositions,
        'Max Concurrent',
        {
          integer: true,
          min: 1,
        },
      ),
      cooldown_minutes: parseFiniteNumber(draft.risk.cooldownMinutes, 'Cooldown Minutes', {
        integer: true,
        min: 1,
      }),
    },
    schedule: {
      enabled: Boolean(draft.schedule.enabled),
      start_hour: scheduleStartHour,
      end_hour: scheduleEndHour,
    },
    grid: {
      target_coin: targetCoin,
      grid_upper_bound: gridUpperBound,
      grid_lower_bound: gridLowerBound,
      grid_order_krw: gridOrderKrw,
      grid_sell_pct: gridSellPct,
      grid_cooldown_seconds: gridCooldownSeconds,
      trade_mode: tradeMode,
    },
  }

  return payload
}

function TextInput({
  label,
  value,
  onChange,
  disabled,
  type = 'text',
  placeholder,
}: {
  label: string
  value: string
  onChange: (nextValue: string) => void
  disabled: boolean
  type?: 'text' | 'number'
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-300">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder:text-gray-400 dark:focus:border-blue-400 dark:focus:ring-blue-400 dark:disabled:bg-gray-600 dark:disabled:text-gray-400"
      />
    </label>
  )
}

function BotConfigEditor({
  initialConfig,
  onClose,
  onSaveSuccess,
}: {
  initialConfig: NormalizedBotConfig
  onClose: () => void
  onSaveSuccess: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<BotConfigDraft>(() => createDraft(initialConfig))
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaveError(null)

    try {
      const payload = buildPayload(draft)
      setIsSaving(true)

      const savedConfig = await updateBotConfig(payload)

      queryClient.setQueryData(['bot-config-modal'], savedConfig)
      void queryClient.invalidateQueries({ queryKey: ['bot-config-modal'] })

      onSaveSuccess('설정이 저장되어 즉시 배포되었습니다.')
    } catch (error) {
      setSaveError(resolveErrorMessage(error, '설정을 저장하지 못했습니다.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <section className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-4 dark:border-gray-700 dark:bg-gray-700/40">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">자산 배분</h3>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <TextInput
            label="Symbols"
            value={draft.symbols}
            onChange={(nextValue) => setDraft((current) => ({ ...current, symbols: nextValue }))}
            disabled={isSaving}
            placeholder="KRW-BTC, KRW-ETH"
          />
          <TextInput
            label="Allocation"
            value={draft.allocationPctPerSymbol}
            onChange={(nextValue) =>
              setDraft((current) => ({ ...current, allocationPctPerSymbol: nextValue }))
            }
            disabled={isSaving}
            placeholder="0.5, 0.5"
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">전략</h3>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <TextInput
            label="EMA Fast"
            value={draft.strategy.emaFast}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                strategy: { ...current.strategy, emaFast: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="EMA Slow"
            value={draft.strategy.emaSlow}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                strategy: { ...current.strategy, emaSlow: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="RSI"
            value={draft.strategy.rsi}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                strategy: { ...current.strategy, rsi: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="RSI Min"
            value={draft.strategy.rsiMin}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                strategy: { ...current.strategy, rsiMin: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="Trailing Stop %"
            value={draft.strategy.trailingStopPct}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                strategy: { ...current.strategy, trailingStopPct: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">리스크</h3>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <TextInput
            label="Max Capital %"
            value={draft.risk.maxCapitalPct}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                risk: { ...current.risk, maxCapitalPct: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="Max Daily Loss %"
            value={draft.risk.maxDailyLossPct}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                risk: { ...current.risk, maxDailyLossPct: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="Position Size %"
            value={draft.risk.positionSizePct}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                risk: { ...current.risk, positionSizePct: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="Max Concurrent"
            value={draft.risk.maxConcurrentPositions}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                risk: { ...current.risk, maxConcurrentPositions: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="Cooldown Minutes"
            value={draft.risk.cooldownMinutes}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                risk: { ...current.risk, cooldownMinutes: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">스케줄</h3>
        <div className="mt-4 grid gap-4 md:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)]">
          <label className="flex items-center gap-3 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={draft.schedule.enabled}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  schedule: { ...current.schedule, enabled: event.target.checked },
                }))
              }
              disabled={isSaving}
              className="h-4 w-4 rounded border-gray-300 bg-white text-emerald-600 focus:ring-2 focus:ring-blue-500 dark:border-gray-500 dark:bg-gray-700 dark:focus:ring-blue-400 dark:disabled:bg-gray-600"
            />
            스케줄 사용
          </label>
          <TextInput
            label="Start Hour"
            value={draft.schedule.startHour}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                schedule: { ...current.schedule, startHour: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
            placeholder="0~23"
          />
          <TextInput
            label="End Hour"
            value={draft.schedule.endHour}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                schedule: { ...current.schedule, endHour: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
            placeholder="0~23"
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">그리드</h3>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <TextInput
            label="GRID_TARGET_COIN"
            value={draft.grid.targetCoin}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, targetCoin: nextValue },
              }))
            }
            disabled={isSaving}
          />
          <TextInput
            label="GRID_UPPER_BOUND"
            value={draft.grid.upperBound}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, upperBound: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="GRID_LOWER_BOUND"
            value={draft.grid.lowerBound}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, lowerBound: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="GRID_ORDER_KRW"
            value={draft.grid.orderKrw}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, orderKrw: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="GRID_SELL_PCT"
            value={draft.grid.sellPct}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, sellPct: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="GRID_COOLDOWN_SECONDS"
            value={draft.grid.cooldownSeconds}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, cooldownSeconds: nextValue },
              }))
            }
            disabled={isSaving}
            type="number"
          />
          <TextInput
            label="TRADE_MODE"
            value={draft.grid.tradeMode}
            onChange={(nextValue) =>
              setDraft((current) => ({
                ...current,
                grid: { ...current.grid, tradeMode: nextValue },
              }))
            }
            disabled={isSaving}
          />
        </div>
      </section>

      {saveError && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {saveError}
        </p>
      )}

      <footer className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4 dark:border-gray-700">
        <button
          type="button"
          onClick={onClose}
          disabled={isSaving}
          className="rounded-lg border border-gray-300 bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600"
        >
          닫기
        </button>
        <button
          type="submit"
          disabled={isSaving}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
          <span>{isSaving ? '배포 중...' : 'Save & Deploy'}</span>
        </button>
      </footer>
    </form>
  )
}

function BotConfigForm({ isOpen, onClose, onSaveSuccess }: BotConfigFormProps) {
  const botConfigQuery = useQuery({
    queryKey: ['bot-config-modal'],
    queryFn: getBotConfig,
    enabled: isOpen,
    gcTime: 0,
  })

  const normalizedConfig = normalizeBotConfig(botConfigQuery.data)
  const formKey = JSON.stringify(normalizedConfig)

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-slate-950/60" aria-hidden="true" />

      <div className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-4">
          <DialogPanel className="w-full max-w-5xl rounded-3xl bg-white shadow-2xl ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <header className="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-5 dark:border-gray-700">
              <div>
                <DialogTitle className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                  매매 파라미터 설정
                </DialogTitle>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">
                  DB에 저장된 현재 설정값을 기준으로 폼을 미리 채웁니다.
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-full bg-gray-100 p-2 text-gray-500 transition hover:bg-gray-200 hover:text-gray-800 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600 dark:hover:text-gray-100"
                aria-label="설정 모달 닫기"
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            <div className="max-h-[75vh] overflow-y-auto px-6 py-5">
              {botConfigQuery.isLoading && (
                <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-gray-500 dark:text-gray-300">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  현재 설정값을 불러오는 중입니다.
                </div>
              )}

              {botConfigQuery.isError && (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  설정값을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
                </div>
              )}

              {!botConfigQuery.isLoading && !botConfigQuery.isError && (
                <BotConfigEditor
                  key={formKey}
                  initialConfig={normalizedConfig}
                  onClose={onClose}
                  onSaveSuccess={onSaveSuccess}
                />
              )}
            </div>
          </DialogPanel>
        </div>
      </div>
    </Dialog>
  )
}

export default BotConfigForm
