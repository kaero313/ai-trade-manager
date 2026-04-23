interface PortfolioSummaryCardProps {
  totalNetWorth: number
  totalPnl: number
  krwBalance: number
  coinCount: number
  isLoading: boolean
}

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(Math.abs(value)))}`
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

function formatCoinCount(value: number): string {
  return `${new Intl.NumberFormat('ko-KR').format(Math.max(0, Math.round(value)))}개`
}

function resolvePnlTone(totalPnl: number): string {
  if (totalPnl > 0) {
    return 'text-emerald-600 dark:text-emerald-300'
  }
  if (totalPnl < 0) {
    return 'text-rose-600 dark:text-rose-300'
  }
  return 'text-slate-900 dark:text-slate-100'
}

function SummaryMetric({
  label,
  value,
  valueClassName = 'text-slate-900 dark:text-slate-100',
}: {
  label: string
  value: string
  valueClassName?: string
}) {
  return (
    <div className="rounded-2xl border border-white/60 bg-white/55 px-4 py-4 shadow-[0_18px_40px_-28px_rgba(15,23,42,0.7)] backdrop-blur transition-shadow duration-200 hover:shadow-[0_24px_56px_-30px_rgba(15,23,42,0.72)] md:px-5 dark:border-white/10 dark:bg-white/5 dark:shadow-[0_18px_40px_-28px_rgba(2,6,23,0.9)] dark:hover:shadow-[0_24px_56px_-30px_rgba(2,6,23,0.95)]">
      <p className="text-[11px] font-semibold tracking-[0.22em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className={`mt-3 text-lg font-semibold ${valueClassName}`}>{value}</p>
    </div>
  )
}

function PortfolioSummaryCard({
  totalNetWorth,
  totalPnl,
  krwBalance,
  coinCount,
  isLoading,
}: PortfolioSummaryCardProps) {
  return (
    <section className="relative overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-6 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.55)] backdrop-blur-xl transition-shadow duration-200 hover:shadow-[0_36px_110px_-44px_rgba(15,23,42,0.6)] dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_36px_110px_-44px_rgba(2,6,23,1)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.16),_transparent_38%),radial-gradient(circle_at_top_right,_rgba(14,165,233,0.14),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.38),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.18),_transparent_34%),radial-gradient(circle_at_top_right,_rgba(59,130,246,0.18),_transparent_28%),linear-gradient(135deg,rgba(255,255,255,0.08),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/15" />

      <div className="relative">
        {isLoading ? (
          <div className="animate-pulse">
            <div className="h-3 w-24 rounded-full bg-slate-200/90 dark:bg-slate-700/80" />
            <div className="mt-5 h-12 w-56 rounded-2xl bg-slate-200/90 dark:bg-slate-700/80" />

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-white/50 bg-white/45 px-4 py-4 backdrop-blur dark:border-white/10 dark:bg-white/5">
                <div className="h-3 w-20 rounded-full bg-emerald-100 dark:bg-emerald-500/20" />
                <div className="mt-3 h-7 w-28 rounded-xl bg-emerald-100 dark:bg-emerald-500/20" />
              </div>
              <div className="rounded-2xl border border-white/50 bg-white/45 px-4 py-4 backdrop-blur dark:border-white/10 dark:bg-white/5">
                <div className="h-3 w-16 rounded-full bg-slate-200 dark:bg-slate-700" />
                <div className="mt-3 h-7 w-24 rounded-xl bg-slate-200 dark:bg-slate-700" />
              </div>
              <div className="rounded-2xl border border-white/50 bg-white/45 px-4 py-4 backdrop-blur dark:border-white/10 dark:bg-white/5">
                <div className="h-3 w-16 rounded-full bg-slate-200 dark:bg-slate-700" />
                <div className="mt-3 h-7 w-20 rounded-xl bg-slate-200 dark:bg-slate-700" />
              </div>
            </div>
          </div>
        ) : (
          <>
            <div>
              <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
                총 순자산
              </p>
              <p className="mt-4 text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl dark:text-white">
                {formatKrw(totalNetWorth)}
              </p>
            </div>

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <SummaryMetric
                label="총 평가손익"
                value={formatSignedKrw(totalPnl)}
                valueClassName={resolvePnlTone(totalPnl)}
              />
              <SummaryMetric label="KRW 잔고" value={formatKrw(krwBalance)} />
              <SummaryMetric label="보유 코인 수" value={formatCoinCount(coinCount)} />
            </div>
          </>
        )}
      </div>
    </section>
  )
}

export default PortfolioSummaryCard
