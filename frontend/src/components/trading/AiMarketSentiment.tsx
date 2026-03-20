const sentimentScore = 72
const gaugeDegrees = sentimentScore * 1.8

const trendStrength = '강함'
const volatilityWarning = '주의'
const sentimentLabel = '탐욕'
const sentimentDescription = '단기 추세는 우상향이지만 과열 진입 구간을 경계 중입니다.'

const gaugeStyle = {
  background: `conic-gradient(from 180deg, #38bdf8 0deg, #10b981 92deg, #fb7185 ${gaugeDegrees}deg, #e5e7eb ${gaugeDegrees}deg, #e5e7eb 180deg, transparent 180deg 360deg)`,
}

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
              시장 심리지수 72
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
            <div className="relative mx-auto h-40 w-full max-w-[260px] overflow-hidden">
              <div
                className="absolute inset-x-0 bottom-0 mx-auto h-[240px] w-[240px] rounded-full"
                style={gaugeStyle}
              />
              <div className="absolute inset-x-0 bottom-0 mx-auto h-[192px] w-[192px] rounded-full bg-white dark:bg-gray-900" />
              <div className="absolute inset-x-0 bottom-0 h-1/2 bg-white dark:bg-gray-900" />

              <div className="absolute inset-x-0 bottom-4 flex flex-col items-center">
                <span className="text-4xl font-black tracking-tight text-gray-900 dark:text-gray-100">
                  {sentimentScore}
                </span>
                <span className="mt-1 break-words text-center text-xs font-semibold uppercase tracking-[0.22em] text-gray-500 dark:text-gray-400">
                  {sentimentLabel}
                </span>
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

            <div className="min-w-0 overflow-hidden rounded-xl bg-gray-950 p-4 text-gray-100 ring-1 ring-gray-900 dark:bg-gray-950">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full bg-sky-500/15 px-3 py-1 text-xs font-semibold text-sky-300 ring-1 ring-sky-500/20">
                  Momentum Expansion
                </span>
                <span className="rounded-full bg-rose-500/15 px-3 py-1 text-xs font-semibold text-rose-300 ring-1 ring-rose-500/20">
                  Volatility Elevated
                </span>
              </div>

              <p className="mt-4 break-words text-sm leading-6 text-gray-200">
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
