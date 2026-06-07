import type { OrderHistoryItem } from '../../services/portfolioService'

interface RecentOrdersProps {
  orders: OrderHistoryItem[]
  isLoading: boolean
  errorMessage?: string | null
  isStale?: boolean
  updatedAt?: number | null
}

const RECENT_ORDER_LIMIT = 6

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

  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${month}.${day} ${hours}:${minutes}`
}

function formatSignedPct(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(1)}%`
}

function resolveTradeAmount(order: OrderHistoryItem): number {
  if (typeof order.trade_amount_krw === 'number' && Number.isFinite(order.trade_amount_krw)) {
    return order.trade_amount_krw
  }
  return Math.max(order.price, 0) * Math.max(order.qty, 0)
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

function resolvePnlStyle(
  side: string,
  value: number | null | undefined,
): { label: string; className: string } {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return {
      label: resolveSideStyle(side).label === 'Buy' ? '진입' : '--%',
      className: 'text-[#849495]',
    }
  }
  if (value > 0) {
    return {
      label: formatSignedPct(value),
      className: 'text-[#77e2a8]',
    }
  }
  if (value < 0) {
    return {
      label: formatSignedPct(value),
      className: 'text-[#ffb4ab]',
    }
  }
  return {
    label: '0.0%',
    className: 'text-[#b9cacb]',
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
  const visibleOrders = orders.slice(0, RECENT_ORDER_LIMIT)
  const hiddenOrderCount = Math.max(orders.length - visibleOrders.length, 0)

  return (
    <section className="quantum-card rounded-xl p-4 sm:p-5">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-[#dfe2eb]">최근 체결</h2>
          <p className="mt-1 text-sm text-[#849495]">
            {updatedAtLabel
              ? `최근 ${visibleOrders.length}건 · 마지막 조회 ${updatedAtLabel}`
              : `최근 ${RECENT_ORDER_LIMIT}건만 간단히 표시합니다.`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {hiddenOrderCount > 0 && (
            <span className="inline-flex items-center rounded-md bg-[#262a31]/70 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-[#b9cacb]">
              +{hiddenOrderCount}
            </span>
          )}
          {isStale && (
            <span className="inline-flex items-center rounded-md bg-[#ffe179]/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-[#ffe179]">
              지연
            </span>
          )}
        </div>
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

      <div className="mt-4">
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

        {!isLoading && visibleOrders.length > 0 && (
          <div className="grid gap-2 md:grid-cols-2">
            {visibleOrders.map((order) => {
              const sideStyle = resolveSideStyle(order.side)
              const pnlStyle = resolvePnlStyle(order.side, order.pnl_percentage)
              const tradeAmount = resolveTradeAmount(order)
              return (
                <article
                  key={order.id}
                  className="rounded-lg bg-[#0a0e14]/80 px-3 py-2.5"
                  title={`단가 ${formatKrw(order.price)} · 수량 ${formatQty(order.qty)} · ${order.broker}`}
                >
                  <div className="flex min-w-0 items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="shrink-0 text-sm font-bold text-[#dfe2eb]">
                        {order.symbol}
                      </span>
                      <span
                        className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ${sideStyle.className}`}
                      >
                        {sideStyle.label}
                      </span>
                    </div>
                    <span className={`shrink-0 font-mono text-xs font-bold ${pnlStyle.className}`}>
                      {pnlStyle.label}
                    </span>
                  </div>
                  <div className="mt-2 flex min-w-0 items-center justify-between gap-2">
                    <span className="truncate text-xs text-[#849495]">
                      {formatExecutedAt(order.executed_at)}
                    </span>
                    <span className="shrink-0 font-mono text-sm font-bold text-[#dfe2eb]">
                      {formatKrw(tradeAmount)}
                    </span>
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

export default RecentOrders
