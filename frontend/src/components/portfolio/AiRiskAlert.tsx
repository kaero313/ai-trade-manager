import { AlertTriangle, TrendingDown, TrendingUp } from 'lucide-react'

import type { AssetItem } from '../../services/portfolioService'
import {
  PORTFOLIO_BODY_TEXT_CLASS_NAME,
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
} from './portfolioStyles'

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
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/12 dark:text-rose-200'
  }
  if (tone === 'info') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/12 dark:text-emerald-200'
  }
  return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-300/20 dark:bg-amber-500/12 dark:text-amber-200'
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
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4 text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/12 dark:text-emerald-200">
      <div className="flex items-center gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-white text-emerald-600 ring-1 ring-emerald-200 dark:bg-gray-900 dark:text-emerald-200 dark:ring-emerald-300/15">
          <TrendingUp className="h-5 w-5" />
        </span>
        <div>
          <p className="text-[11px] font-semibold tracking-[0.18em] opacity-80">AI RISK CHECK</p>
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
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} overflow-hidden p-6`}>
      <div>
        <header className="mb-5">
          <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
            AI RISK ALERT
          </p>
          <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>
            포트폴리오 리스크 알림
          </h2>
          <p className={PORTFOLIO_BODY_TEXT_CLASS_NAME}>
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
                  className={`rounded-xl border px-5 py-4 transition-shadow duration-200 hover:shadow-sm ${resolveAlertCardClassName(alert.tone)}`}
                >
                  <div className="flex items-start gap-4">
                    <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white ring-1 ring-white/70 dark:bg-gray-900 dark:ring-white/10">
                      <Icon className="h-5 w-5" />
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold tracking-[0.14em] ring-1 ring-white/70 dark:bg-gray-900 dark:ring-white/10">
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
