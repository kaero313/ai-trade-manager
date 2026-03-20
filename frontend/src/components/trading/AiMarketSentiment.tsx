const sentimentScore = 72

const trendStrength = '강함'
const volatilityWarning = '주의'
const sentimentLabel = '탐욕'
const sentimentDescription = '단기 추세는 우상향이지만 과열 진입 구간을 경계 중입니다.'

function AiMarketSentiment() {
  return (
    <section className="min-w-0 shrink-0 overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="h-full min-w-0 overflow-hidden bg-gradient-to-br from-sky-50 via-white to-rose-50 p-4 dark:from-sky-500/10 dark:via-gray-800 dark:to-rose-500/10 sm:p-5">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 break-words">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-600 dark:text-sky-300">
              AI Fear & Greed Index
            </p>
            <h2 className="mt-3 break-words text-2xl font-bold text-gray-900 dark:text-gray-100">
              시장 심리지수 {sentimentScore}
            </h2>
            <p className="mt-2 break-words text-sm text-gray-500 dark:text-gray-300">
              AI가 현재 시장 참여자의 위험 선호도를 해석한 Mock 지표입니다.
            </p>
          </div>

          <span className="inline-flex max-w-full items-center gap-2 break-words rounded-full bg-rose-50 px-3 py-1 text-sm font-semibold text-rose-700 ring-1 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20">
            <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
            {sentimentLabel}
          </span>
        </div>

        <div className="mt-6 grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.95fr)]">
          <div className="min-w-0 rounded-xl bg-white/80 p-4 ring-1 ring-white/70 backdrop-blur dark:bg-gray-900/50 dark:ring-gray-700/80">
            <div className="space-y-4">
              <div className="flex min-w-0 items-end justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">
                    Current Position
                  </p>
                  <p className="mt-2 text-3xl font-black tracking-tight text-gray-900 dark:text-gray-100">
                    {sentimentScore}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">
                    Market Bias
                  </p>
                  <p className="mt-2 break-words text-lg font-bold text-rose-600 dark:text-rose-300">
                    {sentimentLabel}
                  </p>
                </div>
              </div>

              <div className="space-y-3">
                <div className="relative pt-4">
                  <div className="h-3 w-full rounded-full bg-gradient-to-r from-sky-400 via-emerald-400 to-rose-400" />
                  <div
                    className="absolute top-0 -translate-x-1/2"
                    style={{ left: `${sentimentScore}%` }}
                  >
                    <span className="block h-3 w-3 rounded-full border-2 border-white bg-gray-950 shadow-sm dark:border-gray-900 dark:bg-white" />
                  </div>
                </div>

                <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  <span>0 Fear</span>
                  <span>100 Greed</span>
                </div>

                <p className="text-sm text-gray-600 dark:text-gray-300">
                  공포에서 탐욕까지 현재 시장 심리 위치를 한 줄로 요약합니다.
                </p>
              </div>
            </div>
          </div>

          <div className="min-w-0 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <article className="min-w-0 rounded-xl bg-emerald-50 p-4 ring-1 ring-emerald-100 dark:bg-emerald-500/10 dark:ring-emerald-500/20">
                <p className="break-words text-xs font-semibold uppercase tracking-[0.2em] text-emerald-600 dark:text-emerald-300">
                  현재 트렌드 강도
                </p>
                <p className="mt-2 break-words text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {trendStrength}
                </p>
              </article>

              <article className="min-w-0 rounded-xl bg-rose-50 p-4 ring-1 ring-rose-100 dark:bg-rose-500/10 dark:ring-rose-500/20">
                <p className="break-words text-xs font-semibold uppercase tracking-[0.2em] text-rose-600 dark:text-rose-300">
                  변동성 경고
                </p>
                <p className="mt-2 break-words text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {volatilityWarning}
                </p>
              </article>
            </div>

            <div className="min-w-0 overflow-hidden rounded-xl bg-gray-50 p-4 text-gray-900 ring-1 ring-gray-200 dark:bg-gray-950 dark:text-gray-100 dark:ring-gray-800">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700 ring-1 ring-sky-200 dark:bg-sky-500/15 dark:text-sky-300 dark:ring-sky-500/20">
                  Momentum Expansion
                </span>
                <span className="rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700 ring-1 ring-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-500/20">
                  Volatility Elevated
                </span>
              </div>

              <p className="mt-4 break-words text-sm leading-6 text-gray-700 dark:text-gray-200">
                {sentimentDescription}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default AiMarketSentiment
