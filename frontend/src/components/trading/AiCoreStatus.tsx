function AiCoreStatus() {
  return (
    <section className="inline-flex items-center gap-3 rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 shadow-sm ring-1 ring-emerald-100 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20">
      <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-pulse rounded-full bg-sky-400/50" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_18px_rgba(74,222,128,0.85)]" />
      </span>
      <span className="whitespace-nowrap">AI Engine: Active</span>
      <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-gray-900/60 dark:text-emerald-300">
        Live
      </span>
    </section>
  )
}

export default AiCoreStatus
