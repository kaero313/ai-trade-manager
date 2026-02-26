import { useEffect, useState } from 'react'

import { getBotStatus } from '../services/botService'
import type { BotStatus } from '../services/botService'
import { getPortfolioSummary } from '../services/portfolioService'
import type { AssetItem, PortfolioSummary } from '../services/portfolioService'

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${formatKrw(Math.abs(value))}`
}

function formatPercent(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '' : ''
  return `${sign}${value.toFixed(2)}%`
}

function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    const loadDashboard = async () => {
      setIsLoading(true)
      setErrorMessage(null)

      try {
        const [portfolioData, botStatusData] = await Promise.all([getPortfolioSummary(), getBotStatus()])
        if (!isMounted) return
        setPortfolio(portfolioData)
        setBotStatus(botStatusData)
      } catch {
        if (!isMounted) return
        setErrorMessage('대시보드 데이터를 불러오지 못했습니다.')
      } finally {
        if (!isMounted) return
        setIsLoading(false)
      }
    }

    void loadDashboard()

    return () => {
      isMounted = false
    }
  }, [])

  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const totalPnl = portfolio?.total_pnl ?? 0
  const assets: AssetItem[] = portfolio?.items ?? []
  const pnlTextColor = totalPnl >= 0 ? 'text-emerald-600' : 'text-rose-600'
  const isRunning = botStatus?.running ?? false
  const statusLabel = isRunning ? 'Running' : 'Paused'
  const statusClass = isRunning
    ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
    : 'bg-slate-200 text-slate-700 border border-slate-300'

  return (
    <div className="space-y-6">
      {errorMessage && (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {errorMessage}
        </section>
      )}

      <section className="grid gap-4 md:grid-cols-2">
        <article className="rounded-2xl bg-slate-900 p-6 text-slate-100 shadow-lg">
          <p className="text-sm font-medium text-slate-300">총 자산</p>
          <p className="mt-2 text-3xl font-bold sm:text-4xl">
            {isLoading ? '불러오는 중...' : formatKrw(totalNetWorth)}
          </p>
        </article>

        <article className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <p className="text-sm font-medium text-slate-500">총 손익</p>
          <p className={`mt-2 text-3xl font-bold sm:text-4xl ${pnlTextColor}`}>
            {isLoading ? '불러오는 중...' : formatSignedKrw(totalPnl)}
          </p>
        </article>
      </section>

      <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Bot Status</h2>
          <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${statusClass}`}>
            {isLoading ? '확인 중...' : statusLabel}
          </span>
        </div>
      </section>

      <section className="rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <header className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-900">Assets</h2>
        </header>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-100 text-left text-slate-600">
              <tr>
                <th className="px-5 py-3 font-semibold">종목명</th>
                <th className="px-5 py-3 font-semibold">현재가</th>
                <th className="px-5 py-3 font-semibold">평균단가</th>
                <th className="px-5 py-3 font-semibold">수익률</th>
                <th className="px-5 py-3 font-semibold">추정금액</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {isLoading && (
                <tr>
                  <td colSpan={5} className="px-5 py-8 text-center text-slate-500">
                    자산 데이터를 불러오는 중입니다.
                  </td>
                </tr>
              )}

              {!isLoading && assets.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-8 text-center text-slate-500">
                    보유 중인 자산이 없습니다.
                  </td>
                </tr>
              )}

              {!isLoading &&
                assets.map((item) => {
                  const assetPnlClass = item.pnl_percentage >= 0 ? 'text-emerald-600' : 'text-rose-600'

                  return (
                    <tr key={`${item.broker}-${item.currency}`} className="text-slate-700">
                      <td className="px-5 py-3 font-medium text-slate-900">
                        {item.currency}
                        <p className="mt-0.5 text-xs text-slate-500">{item.broker}</p>
                      </td>
                      <td className="px-5 py-3">{formatKrw(item.current_price)}</td>
                      <td className="px-5 py-3">{formatKrw(item.avg_buy_price)}</td>
                      <td className={`px-5 py-3 font-semibold ${assetPnlClass}`}>
                        {formatPercent(item.pnl_percentage)}
                      </td>
                      <td className="px-5 py-3 font-semibold text-slate-900">{formatKrw(item.total_value)}</td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

export default DashboardPage
