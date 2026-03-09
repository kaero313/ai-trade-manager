import type { BotStatus } from '../../services/api'

interface BotControlPanelProps {
  botStatus: BotStatus | null | undefined
  isLoading: boolean
  isError: boolean
}

function BotControlPanel({ botStatus, isLoading, isError }: BotControlPanelProps) {
  const isActive = botStatus?.running ?? false
  const badgeLabel = isError ? 'Error' : isLoading ? '확인 중' : isActive ? 'Active' : 'Inactive'
  const badgeClassName = isError
    ? 'border border-rose-200 bg-rose-100 text-rose-700'
    : isActive
      ? 'border border-emerald-200 bg-emerald-100 text-emerald-700'
      : 'border border-slate-300 bg-slate-200 text-slate-700'
  const description = isError
    ? '봇 상태를 확인하지 못했습니다.'
    : isLoading
      ? '봇 상태를 확인하고 있습니다.'
      : isActive
        ? '트레이딩 봇이 현재 가동 중입니다.'
        : '트레이딩 봇이 현재 정지 상태입니다.'

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Bot Status</h2>
          <p className="mt-1 text-sm text-slate-500">5초 주기로 실시간 상태를 자동 갱신합니다.</p>
        </div>
        <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${badgeClassName}`}>
          {badgeLabel}
        </span>
      </header>

      <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
        <span className={`h-2.5 w-2.5 rounded-full ${isError ? 'bg-rose-500' : isActive ? 'bg-emerald-500' : 'bg-slate-400'}`} />
        <p>{description}</p>
      </div>
    </aside>
  )
}

export default BotControlPanel
