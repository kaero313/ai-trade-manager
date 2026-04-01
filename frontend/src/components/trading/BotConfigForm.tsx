import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'

import InfoTooltip from '../common/InfoTooltip'
import { getBotConfig, updateBotConfig, type BotConfig } from '../../services/api'

type BotConfigInput = BotConfig & { trade_mode?: string }
type StrategyConfig = NonNullable<BotConfig['strategy']>
type RiskConfig = NonNullable<BotConfig['risk']>
type ScheduleConfig = NonNullable<BotConfig['schedule']>
type GridConfig = NonNullable<BotConfig['grid']>
type NormalizedGridConfig = Omit<GridConfig, 'trade_mode'>

interface NormalizedBotConfig {
  symbols: string[]
  allocation_pct_per_symbol: number[]
  strategy: StrategyConfig
  risk: RiskConfig
  schedule: ScheduleConfig
  grid: NormalizedGridConfig
  trade_mode: string
}

interface BotConfigDraft {
  symbols: string
  allocationPctPerSymbol: string
  tradeMode: string
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
  }
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
  trade_mode: 'ai',
  grid: {
    target_coin: 'BTC',
    grid_upper_bound: 100000000,
    grid_lower_bound: 80000000,
    grid_order_krw: 10000,
    grid_sell_pct: 100,
    grid_cooldown_seconds: 60,
  },
}

function normalizeBotConfig(config: BotConfigInput | undefined): NormalizedBotConfig {
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
    trade_mode:
      config?.trade_mode ?? config?.grid?.trade_mode ?? DEFAULT_BOT_CONFIG.trade_mode,
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
    tradeMode: config.trade_mode,
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
    throw new Error(`${label}에는 올바른 숫자를 입력해 주세요.`)
  }
  if (options.integer && !Number.isInteger(parsed)) {
    throw new Error(`${label}에는 정수만 입력할 수 있습니다.`)
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
    throw new Error('종목별 자산 배분 비율을 최소 1개 이상 입력해 주세요.')
  }

  return tokens.map((token, index) =>
    parseFiniteNumber(token, `종목별 자산 배분 비율 ${index + 1}`, { min: 0 }),
  )
}

function buildPayload(draft: BotConfigDraft): BotConfig {
  const symbols = parseSymbols(draft.symbols)
  const allocationPctPerSymbol = parseAllocationList(draft.allocationPctPerSymbol)

  if (symbols.length !== allocationPctPerSymbol.length) {
    throw new Error('매매 대상 심볼과 자산 배분 비율 개수는 반드시 같아야 합니다.')
  }

  const scheduleStartHour = parseNullableHour(draft.schedule.startHour, '거래 시작 시간')
  const scheduleEndHour = parseNullableHour(draft.schedule.endHour, '거래 종료 시간')
  if (
    scheduleStartHour !== null &&
    scheduleEndHour !== null &&
    scheduleStartHour >= scheduleEndHour
  ) {
    throw new Error('거래 종료 시간은 거래 시작 시간보다 커야 합니다.')
  }

  const targetCoin = draft.grid.targetCoin.replace(/^KRW-/i, '').trim().toUpperCase()
  if (!targetCoin) {
    throw new Error('거래 대상 코인을 입력해 주세요.')
  }

  const gridLowerBound = parseFiniteNumber(draft.grid.lowerBound, '그리드 매매 하단 가격', {
    exclusiveMin: 0,
  })
  const gridUpperBound = parseFiniteNumber(draft.grid.upperBound, '그리드 매매 상단 가격', {
    exclusiveMin: 0,
  })
  if (gridLowerBound >= gridUpperBound) {
    throw new Error('그리드 매매 하단 가격은 상단 가격보다 작아야 합니다.')
  }

  return {
    symbols,
    allocation_pct_per_symbol: allocationPctPerSymbol,
    strategy: {
      ema_fast: parseFiniteNumber(draft.strategy.emaFast, '빠른 EMA 기간', { integer: true, min: 1 }),
      ema_slow: parseFiniteNumber(draft.strategy.emaSlow, '느린 EMA 기간', { integer: true, min: 1 }),
      rsi: parseFiniteNumber(draft.strategy.rsi, 'RSI 계산 기간', { integer: true, min: 1 }),
      rsi_min: parseFiniteNumber(draft.strategy.rsiMin, 'RSI 최소 진입 기준', { integer: true, min: 1 }),
      trailing_stop_pct: parseFiniteNumber(draft.strategy.trailingStopPct, '추적 손절 비율', {
        exclusiveMin: 0,
      }),
    },
    risk: {
      max_capital_pct: parseFiniteNumber(draft.risk.maxCapitalPct, '최대 총 투자 비중', { exclusiveMin: 0 }),
      max_daily_loss_pct: parseFiniteNumber(draft.risk.maxDailyLossPct, '일일 최대 손실 허용치', {
        exclusiveMin: 0,
      }),
      position_size_pct: parseFiniteNumber(draft.risk.positionSizePct, '1회 진입 비중', {
        exclusiveMin: 0,
      }),
      max_concurrent_positions: parseFiniteNumber(
        draft.risk.maxConcurrentPositions,
        '최대 동시 보유 종목 수',
        { integer: true, min: 1 },
      ),
      cooldown_minutes: parseFiniteNumber(draft.risk.cooldownMinutes, '종목 재진입 대기 시간', {
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
      grid_order_krw: parseFiniteNumber(draft.grid.orderKrw, '1회 주문당 투자 금액', {
        exclusiveMin: 0,
      }),
      grid_sell_pct: parseFiniteNumber(draft.grid.sellPct, '목표 익절 수익률', {
        exclusiveMin: 0,
        max: 100,
      }),
      grid_cooldown_seconds: parseFiniteNumber(draft.grid.cooldownSeconds, '재주문 대기 시간', {
        integer: true,
        min: 1,
      }),
      trade_mode: draft.tradeMode.trim().toLowerCase() || 'ai',
    },
  }
}

function TextInput({
  label,
  value,
  onChange,
  disabled,
  type = 'text',
  placeholder,
  hint,
}: {
  label: string
  value: string
  onChange: (nextValue: string) => void
  disabled: boolean
  type?: 'text' | 'number'
  placeholder?: string
  hint?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
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
      {hint && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{hint}</p>}
    </label>
  )
}

function SectionHeading({ title, tooltip }: { title: string; tooltip: string }) {
  return (
    <div className="flex items-center gap-2">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
      <InfoTooltip title={title} content={tooltip} />
    </div>
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
      const payload = buildPayload(draft)
      setIsSaving(true)
      const savedConfig = await updateBotConfig(payload)
      queryClient.setQueryData(BOT_CONFIG_QUERY_KEY, savedConfig)
      void queryClient.invalidateQueries({ queryKey: BOT_CONFIG_QUERY_KEY })
      setSaveNotice('봇 파라미터가 저장되었고 즉시 반영되었습니다.')
    } catch (error) {
      setSaveError(resolveErrorMessage(error, '봇 파라미터를 저장하지 못했습니다.'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-4 text-sm text-sky-900 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-100">
        <p className="font-semibold">전략 설정 안내</p>
        <p className="mt-2 leading-6">
          기존 대시보드 팝업을 넓은 설정 화면으로 옮겨 온 통합 편집 구역입니다. 저장 즉시 백엔드
          전략 파라미터가 갱신되므로, 툴팁과 힌트를 확인한 뒤 수정하는 편이 안전합니다.
        </p>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-4 dark:border-gray-700 dark:bg-gray-700/40">
        <SectionHeading
          title="자산 배분"
          tooltip="심볼 목록과 종목별 배분 비율을 한 번에 관리하는 구간입니다. 심볼 수와 배분 비율 개수는 반드시 같아야 합니다."
        />
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <TextInput
            label="매매 대상 심볼 목록"
            value={draft.symbols}
            onChange={(nextValue) => setDraft((current) => ({ ...current, symbols: nextValue }))}
            disabled={isSaving}
            placeholder="예: KRW-BTC, KRW-ETH"
            hint="쉼표로 구분해 입력하세요. 예: KRW-BTC, KRW-ETH"
          />
          <TextInput
            label="종목별 자산 배분 비율"
            value={draft.allocationPctPerSymbol}
            onChange={(nextValue) => setDraft((current) => ({ ...current, allocationPctPerSymbol: nextValue }))}
            disabled={isSaving}
            placeholder="예: 0.5, 0.5"
            hint="심볼 순서와 같은 개수로 입력하세요. 예: 0.5, 0.5"
          />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <SectionHeading
          title="전략 설정"
          tooltip="EMA, RSI, 추적 손절로 진입과 청산 논리를 정하는 구간입니다. 값이 작을수록 빠르지만 노이즈가 커질 수 있습니다."
        />
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <TextInput label="빠른 EMA 기간" value={draft.strategy.emaFast} onChange={(nextValue) => setDraft((current) => ({ ...current, strategy: { ...current.strategy, emaFast: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 12" hint="단기 추세를 빠르게 반영합니다." />
          <TextInput label="느린 EMA 기간" value={draft.strategy.emaSlow} onChange={(nextValue) => setDraft((current) => ({ ...current, strategy: { ...current.strategy, emaSlow: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 26" hint="중기 추세를 보는 기준선입니다." />
          <TextInput label="RSI 계산 기간" value={draft.strategy.rsi} onChange={(nextValue) => setDraft((current) => ({ ...current, strategy: { ...current.strategy, rsi: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 14" hint="RSI를 계산할 캔들 수입니다." />
          <TextInput label="RSI 최소 진입 기준" value={draft.strategy.rsiMin} onChange={(nextValue) => setDraft((current) => ({ ...current, strategy: { ...current.strategy, rsiMin: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 50" hint="이 값 이상일 때만 매수 진입을 허용합니다." />
          <TextInput label="추적 손절 비율" value={draft.strategy.trailingStopPct} onChange={(nextValue) => setDraft((current) => ({ ...current, strategy: { ...current.strategy, trailingStopPct: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 0.03" hint="예: 0.03 은 3%를 의미합니다." />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <SectionHeading
          title="리스크 관리"
          tooltip="총 투자 한도, 일일 손실 허용치, 포지션 분산 정도를 조절하는 구간입니다. 실계좌 보호를 위해 가장 중요합니다."
        />
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <TextInput label="최대 총 투자 비중" value={draft.risk.maxCapitalPct} onChange={(nextValue) => setDraft((current) => ({ ...current, risk: { ...current.risk, maxCapitalPct: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 0.1" hint="예: 0.1 은 전체 자산의 10%를 의미합니다." />
          <TextInput label="일일 최대 손실 허용치" value={draft.risk.maxDailyLossPct} onChange={(nextValue) => setDraft((current) => ({ ...current, risk: { ...current.risk, maxDailyLossPct: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 0.05" hint="예: 0.05 는 하루 손실 허용치를 5%로 둡니다." />
          <TextInput label="1회 진입 비중" value={draft.risk.positionSizePct} onChange={(nextValue) => setDraft((current) => ({ ...current, risk: { ...current.risk, positionSizePct: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 0.2" hint="예: 0.2 는 한 번 진입 시 20%를 사용합니다." />
          <TextInput label="최대 동시 보유 종목 수" value={draft.risk.maxConcurrentPositions} onChange={(nextValue) => setDraft((current) => ({ ...current, risk: { ...current.risk, maxConcurrentPositions: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 3" hint="동시에 보유할 수 있는 종목 수 상한입니다." />
          <TextInput label="종목 재진입 대기 시간 (분)" value={draft.risk.cooldownMinutes} onChange={(nextValue) => setDraft((current) => ({ ...current, risk: { ...current.risk, cooldownMinutes: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 60" hint="같은 종목을 다시 진입하기 전 기다릴 시간입니다." />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <SectionHeading
          title="자동 매매 시간"
          tooltip="봇이 실제 주문을 낼 수 있는 시간대를 제한합니다. 체크를 끄면 시간 제한 없이 계속 동작합니다."
        />
        <div className="mt-4 grid gap-4 md:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]">
          <div>
            <label className="flex items-center gap-3 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200">
              <input
                type="checkbox"
                checked={draft.schedule.enabled}
                onChange={(event) => setDraft((current) => ({ ...current, schedule: { ...current.schedule, enabled: event.target.checked } }))}
                disabled={isSaving}
                className="h-4 w-4 rounded border-gray-300 bg-white text-emerald-600 focus:ring-2 focus:ring-blue-500 dark:border-gray-500 dark:bg-gray-700 dark:focus:ring-blue-400 dark:disabled:bg-gray-600"
              />
              시간 조건 사용
            </label>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">체크를 켜면 지정한 시간대에서만 자동 매매가 동작합니다.</p>
          </div>
          <TextInput label="거래 시작 시간 (0~23)" value={draft.schedule.startHour} onChange={(nextValue) => setDraft((current) => ({ ...current, schedule: { ...current.schedule, startHour: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 9" hint="비워 두면 시작 시간 제한 없이 동작합니다." />
          <TextInput label="거래 종료 시간 (0~23)" value={draft.schedule.endHour} onChange={(nextValue) => setDraft((current) => ({ ...current, schedule: { ...current.schedule, endHour: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 23" hint="비워 두면 종료 시간 제한 없이 동작합니다." />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white px-4 py-4 dark:border-gray-700 dark:bg-gray-800">
        <SectionHeading
          title="그리드 매매"
          tooltip="가격 밴드 안에서 분할 매수·분할 매도를 반복하는 전략 구간입니다. 상단/하단 가격과 주문 금액이 핵심입니다."
        />
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <TextInput label="거래 대상 코인" value={draft.grid.targetCoin} onChange={(nextValue) => setDraft((current) => ({ ...current, grid: { ...current.grid, targetCoin: nextValue } }))} disabled={isSaving} placeholder="예: BTC" hint="KRW- 접두사는 생략하고 코인 이름만 입력해도 됩니다." />
          <TextInput label="그리드 매매 상단 가격 (Upper Bound)" value={draft.grid.upperBound} onChange={(nextValue) => setDraft((current) => ({ ...current, grid: { ...current.grid, upperBound: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 110000000" hint="예: 110,000,000" />
          <TextInput label="그리드 매매 하단 가격 (Lower Bound)" value={draft.grid.lowerBound} onChange={(nextValue) => setDraft((current) => ({ ...current, grid: { ...current.grid, lowerBound: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 95000000" hint="예: 95,000,000" />
          <TextInput label="1회 주문당 투자 금액 (KRW)" value={draft.grid.orderKrw} onChange={(nextValue) => setDraft((current) => ({ ...current, grid: { ...current.grid, orderKrw: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 10000" hint="예: 10,000" />
          <TextInput label="목표 익절 수익률 (%)" value={draft.grid.sellPct} onChange={(nextValue) => setDraft((current) => ({ ...current, grid: { ...current.grid, sellPct: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 1.5" hint="예: 1.5" />
          <TextInput label="재주문 대기 시간 (Cool-down 초)" value={draft.grid.cooldownSeconds} onChange={(nextValue) => setDraft((current) => ({ ...current, grid: { ...current.grid, cooldownSeconds: nextValue } }))} disabled={isSaving} type="number" placeholder="예: 60" hint="예: 60" />
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-gray-600 dark:text-gray-300">
              매매 모드
            </span>
            <select
              value={draft.tradeMode}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  tradeMode: event.target.value,
                }))
              }
              disabled={isSaving}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400 dark:disabled:bg-gray-600 dark:disabled:text-gray-400"
            >
              <option value="grid">그리드 매매 (grid)</option>
              <option value="ai">AI 자율 주행 (ai)</option>
            </select>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              일반적으로 grid 또는 ai 값을 사용합니다.
            </p>
          </label>
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

      <footer className="flex items-center justify-between gap-3 border-t border-gray-200 pt-4 dark:border-gray-700">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          저장 즉시 백엔드 전략 파라미터가 갱신됩니다. 실계좌 운용 중이라면 리스크 한도와 주문 금액을 먼저 확인하세요.
        </p>
        <button
          type="submit"
          disabled={isSaving}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
          <span>{isSaving ? '저장 중...' : '설정 저장하기'}</span>
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
          Trading Bot Parameters
        </p>
        <div className="mt-3 flex items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">트레이딩 봇 파라미터</h2>
          <InfoTooltip
            title="트레이딩 봇 파라미터"
            content="대시보드 팝업을 없애고 넓은 설정 화면으로 옮긴 편집 구역입니다. 전략과 리스크를 한 번에 검토하면서 저장할 수 있게 구성했습니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          전략, 리스크, 운용 시간, 그리드 매매 설정을 한 번에 조정하는 통합 화면입니다.
          각 섹션 제목 옆의 정보 아이콘에 마우스를 올리면 상세한 한국어 설명을 볼 수 있습니다.
        </p>
      </header>

      <div className="mt-6">
        {botConfigQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-gray-500 dark:text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin" />
            현재 저장된 봇 파라미터를 불러오는 중입니다.
          </div>
        )}
        {botConfigQuery.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            봇 파라미터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
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
