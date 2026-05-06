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
      className: 'bg-rose-100 text-rose-700',
    }
  }
  if (normalized === 'sell' || normalized === 'ask') {
    return {
      label: 'Sell',
      className: 'bg-blue-100 text-blue-700',
    }
  }
  return {
    label: side.toUpperCase(),
    className: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
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
    <section className="rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="flex items-start justify-between gap-3 border-b border-gray-200 px-5 py-4 dark:border-gray-700">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">최근 체결</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-300">
            {updatedAtLabel ? `마지막 정상 조회 ${updatedAtLabel}` : '최근 체결된 매매 내역입니다.'}
          </p>
        </div>
        {isStale && (
          <span className="inline-flex shrink-0 items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            지연
          </span>
        )}
      </header>

      {errorMessage && (
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-700">
          {errorMessage}
        </div>
      )}

      {isStale && !errorMessage && (
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm font-medium text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          최근 체결 새로고침에 실패해 마지막 정상 조회값을 유지하고 있습니다.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
          <thead className="bg-gray-100 text-left text-gray-600 dark:bg-gray-700 dark:text-gray-300">
            <tr>
              <th className="px-5 py-3 font-semibold">체결 시간</th>
              <th className="px-5 py-3 font-semibold">종목</th>
              <th className="px-5 py-3 font-semibold">구분</th>
              <th className="px-5 py-3 font-semibold">체결가</th>
              <th className="px-5 py-3 font-semibold">수량</th>
              <th className="px-5 py-3 font-semibold">브로커</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-700 dark:bg-gray-800">
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-gray-500 dark:text-gray-300">
                  최근 체결 내역을 불러오는 중입니다.
                </td>
              </tr>
            )}

            {!isLoading && orders.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-gray-500 dark:text-gray-300">
                  체결 내역이 없습니다.
                </td>
              </tr>
            )}

            {!isLoading &&
              orders.map((order) => {
                const sideStyle = resolveSideStyle(order.side)
                return (
                  <tr key={order.id} className="text-gray-700 dark:text-gray-200">
                    <td className="px-5 py-3">{formatExecutedAt(order.executed_at)}</td>
                    <td className="px-5 py-3 font-medium text-gray-900 dark:text-gray-100">{order.symbol}</td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex min-w-14 items-center justify-center rounded-full px-2.5 py-1 text-xs font-semibold ${sideStyle.className}`}
                      >
                        {sideStyle.label}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-semibold text-gray-900 dark:text-gray-100">{formatKrw(order.price)}</td>
                    <td className="px-5 py-3">{formatQty(order.qty)}</td>
                    <td className="px-5 py-3">{order.broker}</td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default RecentOrders
