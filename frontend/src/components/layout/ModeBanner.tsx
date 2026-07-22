import { AlertTriangle, ShieldAlert, ShieldCheck } from 'lucide-react'

import type { LiveOrderMode, TradingMode } from '../../services/api'

export type RuntimeStatus = 'RUNNING' | 'STOPPED' | 'UNAVAILABLE'

export interface ModeBannerProps {
  runtimeStatus: RuntimeStatus
  tradingMode: TradingMode | null
  orderGate: LiveOrderMode | null
  rolloutEnabled: boolean | null
  desktopNavigationCollapsed?: boolean
}

interface ReadOnlyStatusProps {
  label: string
  value: string
  tone: 'neutral' | 'brand' | 'warning' | 'danger' | 'success'
}

const STATUS_TONE_CLASS: Record<ReadOnlyStatusProps['tone'], string> = {
  neutral: 'border-border-subtle bg-surface-high text-content-secondary',
  brand: 'border-brand/25 bg-brand/10 text-brand-bright',
  warning: 'border-warning/25 bg-warning/10 text-warning',
  danger: 'border-status-danger/25 bg-status-danger/10 text-status-danger',
  success: 'border-status-success/25 bg-status-success/10 text-status-success',
}

function ReadOnlyStatus({ label, value, tone }: ReadOnlyStatusProps) {
  return (
    <span
      className={`inline-flex min-h-7 items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-bold ${STATUS_TONE_CLASS[tone]}`}
    >
      <span className="font-semibold opacity-75">{label}</span>
      <span>{value}</span>
    </span>
  )
}

function resolveRuntimeTone(status: RuntimeStatus): ReadOnlyStatusProps['tone'] {
  if (status === 'RUNNING') {
    return 'success'
  }
  if (status === 'STOPPED') {
    return 'neutral'
  }
  return 'danger'
}

function resolveGateTone(mode: LiveOrderMode | null): ReadOnlyStatusProps['tone'] {
  if (mode === 'ARMED') {
    return 'danger'
  }
  if (mode === 'EXIT_ONLY') {
    return 'warning'
  }
  if (mode === 'BLOCK_ALL') {
    return 'brand'
  }
  return 'danger'
}

function ModeBanner({
  runtimeStatus,
  tradingMode,
  orderGate,
  rolloutEnabled,
  desktopNavigationCollapsed = false,
}: ModeBannerProps) {
  const modeUnavailable = tradingMode === null
  const isLive = tradingMode === 'live'
  const Icon = modeUnavailable ? ShieldAlert : isLive ? AlertTriangle : ShieldCheck
  const modeTitle = modeUnavailable
    ? '거래 모드 확인 불가'
    : isLive
      ? 'LIVE 실거래 모드'
      : 'PAPER 모의투자 모드'
  const modeDescription = modeUnavailable
    ? '조회 실패나 상태 불일치를 LIVE로 간주하지 않으며 실주문은 fail-closed로 차단됩니다.'
    : isLive
      ? '런타임, Rollout, Order Gate 조건에 따라 실제 Upbit 주문이 제출될 수 있습니다.'
      : '주문은 실제 자산에 영향을 주지 않습니다.'
  const modeTextClassName = modeUnavailable || isLive ? 'text-status-danger' : 'text-warning'
  const bannerClassName = modeUnavailable
    ? 'border-status-danger/30 bg-status-danger/8'
    : isLive
      ? 'border-status-danger/30 bg-status-danger/8'
      : 'border-warning/30 bg-warning/8'

  return (
    <section
      aria-label="거래 안전 상태"
      aria-live="polite"
      className={`sticky top-0 z-30 border-b backdrop-blur-xl ${bannerClassName}`}
    >
      <div
        className={`mx-auto flex w-full flex-col gap-2 px-4 py-2 transition-[max-width] duration-200 motion-reduce:transition-none sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8 ${
          desktopNavigationCollapsed ? 'max-w-[1600px]' : 'max-w-[1440px]'
        }`}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <Icon
            className={`h-4 w-4 shrink-0 ${modeTextClassName}`}
            aria-hidden="true"
          />
          <p className={`min-w-0 truncate text-xs font-semibold sm:text-sm ${modeTextClassName}`}>
            <span className="font-extrabold">{modeTitle}</span>
            <span className="sr-only"> · {modeDescription}</span>
            <span aria-hidden="true" className="hidden xl:inline">
              {' '}
              · {modeDescription}
            </span>
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5" aria-label="조회 전용 운영 상태">
          <ReadOnlyStatus
            label="Runtime"
            value={runtimeStatus === 'UNAVAILABLE' ? '조회 불가' : runtimeStatus}
            tone={resolveRuntimeTone(runtimeStatus)}
          />
          <ReadOnlyStatus
            label="Order Gate"
            value={orderGate ?? 'UNAVAILABLE'}
            tone={resolveGateTone(orderGate)}
          />
          <ReadOnlyStatus
            label="Rollout"
            value={rolloutEnabled === null ? 'UNAVAILABLE' : rolloutEnabled ? 'ON' : 'OFF'}
            tone={rolloutEnabled === null ? 'danger' : rolloutEnabled ? 'warning' : 'neutral'}
          />
        </div>
      </div>
    </section>
  )
}

export default ModeBanner
