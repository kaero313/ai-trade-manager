import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

import { useAIPerformance } from '../../hooks/useAIPerformance'
import { useSystemConfigs } from '../../hooks/useSystemConfigs'

function formatKrw(value: number): string {
  const rounded = Math.round(Math.abs(value))
  return `₩${new Intl.NumberFormat('ko-KR').format(rounded)}`
}

function formatSignedKrw(value: number): string {
  if (value > 0) {
    return `+${formatKrw(value)}`
  }
  if (value < 0) {
    return `-${formatKrw(value)}`
  }
  return formatKrw(value)
}

function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`
}

function parseBooleanConfig(value: string | undefined): boolean {
  return ['true', '1', 'yes', 'on'].includes(String(value ?? '').trim().toLowerCase())
}

function resolveValueClassName(tone: 'primary' | 'success' | 'warning' | 'danger' | 'muted'): string {
  if (tone === 'success') {
    return 'text-[#77e2a8]'
  }
  if (tone === 'warning') {
    return 'text-[#ffe179]'
  }
  if (tone === 'danger') {
    return 'text-[#ffb4ab]'
  }
  if (tone === 'muted') {
    return 'text-[#849495]'
  }
  return 'text-[#00dbe9]'
}

function resolvePnlTone(value: number): 'success' | 'danger' | 'muted' {
  if (value > 0) {
    return 'success'
  }
  if (value < 0) {
    return 'danger'
  }
  return 'muted'
}

function resolveDecisionTone(decision: string): 'primary' | 'warning' | 'danger' | 'muted' {
  const normalized = decision.toUpperCase()
  if (normalized === 'BUY') {
    return 'primary'
  }
  if (normalized === 'SELL') {
    return 'danger'
  }
  if (normalized === 'HOLD') {
    return 'warning'
  }
  return 'muted'
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }
  return Math.max(0, Math.min(100, value))
}

function MetricTile({
  label,
  value,
  tone = 'primary',
  size = 'lg',
}: {
  label: string
  value: string
  tone?: 'primary' | 'success' | 'warning' | 'danger' | 'muted'
  size?: 'lg' | 'xl'
}) {
  return (
    <article className="rounded-lg bg-[#0a0e14]/72 p-3">
      <p className="text-xs text-[#849495]">{label}</p>
      <p
        className={`mt-2 break-words font-mono font-semibold ${resolveValueClassName(tone)} ${
          size === 'xl' ? 'text-2xl' : 'text-lg'
        }`}
      >
        {value}
      </p>
    </article>
  )
}

function PerformanceShell({
  badge,
  badgeTone = 'primary',
  children,
}: {
  badge: string
  badgeTone?: 'primary' | 'success' | 'warning' | 'danger'
  children: ReactNode
}) {
  return (
    <section className="quantum-card flex min-h-0 flex-col overflow-hidden rounded-xl p-5">
      <header className="mb-4 flex items-center justify-between gap-3">
        <h2 className="min-w-0 text-lg font-bold text-[#dfe2eb]">AI 성과 요약</h2>
        <span
          className={`shrink-0 rounded px-2 py-1 text-xs font-semibold ${resolveValueClassName(badgeTone)} ${
            badgeTone === 'success'
              ? 'bg-[#77e2a8]/10'
              : badgeTone === 'warning'
                ? 'bg-[#ffe179]/10'
                : badgeTone === 'danger'
                  ? 'bg-[#ffb4ab]/10'
                  : 'bg-[#00dbe9]/10'
          }`}
        >
          {badge}
        </span>
      </header>
      {children}
    </section>
  )
}

function AiPerformanceWidget() {
  const performanceQuery = useAIPerformance()
  const systemConfigsQuery = useSystemConfigs()
  const performance = performanceQuery.data
  const hasData = performance !== undefined

  if (performanceQuery.isLoading && !hasData) {
    return (
      <PerformanceShell badge="LOADING">
        <div className="flex h-44 items-center justify-center gap-3 rounded-lg bg-[#0a0e14]/72 px-5 py-8 text-sm text-[#b9cacb]">
          <Loader2 className="h-5 w-5 animate-spin text-[#00dbe9]" />
          AI 성과 데이터를 불러오는 중입니다.
        </div>
      </PerformanceShell>
    )
  }

  if (performanceQuery.isError && !hasData) {
    return (
      <PerformanceShell badge="DEGRADED" badgeTone="danger">
        <div className="rounded-lg bg-[#0a0e14]/72 px-4 py-3 text-sm font-semibold leading-6 text-[#ffb4ab]">
          AI 매매 성과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
        </div>
      </PerformanceShell>
    )
  }

  const summary = performance ?? {
    total_trades: 0,
    winning_trades: 0,
    losing_trades: 0,
    win_rate: 0,
    accuracy_rate: 0,
    total_realized_pnl_krw: 0,
    avg_confidence: 0,
    recent_trades: [],
  }
  const latestTrade = summary.recent_trades[0] ?? null
  const latestDecision = latestTrade?.decision ?? '대기'
  const statusBadge = performanceQuery.isError ? 'CACHED' : 'TRACKING'
  const statusTone = performanceQuery.isError ? 'warning' : 'success'
  const accuracy = clampPercent(summary.accuracy_rate)
  const liveBuyConfig = systemConfigsQuery.data?.find((item) => item.config_key === 'live_buy_enabled')
  const liveBuyEnabled = parseBooleanConfig(liveBuyConfig?.config_value)
  const autoBuyLabel = systemConfigsQuery.isLoading ? 'CHECKING' : liveBuyEnabled ? 'ENABLED' : 'BLOCKED'
  const autoBuyTone = systemConfigsQuery.isLoading ? 'muted' : liveBuyEnabled ? 'success' : 'muted'

  return (
    <PerformanceShell badge={statusBadge} badgeTone={statusTone}>
      <div className="grid grid-cols-2 gap-3">
        <MetricTile
          label="AI 적중률"
          value={formatPercentage(accuracy)}
          tone={accuracy > 0 ? 'primary' : 'muted'}
          size="xl"
        />
        <MetricTile
          label="Paper PnL"
          value={formatSignedKrw(summary.total_realized_pnl_krw)}
          tone={resolvePnlTone(summary.total_realized_pnl_krw)}
          size="xl"
        />
        <MetricTile
          label="최근 판단"
          value={latestDecision}
          tone={resolveDecisionTone(latestDecision)}
        />
        <MetricTile label="자동 BUY" value={autoBuyLabel} tone={autoBuyTone} />
      </div>

      {performanceQuery.isError && hasData && (
        <p className="mt-4 rounded-lg bg-[#ffe179]/10 p-3 text-sm font-semibold leading-6 text-[#ffe179]">
          최신 성과 데이터를 다시 가져오지 못해 최근 캐시 기준으로 표시합니다.
        </p>
      )}
    </PerformanceShell>
  )
}

export default AiPerformanceWidget
