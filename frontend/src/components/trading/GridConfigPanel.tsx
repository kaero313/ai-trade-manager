import { isAxiosError } from 'axios'
import { useEffect, useState } from 'react'

import type { BotConfig, GridParams } from '../../services/botService'

interface GridConfigPanelProps {
  config: BotConfig | null
  isLoading: boolean
  loadError?: string | null
  onSave: (grid: GridParams) => Promise<void>
}

const DEFAULT_GRID: GridParams = {
  target_coin: 'BTC',
  grid_upper_bound: 100000000,
  grid_lower_bound: 80000000,
  grid_order_krw: 10000,
  grid_sell_pct: 100,
  grid_cooldown_seconds: 60,
  trade_mode: 'grid',
}

function normalizeGrid(config: BotConfig | null): GridParams {
  const raw = config?.grid
  if (!raw) {
    return DEFAULT_GRID
  }

  const toNumber = (value: unknown, fallback: number): number => {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : fallback
  }

  const symbol = String(raw.target_coin ?? DEFAULT_GRID.target_coin)
    .replace(/^KRW-/i, '')
    .trim()
    .toUpperCase()

  return {
    target_coin: symbol || DEFAULT_GRID.target_coin,
    grid_upper_bound: toNumber(raw.grid_upper_bound, DEFAULT_GRID.grid_upper_bound),
    grid_lower_bound: toNumber(raw.grid_lower_bound, DEFAULT_GRID.grid_lower_bound),
    grid_order_krw: toNumber(raw.grid_order_krw, DEFAULT_GRID.grid_order_krw),
    grid_sell_pct: toNumber(raw.grid_sell_pct, DEFAULT_GRID.grid_sell_pct),
    grid_cooldown_seconds: Math.max(
      1,
      Math.trunc(toNumber(raw.grid_cooldown_seconds, DEFAULT_GRID.grid_cooldown_seconds)),
    ),
    trade_mode: String(raw.trade_mode ?? DEFAULT_GRID.trade_mode) || DEFAULT_GRID.trade_mode,
  }
}

function GridConfigPanel({ config, isLoading, loadError, onSave }: GridConfigPanelProps) {
  const [targetCoin, setTargetCoin] = useState(DEFAULT_GRID.target_coin)
  const [lowerBound, setLowerBound] = useState(String(DEFAULT_GRID.grid_lower_bound))
  const [upperBound, setUpperBound] = useState(String(DEFAULT_GRID.grid_upper_bound))
  const [orderKrw, setOrderKrw] = useState(String(DEFAULT_GRID.grid_order_krw))
  const [sellPct, setSellPct] = useState(String(DEFAULT_GRID.grid_sell_pct))
  const [cooldownSeconds, setCooldownSeconds] = useState(String(DEFAULT_GRID.grid_cooldown_seconds))
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)

  useEffect(() => {
    const grid = normalizeGrid(config)
    setTargetCoin(grid.target_coin)
    setLowerBound(String(grid.grid_lower_bound))
    setUpperBound(String(grid.grid_upper_bound))
    setOrderKrw(String(grid.grid_order_krw))
    setSellPct(String(grid.grid_sell_pct))
    setCooldownSeconds(String(grid.grid_cooldown_seconds))
  }, [config])

  const handleSave = async () => {
    setSaveError(null)
    setSaveSuccess(null)

    const normalizedCoin = targetCoin.replace(/^KRW-/i, '').trim().toUpperCase()
    const parsedLower = Number(lowerBound)
    const parsedUpper = Number(upperBound)
    const parsedOrder = Number(orderKrw)
    const parsedSellPct = Number(sellPct)
    const parsedCooldown = Number(cooldownSeconds)

    if (!normalizedCoin) {
      setSaveError('타겟 코인을 입력해 주세요.')
      return
    }
    if (!Number.isFinite(parsedLower) || !Number.isFinite(parsedUpper) || parsedLower >= parsedUpper) {
      setSaveError('하단가는 상단가보다 작아야 합니다.')
      return
    }
    if (!Number.isFinite(parsedOrder) || parsedOrder <= 0) {
      setSaveError('1회 매수 금액은 0보다 커야 합니다.')
      return
    }
    if (!Number.isFinite(parsedSellPct) || parsedSellPct < 0 || parsedSellPct > 100) {
      setSaveError('매도 비율은 0~100 범위여야 합니다.')
      return
    }
    if (!Number.isFinite(parsedCooldown) || parsedCooldown < 1) {
      setSaveError('쿨타임은 1초 이상이어야 합니다.')
      return
    }

    const nextGrid: GridParams = {
      target_coin: normalizedCoin,
      grid_lower_bound: parsedLower,
      grid_upper_bound: parsedUpper,
      grid_order_krw: parsedOrder,
      grid_sell_pct: parsedSellPct,
      grid_cooldown_seconds: Math.trunc(parsedCooldown),
      trade_mode: 'grid',
    }

    try {
      setIsSaving(true)
      await onSave(nextGrid)
      setSaveSuccess('그리드 봇 설정이 저장되었습니다.')
    } catch (error) {
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string' && detail.length > 0) {
          setSaveError(detail)
        } else {
          setSaveError(error.message)
        }
      } else {
        setSaveError('설정을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      }
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">🤖 그리드 봇 설정 (Grid Trading Configuration)</h2>
        <p className="mt-1 text-sm text-slate-500">거래 코인과 주문 범위를 직접 제어할 수 있습니다.</p>
      </header>

      {loadError && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          {loadError}
        </p>
      )}

      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
            타겟 코인 (Target Coin)
          </label>
          <input
            type="text"
            value={targetCoin}
            onChange={(event) => setTargetCoin(event.target.value)}
            placeholder="BTC"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            disabled={isLoading || isSaving}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              매수 하단가 (Lower Bound)
            </label>
            <input
              type="number"
              value={lowerBound}
              onChange={(event) => setLowerBound(event.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              disabled={isLoading || isSaving}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              매도 상단가 (Upper Bound)
            </label>
            <input
              type="number"
              value={upperBound}
              onChange={(event) => setUpperBound(event.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              disabled={isLoading || isSaving}
            />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              1회 매수 금액 (Order KRW)
            </label>
            <input
              type="number"
              value={orderKrw}
              onChange={(event) => setOrderKrw(event.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              disabled={isLoading || isSaving}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              매도 비율 (Sell %)
            </label>
            <input
              type="number"
              min={0}
              max={100}
              value={sellPct}
              onChange={(event) => setSellPct(event.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              disabled={isLoading || isSaving}
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
            쿨타임 (Cooldown seconds)
          </label>
          <input
            type="number"
            min={1}
            value={cooldownSeconds}
            onChange={(event) => setCooldownSeconds(event.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            disabled={isLoading || isSaving}
          />
        </div>
      </div>

      <button
        type="button"
        onClick={handleSave}
        disabled={isLoading || isSaving}
        className="mt-5 w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {isSaving ? '저장 중...' : '설정 저장'}
      </button>

      {saveSuccess && (
        <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          {saveSuccess}
        </p>
      )}
      {saveError && (
        <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {saveError}
        </p>
      )}
    </aside>
  )
}

export default GridConfigPanel
