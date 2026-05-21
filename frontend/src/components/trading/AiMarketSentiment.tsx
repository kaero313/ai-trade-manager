import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'

import { getMarketSentiment } from '../../services/api'

type SentimentTone = {
  badgeClassName: string
  dotClassName: string
  directionClassName: string
  directionSurfaceClassName: string
  label: string
  trendStrength: string
  volatilityWarning: string
  description: string
  chipLabel: string
  chipSubLabel: string
}

function clampScore(score: number): number {
  return Math.max(0, Math.min(100, score))
}

function formatUpdatedAt(value: string | undefined): string {
  if (!value) {
    return '-'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

function resolveClassificationLabel(classification: string | undefined): string {
  switch (String(classification ?? '').trim().toLowerCase()) {
    case 'extreme fear':
      return '극단적 공포'
    case 'fear':
      return '공포'
    case 'neutral':
      return '중립'
    case 'greed':
      return '탐욕'
    case 'extreme greed':
      return '극단적 탐욕'
    default:
      return classification && classification.trim().length > 0 ? classification : '중립'
  }
}

function resolveSentimentTone(score: number, classification: string | undefined): SentimentTone {
  const label = resolveClassificationLabel(classification)

  if (score <= 25) {
    return {
      badgeClassName:
        'border border-[#ffb4ab]/45 bg-[#0a0e14]/80 text-[#ffb4ab]',
      dotClassName: 'bg-[#ffb4ab]',
      directionClassName: 'text-[#ffb4ab]',
      directionSurfaceClassName: 'bg-[#ffb4ab]/10',
      label,
      trendStrength: '트렌드 약세',
      volatilityWarning: '매우 높음',
      description:
        '투매 심리가 짙은 구간입니다. 반등 시도와 추가 하락 가능성이 함께 열려 있어 분할 접근이 유리합니다.',
      chipLabel: '저가 매수 관찰',
      chipSubLabel: '변동성 확대 구간',
    }
  }

  if (score <= 45) {
    return {
      badgeClassName:
        'border border-[#ffb4ab]/45 bg-[#0a0e14]/80 text-[#ffb4ab]',
      dotClassName: 'bg-[#ffb4ab]',
      directionClassName: 'text-[#ffb4ab]',
      directionSurfaceClassName: 'bg-[#ffb4ab]/10',
      label,
      trendStrength: '트렌드 약세',
      volatilityWarning: '높음',
      description:
        '공포 심리가 우세한 구간입니다. 추세 반전 신호가 확인되기 전까지는 관망 또는 분할 진입이 적절합니다.',
      chipLabel: '방어적 포지션',
      chipSubLabel: '하락 심리 우세',
    }
  }

  if (score <= 55) {
    return {
      badgeClassName:
        'border border-[#ffe179]/40 bg-[#0a0e14]/80 text-[#ffe179]',
      dotClassName: 'bg-[#ffe179]',
      directionClassName: 'text-[#ffe179]',
      directionSurfaceClassName: 'bg-[#ffe179]/10',
      label,
      trendStrength: '트렌드 중립',
      volatilityWarning: '보통',
      description:
        '시장 방향성이 아직 뚜렷하지 않은 구간입니다. 추격 진입보다는 다음 방향 확인이 더 중요한 시점입니다.',
      chipLabel: '방향성 탐색',
      chipSubLabel: '균형 구간',
    }
  }

  if (score <= 74) {
    return {
      badgeClassName:
        'border border-[#77e2a8]/40 bg-[#0a0e14]/80 text-[#77e2a8]',
      dotClassName: 'bg-[#77e2a8]',
      directionClassName: 'text-[#77e2a8]',
      directionSurfaceClassName: 'bg-[#77e2a8]/10',
      label,
      trendStrength: '트렌드 강세',
      volatilityWarning: '주의',
      description:
        '매수 심리가 살아 있는 구간입니다. 추세는 우호적이지만 과열 진입 여부를 함께 점검해야 합니다.',
      chipLabel: '상승 심리 우세',
      chipSubLabel: '과열 진입 경계',
    }
  }

  return {
    badgeClassName:
      'border border-[#ffe179]/45 bg-[#0a0e14]/80 text-[#ffe179]',
    dotClassName: 'bg-[#ffe179]',
    directionClassName: 'text-[#ffe179]',
    directionSurfaceClassName: 'bg-[#ffe179]/10',
    label,
    trendStrength: '트렌드 과열',
    volatilityWarning: '매우 높음',
    description:
      '극단적 탐욕 구간입니다. 추세는 강하지만 단기 버블과 급격한 되돌림 가능성까지 함께 경계해야 합니다.',
    chipLabel: '익절 경계 강화',
    chipSubLabel: '과열 신호 우세',
  }
}

function SentimentInfoTooltip() {
  return (
    <span className="group relative inline-flex shrink-0">
      <span
        aria-label="시장 심리지수 점수 구간 가이드"
        className="inline-flex h-5 w-5 cursor-help items-center justify-center rounded-full text-[#849495] transition hover:bg-[#262a31] hover:text-[#dfe2eb]"
      >
        <Info className="h-4 w-4" />
      </span>
      <div className="absolute right-0 top-full z-50 mt-2 hidden w-max max-w-[240px] whitespace-normal break-words rounded-lg border border-[#3b494b]/80 bg-[#0a0e14] px-4 py-3 text-left text-xs leading-5 text-[#dfe2eb] group-hover:block">
        <p className="font-semibold">시장 심리지수 가이드</p>
        <div className="mt-2 space-y-1">
          <p>0~25: 극단적 공포 (바닥/매수 찬스)</p>
          <p>26~45: 공포 (하락/관망 우세)</p>
          <p>46~55: 중립 (시장 방향성 부재)</p>
          <p>56~74: 탐욕 (상승/매수 강세)</p>
          <p>75~100: 극단적 탐욕 (버블/익절 경고)</p>
        </div>
      </div>
    </span>
  )
}

function SentimentSkeleton() {
  return (
    <section className="quantum-card min-w-0 shrink-0 rounded-xl p-4 sm:p-5">
      <div className="h-full min-w-0">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 break-words">
            <div className="h-8 w-40 animate-pulse rounded bg-[#3b494b]/50" />
            <div className="mt-3 h-4 w-56 animate-pulse rounded bg-[#3b494b]/50" />
          </div>

          <div className="h-8 w-24 animate-pulse rounded-md bg-[#3b494b]/50" />
        </div>

        <div className="mt-5 flex min-w-0 flex-col gap-4">
          <div className="flex min-w-0 flex-col gap-4 xl:flex-row xl:items-stretch">
            <div className="quantum-panel min-w-0 flex-1 rounded-lg p-4">
              <div className="space-y-4">
                <div className="flex min-w-0 items-end justify-between gap-3">
                  <div className="min-w-0">
                    <div className="h-3 w-24 animate-pulse rounded bg-[#3b494b]/50" />
                    <div className="mt-3 h-9 w-20 animate-pulse rounded bg-[#3b494b]/50" />
                  </div>
                  <div className="min-w-[96px] text-right">
                    <div className="ml-auto h-3 w-20 animate-pulse rounded bg-[#3b494b]/50" />
                    <div className="mt-3 ml-auto h-7 w-16 animate-pulse rounded bg-[#3b494b]/50" />
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="pt-4">
                    <div className="h-3 w-full animate-pulse rounded-full bg-[#3b494b]/50" />
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="h-3 w-12 animate-pulse rounded bg-[#3b494b]/50" />
                    <div className="h-3 w-16 animate-pulse rounded bg-[#3b494b]/50" />
                  </div>
                  <div className="h-4 w-48 animate-pulse rounded bg-[#3b494b]/50" />
                </div>
              </div>
            </div>

            <div className="flex min-w-0 flex-col gap-3 sm:flex-row xl:w-[136px] xl:shrink-0 xl:flex-col">
              <article className="min-w-0 flex-1 rounded-lg bg-[#0a0e14]/75 p-3.5">
                <div className="h-3 w-20 animate-pulse rounded bg-[#00dbe9]/20" />
                <div className="mt-3 h-8 w-24 animate-pulse rounded bg-[#00dbe9]/20" />
              </article>

              <article className="min-w-0 flex-1 rounded-lg bg-[#0a0e14]/75 p-3.5">
                <div className="h-3 w-20 animate-pulse rounded bg-[#ffb4ab]/20" />
                <div className="mt-3 h-8 w-20 animate-pulse rounded bg-[#ffb4ab]/20" />
              </article>
            </div>
          </div>

          <div className="min-w-0 rounded-lg bg-[#0a0e14]/75 p-4">
            <div className="flex flex-wrap gap-2">
              <div className="h-6 w-24 animate-pulse rounded-md bg-[#3b494b]/50" />
              <div className="h-6 w-24 animate-pulse rounded-md bg-[#3b494b]/50" />
            </div>
            <div className="mt-4 space-y-2">
              <div className="h-4 w-full animate-pulse rounded bg-[#3b494b]/50" />
              <div className="h-4 w-5/6 animate-pulse rounded bg-[#3b494b]/50" />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function AiMarketSentiment() {
  const sentimentQuery = useQuery({
    queryKey: ['market-sentiment'],
    queryFn: getMarketSentiment,
    refetchInterval: 1000 * 60 * 5,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  const snapshot = sentimentQuery.data
  const shouldShowSkeleton = !snapshot && (sentimentQuery.isLoading || sentimentQuery.isError)

  if (shouldShowSkeleton) {
    return <SentimentSkeleton />
  }

  const sentimentScore = clampScore(snapshot?.score ?? 0)
  const sentimentTone = resolveSentimentTone(sentimentScore, snapshot?.classification)
  const updatedAtLabel = formatUpdatedAt(snapshot?.updated_at)
  const statusCopy = sentimentQuery.isError
    ? `업데이트: ${updatedAtLabel} · 새 데이터 연결 지연`
    : sentimentQuery.isFetching
      ? `업데이트: ${updatedAtLabel} · 새 데이터 확인 중...`
      : `업데이트: ${updatedAtLabel}`

  return (
    <section className="quantum-card min-w-0 shrink-0 rounded-xl p-4 sm:p-5">
      <div className="h-full min-w-0">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 break-words">
            <div className="flex min-w-0 items-start gap-2">
              <h2 className="break-words text-2xl font-bold text-[#dfe2eb]">
                시장 심리지수 {sentimentScore}
              </h2>
              <SentimentInfoTooltip />
            </div>
            <p className="mt-2 break-words text-sm text-[#849495]">{statusCopy}</p>
          </div>

          <span
            className={`inline-flex max-w-full items-center gap-2 break-words rounded-full px-3 py-1 text-xs font-bold ${sentimentTone.badgeClassName}`}
          >
            <span className={`h-2 w-2 rounded-full ${sentimentTone.dotClassName}`} />
            {sentimentTone.label}
          </span>
        </div>

        <div className="mt-5 flex min-w-0 flex-col gap-4">
          <div className="flex min-w-0 flex-col gap-4 xl:flex-row xl:items-stretch">
            <div className="quantum-panel min-w-0 flex-1 rounded-lg p-4">
              <div className="space-y-4">
                <div className="flex min-w-0 items-end justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#849495]">
                      현재 점수
                    </p>
                    <p className="mt-2 text-3xl font-black tracking-tight text-[#dfe2eb]">
                      {sentimentScore}
                    </p>
                  </div>
                  <div
                    className={`min-w-[96px] rounded-lg px-3 py-2 text-right ${sentimentTone.directionSurfaceClassName}`}
                  >
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#849495]">
                      시장 방향
                    </p>
                    <p
                      className={`mt-2 break-words text-xl font-black leading-tight ${sentimentTone.directionClassName}`}
                    >
                      {sentimentTone.label}
                    </p>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="relative w-full pt-4">
                    <div className="h-3 w-full rounded-full bg-[linear-gradient(90deg,#ffb4ab,#ffe179,#77e2a8,#00dbe9)]" />
                    <div
                      className="absolute top-0 -translate-x-1/2"
                      style={{ left: `${sentimentScore}%` }}
                    >
                      <span
                        className={`block h-3 w-3 rounded-full border-2 border-[#10141a] ${sentimentTone.dotClassName}`}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.18em] text-[#849495]">
                    <span>0 Fear</span>
                    <span>100 Greed</span>
                  </div>

                  <p className="text-sm text-[#b9cacb]">
                    공포에서 탐욕까지 현재 시장 심리 위치를 한 줄로 요약합니다.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex min-w-0 flex-col gap-3 sm:flex-row xl:w-[136px] xl:shrink-0 xl:flex-col">
              <article className="min-w-0 flex-1 rounded-lg bg-[#0a0e14]/75 p-3.5">
                <p className="min-w-0 break-words text-[11px] font-bold uppercase tracking-[0.16em] text-[#7df4ff]">
                  현재 트렌드 강도
                </p>
                <p className="mt-2 break-words text-lg font-bold leading-tight text-[#dfe2eb] xl:text-base">
                  {sentimentTone.trendStrength}
                </p>
              </article>

              <article className="min-w-0 flex-1 rounded-lg bg-[#0a0e14]/75 p-3.5">
                <p className="min-w-0 break-words text-[11px] font-bold uppercase tracking-[0.16em] text-[#ffb4ab]">
                  변동성 경고
                </p>
                <p className="mt-2 break-words text-lg font-bold leading-tight text-[#dfe2eb] xl:text-base">
                  {sentimentTone.volatilityWarning}
                </p>
              </article>
            </div>
          </div>

          <div className="min-w-0 overflow-hidden rounded-lg bg-[#0a0e14]/75 p-4 text-[#dfe2eb]">
            <div className="grid gap-2 sm:grid-cols-2">
              <span className="rounded-md bg-[#181c22]/90 px-3 py-2 text-xs font-bold text-[#7df4ff]">
                {sentimentTone.chipLabel}
              </span>
              <span className="rounded-md bg-[#181c22]/90 px-3 py-2 text-xs font-bold text-[#ffb4ab]">
                {sentimentTone.chipSubLabel}
              </span>
            </div>

            <p className="mt-4 break-words text-sm leading-6 text-[#dfe2eb]">
              {sentimentTone.description}
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

export default AiMarketSentiment
