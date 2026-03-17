interface AiInsightBriefingProps {
  symbol: string | null
}

function AiInsightBriefing({ symbol }: AiInsightBriefingProps) {
  const normalizedSymbol = symbol?.trim().toUpperCase() || null
  const symbolDescription = normalizedSymbol
    ? `현재 ${normalizedSymbol}에 대한 AI 분석입니다`
    : '현재 선택된 종목에 대한 AI 분석 대기 중입니다'

  const reasons = [
    '1시간 봉 기준 RSI 30 미만 진입',
    '100M KRW 주요 매물대 지지 테스트 완료',
    '단기 거래량 회복과 저점 방어 동시 확인',
  ]

  return (
    <section className="shrink-0 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
        <div className="rounded-xl bg-gradient-to-br from-emerald-50 via-white to-sky-50 p-5 ring-1 ring-emerald-100 dark:from-emerald-500/10 dark:via-gray-800 dark:to-sky-500/10 dark:ring-emerald-500/20">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-400">AI Briefing</p>
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-300">{symbolDescription}</p>
          <h2 className="mt-4 text-2xl font-bold text-gray-900 dark:text-gray-100">AI 스탠스: BUY</h2>
          <p className="mt-1 text-sm font-semibold text-emerald-600 dark:text-emerald-400">(매수 우위)</p>

          <div className="mt-5 flex flex-wrap items-center gap-4">
            <div className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-emerald-200 bg-white text-xl font-bold text-emerald-600 shadow-inner dark:border-emerald-500/30 dark:bg-gray-900 dark:text-emerald-300">
              88%
            </div>

            <div className="space-y-2">
              <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-sm font-semibold text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/20">
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                신뢰도 88%
              </span>
              <span className="inline-flex items-center rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700 ring-1 ring-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/20">
                1H Momentum Positive
              </span>
            </div>
          </div>
        </div>

        <div className="rounded-xl bg-gray-50 p-5 ring-1 ring-gray-200 dark:bg-gray-900/60 dark:ring-gray-700">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">판단 근거 (XAI)</h3>
          <ul className="mt-4 space-y-3 text-sm leading-6 text-gray-700 dark:text-gray-200">
            {reasons.map((reason) => (
              <li key={reason} className="flex gap-3">
                <span className="mt-1 text-emerald-500">•</span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">실시간 체결강도 및 호가 해석을 반영한 임시 브리핑</p>
        </div>
      </div>
    </section>
  )
}

export default AiInsightBriefing
