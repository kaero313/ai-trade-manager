import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getLatestAiAnalysis } from '../../services/api'
import type { LatestAiAnalysis } from '../../services/api'

interface AiInsightBriefingProps {
  symbol: string | null
}

type DecisionTone = {
  chipClassName: string
  panelClassName: string
  progressClassName: string
  glowClassName: string
  label: string
  caption: string
}

function normalizeSymbol(symbol: string | null): string | null {
  const normalized = symbol?.trim().toUpperCase() ?? ''
  return normalized.length > 0 ? normalized : null
}

function clampPercentage(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }

  return Math.max(0, Math.min(100, Math.round(value)))
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function resolveDecisionTone(decision: LatestAiAnalysis['decision']): DecisionTone {
  if (decision === 'BUY') {
    return {
      chipClassName:
        'border border-white/15 bg-white/10 text-white backdrop-blur',
      panelClassName:
        'bg-gradient-to-br from-emerald-700 via-emerald-600 to-teal-700 text-white shadow-[0_14px_30px_rgba(6,95,70,0.18)]',
      progressClassName: 'from-emerald-400 via-emerald-500 to-teal-500',
      glowClassName: 'bg-emerald-200/10',
      label: '매수 우위',
      caption: '상승 여지가 더 크다고 판단했습니다.',
    }
  }

  if (decision === 'SELL') {
    return {
      chipClassName:
        'border border-white/15 bg-white/10 text-white backdrop-blur',
      panelClassName:
        'bg-gradient-to-br from-rose-700 via-rose-600 to-red-700 text-white shadow-[0_14px_30px_rgba(159,18,57,0.18)]',
      progressClassName: 'from-rose-400 via-rose-500 to-red-500',
      glowClassName: 'bg-rose-200/10',
      label: '매도 우위',
      caption: '리스크 회피와 차익 실현을 우선했습니다.',
    }
  }

  return {
    chipClassName:
      'border border-white/15 bg-white/10 text-white backdrop-blur',
    panelClassName:
      'bg-gradient-to-br from-amber-700 via-amber-600 to-slate-700 text-white shadow-[0_14px_30px_rgba(146,64,14,0.18)]',
    progressClassName: 'from-amber-300 via-amber-400 to-slate-500',
    glowClassName: 'bg-amber-200/10',
    label: '관망 우위',
    caption: '방향성이 선명해질 때까지 보수적으로 접근합니다.',
  }
}

function InsightSkeleton() {
  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="grid min-h-0 gap-5 p-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
        <div className="space-y-4 rounded-2xl bg-gray-100/80 p-5 animate-pulse dark:bg-gray-700/50">
          <div className="h-4 w-28 rounded-full bg-gray-200 dark:bg-gray-600" />
          <div className="h-10 w-40 rounded-2xl bg-gray-200 dark:bg-gray-600" />
          <div className="h-5 w-24 rounded-full bg-gray-200 dark:bg-gray-600" />
          <div className="space-y-2 pt-4">
            <div className="h-3 w-24 rounded-full bg-gray-200 dark:bg-gray-600" />
            <div className="h-3 w-full rounded-full bg-gray-200 dark:bg-gray-600" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="h-20 rounded-2xl bg-gray-200 dark:bg-gray-600" />
            <div className="h-20 rounded-2xl bg-gray-200 dark:bg-gray-600" />
          </div>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-gray-50 p-5 animate-pulse dark:border-gray-700 dark:bg-gray-900/60">
          <div className="h-4 w-32 rounded-full bg-gray-200 dark:bg-gray-700" />
          <div className="mt-4 space-y-3">
            <div className="h-4 w-full rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 w-full rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 w-4/5 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 w-5/6 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="h-4 w-3/4 rounded-full bg-gray-200 dark:bg-gray-700" />
          </div>
        </div>
      </div>
    </section>
  )
}

function EmptyInsightCard({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 px-6 py-10 text-center">
        <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-gray-500 dark:bg-gray-700 dark:text-gray-300">
          AI Briefing
        </span>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h3>
        <p className="max-w-xl break-words text-sm leading-6 text-gray-500 dark:text-gray-400">
          {description}
        </p>
      </div>
    </section>
  )
}

function AiInsightBriefing({ symbol }: AiInsightBriefingProps) {
  const normalizedSymbol = normalizeSymbol(symbol)
  const [isTooltipOpen, setIsTooltipOpen] = useState(false)

  const analysisQuery = useQuery({
    queryKey: ['latest-ai-analysis', normalizedSymbol],
    queryFn: () => getLatestAiAnalysis(normalizedSymbol as string),
    enabled: Boolean(normalizedSymbol),
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  if (!normalizedSymbol) {
    return (
      <EmptyInsightCard
        title="AI 브리핑 대기 중"
        description="종목을 선택하면 해당 코인에 대한 최신 AI 추론 로그를 실시간으로 표시합니다."
      />
    )
  }

  const analysis = analysisQuery.data
  const showSkeleton =
    !analysis &&
    (analysisQuery.isLoading || analysisQuery.isPending || (analysisQuery.isError && !analysisQuery.data))

  if (showSkeleton) {
    return <InsightSkeleton />
  }

  if (!analysis) {
    return (
      <EmptyInsightCard
        title={`${normalizedSymbol} 최신 추론 없음`}
        description="아직 이 종목에 대해 저장된 AI 분석 로그가 없습니다. 백그라운드 추론 엔진이 다음 회차에 로그를 쌓으면 이 영역에 즉시 반영됩니다."
      />
    )
  }

  const tone = resolveDecisionTone(analysis.decision)
  const confidence = clampPercentage(analysis.confidence)
  const recommendedWeight = clampPercentage(analysis.recommended_weight)

  let syncStatus = `업데이트 ${formatUpdatedAt(analysis.created_at)}`
  if (analysisQuery.isFetching) {
    syncStatus = `${syncStatus} · 최신 추론 동기화 중...`
  } else if (analysisQuery.isError) {
    syncStatus = `${syncStatus} · 최근 데이터 기준으로 표시 중`
  }

  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="grid min-h-0 gap-5 p-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
        <div className={`relative overflow-hidden rounded-[24px] p-5 ${tone.panelClassName}`}>
          <div className={`absolute -right-8 -top-8 h-28 w-28 rounded-full blur-2xl ${tone.glowClassName}`} />
          <div className="relative flex h-full min-h-0 flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-white/70">
                  AI Briefing
                </p>
                <h3 className="mt-2 break-words text-2xl font-semibold">{normalizedSymbol}</h3>
                <p className="mt-2 break-words text-sm text-white/80">{tone.caption}</p>
              </div>
              <span
                className={`inline-flex shrink-0 items-center rounded-full px-3 py-1 text-xs font-semibold ${tone.chipClassName}`}
              >
                {analysis.decision}
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/70">스탠스</p>
                <p className="mt-2 text-3xl font-semibold">{analysis.decision}</p>
                <p className="mt-2 text-sm text-white/85">{tone.label}</p>
              </div>

              <div className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/70">추천 비중</p>
                <p className="mt-2 text-3xl font-semibold">{recommendedWeight}%</p>
                <p className="mt-2 text-sm text-white/85">리스크 조절을 반영한 제안치입니다.</p>
              </div>
            </div>

            <div className="rounded-2xl border border-white/15 bg-white/10 p-4 backdrop-blur">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-white/70">확신도</p>
                  <p className="mt-2 text-2xl font-semibold">{confidence}%</p>
                </div>
                <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${tone.chipClassName}`}>
                  실시간 추론 로그
                </span>
              </div>

              <div className="mt-4">
                <div className="h-3 w-full overflow-hidden rounded-full bg-white/20">
                  <div
                    className={`h-full rounded-full bg-gradient-to-r transition-[width] duration-500 ${tone.progressClassName}`}
                    style={{ width: `${confidence}%` }}
                  />
                </div>
                <div className="mt-2 flex items-center justify-between text-xs text-white/70">
                  <span>0</span>
                  <span>{syncStatus}</span>
                  <span>100</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-[24px] border border-gray-200 bg-gray-50 p-5 dark:border-gray-700 dark:bg-gray-900/60">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500 dark:text-gray-400">
              AI 판단 근거
            </p>
            <div
              className="relative mt-2 inline-flex items-center gap-2"
              onMouseEnter={() => setIsTooltipOpen(true)}
              onMouseLeave={() => setIsTooltipOpen(false)}
            >
              <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100">판단 근거 (XAI)</h3>
              <button
                type="button"
                aria-label="AI 판단 근거 데이터 출처"
                className="inline-flex h-5 w-5 cursor-help items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-500 dark:bg-gray-600 dark:text-gray-300"
              >
                i
              </button>

              {isTooltipOpen && (
                <div className="absolute left-0 top-full z-50 mt-2 min-w-[280px] rounded-xl border border-gray-200 bg-white p-4 shadow-xl dark:border-gray-700 dark:bg-gray-800">
                  <div className="space-y-3">
                    <div>
                      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">📊 기술적 지표</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        RSI, SMA20, EMA50, 볼린저밴드 등 1시간봉 기준 200개 캔들 데이터
                      </p>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">🧠 시장 심리</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Alternative.me Fear &amp; Greed Index 실시간 수치
                      </p>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">📰 글로벌 뉴스</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        CoinDesk Korea, TokenPost, 네이버 경제 등 RSS 실시간 피드
                      </p>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">💼 포트폴리오</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        업비트 실시간 잔고 및 보유/미보유 상태
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-2xl border border-gray-200 bg-white p-4 pr-3 dark:border-gray-700 dark:bg-gray-800">
            <p className="whitespace-pre-wrap break-words text-sm leading-7 text-gray-700 dark:text-gray-300">
              {analysis.reasoning}
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

export default AiInsightBriefing
