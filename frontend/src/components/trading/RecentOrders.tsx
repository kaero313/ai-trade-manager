import type { OrderHistoryItem } from '../../services/portfolioService'

interface RecentOrdersProps {
  orders: OrderHistoryItem[]
  isLoading: boolean
  errorMessage?: string | null
  isStale?: boolean
  updatedAt?: number | null
}

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatQty(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
  }).format(value)
}

function formatExecutedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

function formatUpdatedAt(value?: number | null): string | null {
  if (!value) {
    return null
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }

  return date.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function resolveSideStyle(side: string): { label: string; className: string } {
  const normalized = side.toLowerCase()
  if (normalized === 'buy' || normalized === 'bid') {
    return {
      label: 'Buy',
      className: 'bg-[#ffb4ab]/10 text-[#ffb4ab]',
    }
  }
  if (normalized === 'sell' || normalized === 'ask') {
    return {
      label: 'Sell',
      className: 'bg-[#00dbe9]/10 text-[#7df4ff]',
    }
  }
  return {
    label: side.toUpperCase(),
    className: 'bg-[#262a31] text-[#b9cacb]',
  }
}

function RecentOrders({
  orders,
  isLoading,
  errorMessage,
  isStale = false,
  updatedAt = null,
}: RecentOrdersProps) {
  const updatedAtLabel = formatUpdatedAt(updatedAt)

  return (
    <section className="quantum-card rounded-xl p-4 sm:p-5">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-[#dfe2eb]">최근 체결</h2>
          <p className="mt-1 text-sm text-[#849495]">
            {updatedAtLabel ? `마지막 정상 조회 ${updatedAtLabel}` : '최근 체결된 매매 내역입니다.'}
          </p>
        </div>
        {isStale && (
          <span className="inline-flex shrink-0 items-center rounded-md bg-[#ffe179]/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-[#ffe179]">
            지연
          </span>
        )}
      </header>

      {errorMessage && (
        <div className="mt-4 rounded-lg bg-[#0a0e14]/80 px-3 py-3 text-sm font-semibold text-[#ffe179]">
          {errorMessage}
        </div>
      )}

      {isStale && !errorMessage && (
        <div className="mt-4 rounded-lg bg-[#0a0e14]/80 px-3 py-3 text-sm font-semibold text-[#ffe179]">
          최근 체결 새로고침에 실패해 마지막 정상 조회값을 유지하고 있습니다.
        </div>
      )}

      <div className="mt-4 space-y-2">
        {isLoading && (
          <div className="rounded-lg bg-[#0a0e14]/80 p-4">
            <div className="h-3 w-28 animate-pulse rounded bg-[#3b494b]/50" />
            <div className="mt-3 h-4 w-full animate-pulse rounded bg-[#3b494b]/50" />
            <div className="mt-2 h-4 w-4/5 animate-pulse rounded bg-[#3b494b]/50" />
          </div>
        )}

        {!isLoading && orders.length === 0 && (
          <div className="rounded-lg bg-[#0a0e14]/80 px-4 py-5 text-center">
            <p className="text-sm font-bold text-[#dfe2eb]">체결 내역 없음</p>
            <p className="mt-2 text-xs leading-5 text-[#849495]">
              전략 엔진의 체결 로그가 쌓이면 이 영역에 표시됩니다.
            </p>
          </div>
        )}

        {!isLoading &&
          orders.map((order) => {
            const sideStyle = resolveSideStyle(order.side)
            return (
              <article key={order.id} className="rounded-lg bg-[#0a0e14]/80 px-3 py-3">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="break-words text-sm font-bold text-[#dfe2eb]">
                        {order.symbol}
                      </span>
                      <span
                        className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ${sideStyle.className}`}
                      >
                        {sideStyle.label}
                      </span>
                    </div>
                    <p className="mt-1 break-words text-xs text-[#849495]">
                      {formatExecutedAt(order.executed_at)} · {order.broker}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-mono text-sm font-bold text-[#dfe2eb]">
                      {formatKrw(order.price)}
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-[#849495]">
                      {formatQty(order.qty)}
                    </p>
                  </div>
                </div>
              </article>
            )
          })}
      </div>
    </section>
  )
}

export default RecentOrders
