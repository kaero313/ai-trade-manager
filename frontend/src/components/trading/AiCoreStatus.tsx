import { useEffect, useState } from 'react'

const LOG_MESSAGES = [
  'Analyzing KRW-BTC Orderbook...',
  'Calculating Divergence...',
  'Monitoring volatility spread...',
  'Evaluating entry confidence...',
  'Scanning liquidity imbalance...',
] as const

function formatTimestamp(date: Date): string {
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

function AiCoreStatus() {
  const [cursor, setCursor] = useState(0)
  const [baseTime, setBaseTime] = useState(() => Date.now())

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setCursor((previousCursor) => (previousCursor + 1) % LOG_MESSAGES.length)
      setBaseTime(Date.now())
    }, 1600)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [])

  const logLines = Array.from({ length: 3 }, (_, index) => {
    const messageIndex = (cursor + index) % LOG_MESSAGES.length
    const timestamp = new Date(baseTime - (2 - index) * 1000)
    return `[${formatTimestamp(timestamp)}] ${LOG_MESSAGES[messageIndex]}`
  })

  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-400 dark:text-gray-500">AI Core</p>
          <div className="mt-2 flex items-center gap-3">
            <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
              <span className="absolute inline-flex h-full w-full animate-pulse rounded-full bg-sky-400/50" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_18px_rgba(74,222,128,0.85)]" />
            </span>
            <h2 className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">[AI Engine: Active]</h2>
          </div>
        </div>
        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          Live
        </span>
      </header>

      <div className="mt-4 rounded-xl bg-gray-950 p-4 font-mono text-xs leading-6 text-emerald-300 ring-1 ring-gray-900/80 dark:bg-black">
        <p className="mb-3 text-[11px] uppercase tracking-[0.24em] text-emerald-500/80">Realtime Signal Console</p>
        <div className="space-y-1.5">
          {logLines.map((line) => (
            <p key={line} className="truncate text-emerald-300/95">
              {line}
            </p>
          ))}
        </div>
      </div>
    </section>
  )
}

export default AiCoreStatus
