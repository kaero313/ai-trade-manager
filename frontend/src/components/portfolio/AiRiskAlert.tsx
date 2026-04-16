import { AlertTriangle, TrendingDown, TrendingUp } from 'lucide-react'

import type { AssetItem } from '../../services/portfolioService'

interface AiRiskAlertProps {
  items: AssetItem[]
  totalNetWorth: number
}

type AlertTone = 'warning' | 'danger' | 'info'

interface RiskAlertItem {
  id: string
  tone: AlertTone
  message: string
}

function formatPercentage(value: number, { signed = false }: { signed?: boolean } = {}): string {
  const safeValue = Number.isFinite(value) ? value : 0
  const prefix = signed && safeValue > 0 ? '+' : ''
  return `${prefix}${safeValue.toFixed(1)}%`
}

function resolveAlertCardClassName(tone: AlertTone): string {
  if (tone === 'danger') {
    return 'border-rose-200/80 bg-rose-50/90 text-rose-700 shadow-[0_18px_40px_-30px_rgba(225,29,72,0.8)] dark:border-rose-300/20 dark:bg-rose-500/12 dark:text-rose-200'
  }
  if (tone === 'info') {
    return 'border-emerald-200/80 bg-emerald-50/90 text-emerald-700 shadow-[0_18px_40px_-30px_rgba(5,150,105,0.8)] dark:border-emerald-300/20 dark:bg-emerald-500/12 dark:text-emerald-200'
  }
  return 'border-amber-200/80 bg-amber-50/90 text-amber-700 shadow-[0_18px_40px_-30px_rgba(217,119,6,0.8)] dark:border-amber-300/20 dark:bg-amber-500/12 dark:text-amber-200'
}

function resolveAlertIcon(tone: AlertTone) {
  if (tone === 'danger') {
    return TrendingDown
  }
  if (tone === 'info') {
    return TrendingUp
  }
  return AlertTriangle
}

function resolveAlertChipLabel(tone: AlertTone): string {
  if (tone === 'danger') {
    return '위험'
  }
  if (tone === 'info') {
    return '정보'
  }
  return '경고'
}

function buildRiskAlerts(items: AssetItem[], totalNetWorth: number): RiskAlertItem[] {
  const alerts: RiskAlertItem[] = []
  const normalizedTotalNetWorth = Number.isFinite(totalNetWorth) ? totalNetWorth : 0

  for (const item of items) {
    const currency = String(item.currency || '').trim().toUpperCase()
    if (!currency || currency === 'KRW') {
      continue
    }

    const totalValue = Number(item.total_value)
    const pnlPercentage = Number(item.pnl_percentage)
    const weight =
      normalizedTotalNetWorth > 0 && Number.isFinite(totalValue)
        ? (totalValue / normalizedTotalNetWorth) * 100
        : 0

    if (weight > 60) {
      alerts.push({
        id: `${currency}-warning-concentration`,
        tone: 'warning',
        message: `🟠 ${currency} 비중이 ${formatPercentage(weight)}로 높습니다. 분산 투자를 권장합니다.`,
      })
    }

    if (Number.isFinite(pnlPercentage) && pnlPercentage <= -10) {
      alerts.push({
        id: `${currency}-danger-loss`,
        tone: 'danger',
        message: `🔴 ${currency}이 ${formatPercentage(pnlPercentage)} 손실 중입니다. 손절 검토가 필요합니다.`,
      })
    }

    if (Number.isFinite(pnlPercentage) && pnlPercentage >= 15) {
      alerts.push({
        id: `${currency}-info-profit`,
        tone: 'info',
        message: `🟢 ${currency}이 ${formatPercentage(pnlPercentage, { signed: true })} 수익 중입니다. 익절 시점을 점검하세요.`,
      })
    }
  }

  return alerts
}

function StableStateBadge() {
  return (
    <div className="rounded-[24px] border border-emerald-200/80 bg-emerald-50/90 px-5 py-4 text-emerald-700 shadow-[0_18px_40px_-30px_rgba(5,150,105,0.8)] dark:border-emerald-300/20 dark:bg-emerald-500/12 dark:text-emerald-200">
      <div className="flex items-center gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-2xl bg-white/80 text-emerald-600 ring-1 ring-emerald-200/80 dark:bg-slate-900/60 dark:text-emerald-200 dark:ring-emerald-300/15">
          <TrendingUp className="h-5 w-5" />
        </span>
        <div>
          <p className="text-[11px] font-semibold tracking-[0.22em] opacity-80">AI RISK CHECK</p>
          <p className="mt-1 text-sm font-semibold">현재 특이사항 없음</p>
        </div>
      </div>
    </div>
  )
}

function AiRiskAlert({
  items,
  totalNetWorth,
}: AiRiskAlertProps) {
  const alerts = buildRiskAlerts(items, totalNetWorth)

  return (
    <section className="relative overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-6 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.5)] backdrop-blur-xl dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.14),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.1),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.16),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(16,185,129,0.12),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative">
        <header className="mb-5">
          <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
            AI RISK ALERT
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
            포트폴리오 리스크 알림
          </h2>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            보유 비중과 수익률을 기준으로 현재 포트폴리오의 주의 신호를 점검합니다.
          </p>
        </header>

        {alerts.length === 0 ? (
          <StableStateBadge />
        ) : (
          <div className="grid gap-3">
            {alerts.map((alert) => {
              const Icon = resolveAlertIcon(alert.tone)

              return (
                <article
                  key={alert.id}
                  className={`rounded-[24px] border px-5 py-4 transition-transform duration-200 hover:-translate-y-0.5 hover:scale-[1.01] ${resolveAlertCardClassName(alert.tone)}`}
                >
                  <div className="flex items-start gap-4">
                    <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/80 ring-1 ring-white/70 backdrop-blur dark:bg-slate-900/60 dark:ring-white/10">
                      <Icon className="h-5 w-5" />
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center rounded-full bg-white/70 px-2.5 py-1 text-[11px] font-semibold tracking-[0.18em] ring-1 ring-white/70 dark:bg-slate-900/60 dark:ring-white/10">
                          {resolveAlertChipLabel(alert.tone)}
                        </span>
                      </div>
                      <p className="mt-3 text-sm font-medium leading-6">{alert.message}</p>
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}

export default AiRiskAlert
