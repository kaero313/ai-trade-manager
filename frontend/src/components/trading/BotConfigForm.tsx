import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'

import { getBotConfig, type BotConfig } from '../../services/api'

interface BotConfigFormProps {
  isOpen: boolean
  onClose: () => void
}

type NormalizedBotConfig = Required<BotConfig>

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

const STRATEGY_FIELDS: Array<{ key: keyof NormalizedBotConfig['strategy']; label: string }> = [
  { key: 'ema_fast', label: 'EMA Fast' },
  { key: 'ema_slow', label: 'EMA Slow' },
  { key: 'rsi', label: 'RSI' },
  { key: 'rsi_min', label: 'RSI Min' },
  { key: 'trailing_stop_pct', label: 'Trailing Stop %' },
]

const RISK_FIELDS: Array<{ key: keyof NormalizedBotConfig['risk']; label: string }> = [
  { key: 'max_capital_pct', label: 'Max Capital %' },
  { key: 'max_daily_loss_pct', label: 'Max Daily Loss %' },
  { key: 'position_size_pct', label: 'Position Size %' },
  { key: 'max_concurrent_positions', label: 'Max Concurrent' },
  { key: 'cooldown_minutes', label: 'Cooldown Minutes' },
]

const GRID_FIELDS: Array<{ key: keyof NormalizedBotConfig['grid']; label: string; type?: 'text' | 'number' }> = [
  { key: 'target_coin', label: 'Target Coin' },
  { key: 'grid_upper_bound', label: 'Upper Bound', type: 'number' },
  { key: 'grid_lower_bound', label: 'Lower Bound', type: 'number' },
  { key: 'grid_order_krw', label: 'Order KRW', type: 'number' },
  { key: 'grid_sell_pct', label: 'Sell %', type: 'number' },
  { key: 'grid_cooldown_seconds', label: 'Cooldown Seconds', type: 'number' },
  { key: 'trade_mode', label: 'Trade Mode' },
]

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

function formatNullableNumber(value: number | null): string {
  return value === null ? '' : String(value)
}

function TextInput({
  label,
  defaultValue,
  type = 'text',
  placeholder,
}: {
  label: string
  defaultValue: string
  type?: 'text' | 'number'
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <input
        type={type}
        defaultValue={defaultValue}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
      />
    </label>
  )
}

function BotConfigForm({ isOpen, onClose }: BotConfigFormProps) {
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
          <DialogPanel className="w-full max-w-5xl rounded-3xl bg-white shadow-2xl ring-1 ring-slate-200">
            <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
              <div>
                <DialogTitle className="text-xl font-semibold text-slate-900">매매 파라미터 설정</DialogTitle>
                <p className="mt-1 text-sm text-slate-500">DB에 저장된 현재 설정값을 기준으로 폼을 미리 채웁니다.</p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
                aria-label="설정 모달 닫기"
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            <div className="max-h-[75vh] overflow-y-auto px-6 py-5">
              {botConfigQuery.isLoading && (
                <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-slate-500">
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
                <div key={formKey} className="space-y-6">
                  <section className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                    <h3 className="text-sm font-semibold text-slate-900">자산 배분</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-2">
                      <TextInput label="Symbols" defaultValue={normalizedConfig.symbols.join(', ')} placeholder="KRW-BTC, KRW-ETH" />
                      <TextInput
                        label="Allocation"
                        defaultValue={normalizedConfig.allocation_pct_per_symbol.join(', ')}
                        placeholder="0.5, 0.5"
                      />
                    </div>
                  </section>

                  <section className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <h3 className="text-sm font-semibold text-slate-900">전략</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-3">
                      {STRATEGY_FIELDS.map((field) => (
                        <TextInput
                          key={field.key}
                          label={field.label}
                          defaultValue={String(normalizedConfig.strategy[field.key])}
                          type="number"
                        />
                      ))}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <h3 className="text-sm font-semibold text-slate-900">리스크</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-3">
                      {RISK_FIELDS.map((field) => (
                        <TextInput
                          key={field.key}
                          label={field.label}
                          defaultValue={String(normalizedConfig.risk[field.key])}
                          type="number"
                        />
                      ))}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <h3 className="text-sm font-semibold text-slate-900">스케줄</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)]">
                      <label className="flex items-center gap-3 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          defaultChecked={normalizedConfig.schedule.enabled}
                          className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                        />
                        스케줄 사용
                      </label>
                      <TextInput
                        label="Start Hour"
                        defaultValue={formatNullableNumber(normalizedConfig.schedule.start_hour)}
                        type="number"
                        placeholder="0~23"
                      />
                      <TextInput
                        label="End Hour"
                        defaultValue={formatNullableNumber(normalizedConfig.schedule.end_hour)}
                        type="number"
                        placeholder="0~23"
                      />
                    </div>
                  </section>

                  <section className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <h3 className="text-sm font-semibold text-slate-900">그리드</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-3">
                      {GRID_FIELDS.map((field) => (
                        <TextInput
                          key={field.key}
                          label={field.label}
                          defaultValue={String(normalizedConfig.grid[field.key])}
                          type={field.type ?? 'text'}
                        />
                      ))}
                    </div>
                  </section>
                </div>
              )}
            </div>

            <footer className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
              >
                닫기
              </button>
              <button
                type="button"
                disabled
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white opacity-60"
              >
                저장 예정
              </button>
            </footer>
          </DialogPanel>
        </div>
      </div>
    </Dialog>
  )
}

export default BotConfigForm
