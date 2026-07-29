import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { useState } from 'react'

import { AI_PERFORMANCE_QUERY_KEY } from '../../hooks/useAIPerformance'
import { PORTFOLIO_SUMMARY_QUERY_KEY } from '../../hooks/usePortfolioSummary'
import { getBotStatus, getLatestAiAnalysis, runManualAiCycle } from '../../services/api'
import type { LatestAiAnalysis, ManualAiCycleResponse } from '../../services/api'

interface AiInsightBriefingProps {
  symbol: string | null
}

type ToneName = 'positive' | 'neutral' | 'danger' | 'muted'
type ManualCycleTone = 'positive' | 'neutral' | 'danger'

type ManualCycleFeedback = {
  message: string
  tone: ManualCycleTone
}

type DecisionTone = {
  tone: ToneName
  chipClassName: string
  progressClassName: string
  label: string
  caption: string
}

type ReasoningBucketKey = 'technical' | 'sentiment' | 'news' | 'policy'

type ReasoningBucket = {
  key: ReasoningBucketKey
  title: string
  label: string
  fallback: string
  markerPattern: RegExp
  keywords: RegExp
}

type ReasoningCard = {
  key: ReasoningBucketKey
  title: string
  label: string
  status: string
  body: string
  tone: ToneName
}

const TONE_STYLES: Record<
  ToneName,
  {
    chipClassName: string
    cardClassName: string
    labelClassName: string
    barClassName: string
  }
> = {
  positive: {
    chipClassName: 'bg-brand/10 text-brand-bright',
    cardClassName: 'border-brand/40 bg-brand/6',
    labelClassName: 'text-brand-bright',
    barClassName: 'bg-brand',
  },
  neutral: {
    chipClassName: 'bg-warning/10 text-warning',
    cardClassName: 'border-warning/35 bg-warning/6',
    labelClassName: 'text-warning',
    barClassName: 'bg-warning',
  },
  danger: {
    chipClassName: 'bg-status-danger/10 text-status-danger',
    cardClassName: 'border-status-danger/40 bg-status-danger/6',
    labelClassName: 'text-status-danger',
    barClassName: 'bg-status-danger',
  },
  muted: {
    chipClassName: 'bg-surface-highest/24 text-content-muted',
    cardClassName: 'border-border-strong/38 bg-surface-lowest/45',
    labelClassName: 'text-content-muted',
    barClassName: 'bg-surface-highest',
  },
}

const MANUAL_CYCLE_TONE_CLASS: Record<ManualCycleTone, string> = {
  positive: 'text-status-success',
  neutral: 'text-warning',
  danger: 'text-status-danger',
}

const REASONING_BUCKETS: ReasoningBucket[] = [
  {
    key: 'technical',
    title: '기술 지표',
    label: 'QUANT',
    fallback: '기술 지표 근거가 별도 분리되지 않았습니다.',
    markerPattern: /(?:기술\s*지표|기술지표|기술적\s*지표|정량\s*지표)\s*[:：]/gi,
    keywords: /(RSI|SMA|EMA|이동평균|볼린저|캔들|가격|지표|추세|저항|지지|과매수|과매도)/i,
  },
  {
    key: 'sentiment',
    title: '시장 심리',
    label: 'SENTIMENT',
    fallback: '시장 심리 근거가 별도 분리되지 않았습니다.',
    markerPattern: /(?:시장\s*심리|시장심리|공포\s*탐욕|투자\s*심리)\s*[:：]/gi,
    keywords: /(시장\s*심리|공포|탐욕|fear|greed|심리|불안|낙관|비관|중립)/i,
  },
  {
    key: 'news',
    title: '뉴스/RAG',
    label: 'RAG',
    fallback: '뉴스 또는 RAG 근거가 별도 분리되지 않았습니다.',
    markerPattern: /(?:뉴스\s*\/\s*RAG|뉴스|RAG|글로벌\s*뉴스|뉴스\s*문맥)\s*[:：]/gi,
    keywords: /(뉴스|RAG|기사|SEC|ETF|엔비디아|거시|금리|규제|채굴|토큰|거래소|보도)/i,
  },
  {
    key: 'policy',
    title: '안전 정책',
    label: 'POLICY',
    fallback: '안전 정책 근거가 별도 분리되지 않았습니다.',
    markerPattern: /(?:안전\s*정책|정책|리스크|포트폴리오|종합\s*판단|최종\s*판단|결론)\s*[:：]/gi,
    keywords: /(정책|리스크|안전|포트폴리오|비중|잔고|미보유|보유|제한|LOCKED|shadow|HOLD|BUY|SELL|관망)/i,
  },
]

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

function resolveManualCycleError(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (error.response?.status === 429) {
      return 'AI provider 사용량 제한으로 수동 갱신을 실행하지 못했습니다.'
    }
    if (error.message) {
      return error.message
    }
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return 'AI 수동 갱신 요청이 실패했습니다.'
}

function appendManualCycleDetail(
  label: string,
  result: ManualAiCycleResponse,
  includeSide = true,
): string {
  const sideLabel = includeSide && result.order_side ? ` · ${result.order_side}` : ''
  const detail = result.message.trim()
  const isLegacyExecutionMessage = /신규\s*체결\s*(?:있음|없음)/.test(detail)
  if (!detail || isLegacyExecutionMessage || detail === label || label.includes(detail)) {
    return `${label}${sideLabel}`
  }

  if (detail.includes(label)) {
    return `${detail}${sideLabel}`
  }

  return `${label}${sideLabel} · ${detail}`
}

function resolveManualCycleFeedback(result: ManualAiCycleResponse): ManualCycleFeedback {
  const submissionStatus = result.submission_status?.trim().toUpperCase() ?? ''
  const exchangeState = result.exchange_state?.trim().toLowerCase() ?? ''

  if (submissionStatus === 'REJECTED' || submissionStatus === 'FAILED') {
    return {
      message: appendManualCycleDetail('주문 거절', result),
      tone: 'danger',
    }
  }

  if (submissionStatus === 'ABANDONED') {
    return {
      message: appendManualCycleDetail('주문 제출 종료', result),
      tone: 'danger',
    }
  }

  if (['PREPARED', 'SUBMITTING', 'UNKNOWN'].includes(submissionStatus)) {
    return {
      message: appendManualCycleDetail('주문 확인 중', result),
      tone: 'neutral',
    }
  }

  if (submissionStatus === 'ACCEPTED') {
    if (exchangeState === 'wait' || exchangeState === 'watch') {
      return {
        message: appendManualCycleDetail('주문 접수 완료 · 거래소 처리 중', result),
        tone: 'neutral',
      }
    }

    if (exchangeState === 'done') {
      return {
        message: appendManualCycleDetail('주문 접수 완료 · 거래소 처리 완료', result),
        tone: 'neutral',
      }
    }

    if (exchangeState === 'cancel') {
      return {
        message: appendManualCycleDetail('주문 접수 완료 · 거래소 종료 상태 확인', result),
        tone: 'neutral',
      }
    }

    return {
      message: appendManualCycleDetail('주문 접수 완료', result),
      tone: 'neutral',
    }
  }

  if (typeof result.order_intent_id === 'number' || result.order_created) {
    return {
      message: appendManualCycleDetail('주문 상태 확인 중', result),
      tone: 'neutral',
    }
  }

  return {
    message: appendManualCycleDetail('분석 완료, 신규 주문 없음', result, false),
    tone: 'neutral',
  }
}

function cleanReasoningText(value: string): string {
  return value
    .replace(/\s+/g, ' ')
    .replace(/^[\s:：\-–—]+/, '')
    .trim()
}

function summarizeText(value: string, limit = 118): string {
  const cleaned = cleanReasoningText(value)
  if (cleaned.length <= limit) {
    return cleaned
  }

  return `${cleaned.slice(0, limit).trim()}...`
}

function splitIntoSentences(value: string): string[] {
  const cleaned = cleanReasoningText(value)
  if (!cleaned) {
    return []
  }

  return cleaned
    .split(/(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
}

function extractMarkedReasoning(reasoning: string): Partial<Record<ReasoningBucketKey, string>> {
  const markers: Array<{
    key: ReasoningBucketKey
    index: number
    length: number
  }> = []

  for (const bucket of REASONING_BUCKETS) {
    for (const match of reasoning.matchAll(bucket.markerPattern)) {
      markers.push({
        key: bucket.key,
        index: match.index ?? 0,
        length: match[0].length,
      })
    }
  }

  const uniqueMarkers = markers
    .sort((left, right) => left.index - right.index)
    .filter((marker, index, sorted) => index === 0 || marker.index !== sorted[index - 1].index)

  return uniqueMarkers.reduce<Partial<Record<ReasoningBucketKey, string>>>(
    (sections, marker, index) => {
      const nextMarker = uniqueMarkers[index + 1]
      const body = cleanReasoningText(
        reasoning.slice(marker.index + marker.length, nextMarker?.index ?? reasoning.length),
      )

      if (body) {
        sections[marker.key] = body
      }

      return sections
    },
    {},
  )
}

function findKeywordReasoning(reasoning: string, bucket: ReasoningBucket): string | null {
  const sentences = splitIntoSentences(reasoning)
  const matchedSentences = sentences.filter((sentence) => bucket.keywords.test(sentence))

  if (matchedSentences.length === 0) {
    return null
  }

  return matchedSentences.slice(0, 2).join(' ')
}

function resolveDecisionTone(decision: LatestAiAnalysis['decision']): DecisionTone {
  if (decision === 'BUY') {
    return {
      tone: 'positive',
      chipClassName: TONE_STYLES.positive.chipClassName,
      progressClassName: TONE_STYLES.positive.barClassName,
      label: '매수 우위',
      caption: '상승 여지가 더 크다고 판단했습니다.',
    }
  }

  if (decision === 'SELL') {
    return {
      tone: 'danger',
      chipClassName: TONE_STYLES.danger.chipClassName,
      progressClassName: TONE_STYLES.danger.barClassName,
      label: '매도 우위',
      caption: '리스크 회피와 차익 실현을 우선했습니다.',
    }
  }

  return {
    tone: 'neutral',
    chipClassName: TONE_STYLES.neutral.chipClassName,
    progressClassName: TONE_STYLES.neutral.barClassName,
    label: '관망 우위',
    caption: '방향성이 선명해질 때까지 보수적으로 접근합니다.',
  }
}

function resolveReasoningTone(body: string, hasRealBody: boolean): ToneName {
  if (!hasRealBody) {
    return 'muted'
  }

  if (
    /(오류|실패|에러|fallback|provider|부재|차단|제한|누락|못했습니다|없습니다|지연|위험|하락|매도|SELL|LOCKED|잠금|하회|아래)/i.test(
      body,
    )
  ) {
    return 'danger'
  }

  if (/(HOLD|관망|중립|대기|보수|확인|공포|불확실|완화|조절|혼재|shadow|review)/i.test(body)) {
    return 'neutral'
  }

  if (/(BUY|매수|상승|긍정|정상|통과|충족|강세|개선|active|synced)/i.test(body)) {
    return 'positive'
  }

  return 'muted'
}

function resolveReasoningStatus(tone: ToneName): string {
  if (tone === 'positive') {
    return '긍정'
  }

  if (tone === 'neutral') {
    return '관망'
  }

  if (tone === 'danger') {
    return '주의'
  }

  return '대기'
}

function buildReasoningCards(reasoning: string): ReasoningCard[] {
  const markedReasoning = extractMarkedReasoning(reasoning)

  return REASONING_BUCKETS.map((bucket) => {
    const extractedBody = markedReasoning[bucket.key] ?? findKeywordReasoning(reasoning, bucket)
    const hasRealBody = Boolean(extractedBody)
    const body = summarizeText(extractedBody ?? bucket.fallback)
    const tone = resolveReasoningTone(body, hasRealBody)

    return {
      key: bucket.key,
      title: bucket.title,
      label: bucket.label,
      status: resolveReasoningStatus(tone),
      body,
      tone,
    }
  })
}

function resolveReasoningHealth(reasoning: string, isError: boolean, isFetching: boolean): {
  label: string
  tone: ToneName
} {
  if (isError) {
    return { label: '동기화 지연', tone: 'danger' }
  }

  if (
    /(오류|실패|에러|fallback|provider|부재|차단|제한|누락|못했습니다|없습니다|지연)/i.test(
      reasoning,
    )
  ) {
    return { label: '제한', tone: 'danger' }
  }

  if (isFetching) {
    return { label: '동기화', tone: 'neutral' }
  }

  return { label: '정상', tone: 'positive' }
}

function InsightSkeleton() {
  return (
    <section className="quantum-card flex min-h-0 flex-col overflow-hidden rounded-xl">
      <div className="grid min-h-0 gap-5 p-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
        <div className="quantum-panel space-y-4 rounded-lg p-5 animate-pulse">
          <div className="h-4 w-28 rounded-full bg-surface-highest/50" />
          <div className="h-10 w-40 rounded-lg bg-surface-highest/50" />
          <div className="h-5 w-24 rounded-full bg-surface-highest/50" />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="h-24 rounded-lg bg-surface-highest/50" />
            <div className="h-24 rounded-lg bg-surface-highest/50" />
          </div>
          <div className="h-24 rounded-lg bg-surface-highest/50" />
        </div>

        <div className="quantum-panel rounded-lg p-5 animate-pulse">
          <div className="h-7 w-32 rounded-full bg-surface-highest/50" />
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="h-32 rounded-lg bg-surface-highest/50" />
            <div className="h-32 rounded-lg bg-surface-highest/50" />
            <div className="h-32 rounded-lg bg-surface-highest/50" />
            <div className="h-32 rounded-lg bg-surface-highest/50" />
          </div>
        </div>
      </div>
    </section>
  )
}

function EmptyInsightCard({
  title,
  description,
  action,
  feedback,
}: {
  title: string
  description: string
  action?: ReactNode
  feedback?: ReactNode
}) {
  return (
    <section className="quantum-card flex min-h-0 flex-col overflow-hidden rounded-xl">
      <div className="flex min-h-[220px] flex-col items-center justify-center gap-3 px-6 py-10 text-center">
        <h3 className="text-lg font-bold text-content">{title}</h3>
        <p className="max-w-xl break-words text-sm leading-6 text-content-muted">
          {description}
        </p>
        {action}
        {feedback}
      </div>
    </section>
  )
}

function AiInsightBriefing({ symbol }: AiInsightBriefingProps) {
  const normalizedSymbol = normalizeSymbol(symbol)
  const queryClient = useQueryClient()
  const [manualCycleMessage, setManualCycleMessage] = useState<string | null>(null)
  const [manualCycleTone, setManualCycleTone] = useState<ManualCycleTone>('neutral')
  const [manualCycleError, setManualCycleError] = useState<string | null>(null)

  const analysisQuery = useQuery({
    queryKey: ['latest-ai-analysis', normalizedSymbol],
    queryFn: () => getLatestAiAnalysis(normalizedSymbol as string),
    enabled: Boolean(normalizedSymbol),
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
    retry: false,
  })

  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 5000,
    placeholderData: (previousData) => previousData,
  })
  const tradingMode = botStatusQuery.data?.trading_mode
  const tradingModeAvailable =
    !botStatusQuery.isError &&
    (tradingMode === 'paper' || tradingMode === 'live') &&
    Number.isInteger(botStatusQuery.data?.trading_mode_version) &&
    (botStatusQuery.data?.trading_mode_version ?? 0) >= 1 &&
    botStatusQuery.data?.trading_mode_state_available === true &&
    botStatusQuery.data.trading_mode_mirror_consistent === true
  const paperTradeAllowed =
    tradingModeAvailable && tradingMode === 'paper' && botStatusQuery.data?.running === true
  const liveTradeAllowed =
    tradingModeAvailable &&
    tradingMode === 'live' &&
    botStatusQuery.data?.running === true &&
    botStatusQuery.data.live_order_state_available &&
    botStatusQuery.data.live_order_rollout_enabled &&
    botStatusQuery.data.live_order_mode === 'ARMED'
  const manualTradeAllowed = paperTradeAllowed || liveTradeAllowed

  const manualCycleMutation = useMutation({
    mutationFn: () => {
      if (!normalizedSymbol) {
        throw new Error('수동 갱신할 종목을 먼저 선택해 주세요.')
      }
      return runManualAiCycle(normalizedSymbol, manualTradeAllowed)
    },
    onSuccess: async (result) => {
      const resultFeedback = resolveManualCycleFeedback(result)
      setManualCycleError(null)
      setManualCycleMessage(resultFeedback.message)
      setManualCycleTone(resultFeedback.tone)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['latest-ai-analysis', result.symbol] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-orders'] }),
        queryClient.invalidateQueries({ queryKey: PORTFOLIO_SUMMARY_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: AI_PERFORMANCE_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: ['bot-status'] }),
        queryClient.invalidateQueries({ queryKey: ['live-order-gate'] }),
      ])
    },
    onError: (error) => {
      setManualCycleMessage(null)
      setManualCycleTone('danger')
      setManualCycleError(resolveManualCycleError(error))
    },
  })

  const handleManualCycle = () => {
    if (!normalizedSymbol || manualCycleMutation.isPending) {
      return
    }

    const shouldProceed = window.confirm(
      paperTradeAllowed
        ? '현재 종목 AI 분석을 즉시 실행하고, 조건 충족 시 PAPER 모의매매까지 평가합니다.'
        : liveTradeAllowed
          ? '현재 종목 AI 분석을 즉시 실행하고, 조건 충족 시 LIVE 매매 게이트까지 평가합니다.'
          : tradingModeAvailable && tradingMode === 'live'
            ? `현재 LIVE 실주문 Gate는 ${botStatusQuery.data?.live_order_mode ?? '확인 불가'}입니다. Gemini/AI 분석만 실행하고 주문은 생성하지 않습니다.`
            : tradingModeAvailable && tradingMode === 'paper'
              ? '현재 PAPER 런타임이 정지되어 있습니다. Gemini/AI 분석만 실행하고 모의주문은 생성하지 않습니다.'
            : '거래 모드를 안전하게 확인할 수 없습니다. Gemini/AI 분석만 실행하고 주문은 생성하지 않습니다.',
    )
    if (!shouldProceed) {
      return
    }

    setManualCycleMessage(null)
    setManualCycleTone('neutral')
    setManualCycleError(null)
    manualCycleMutation.mutate()
  }

  const manualCycleAction = (
    <button
      type="button"
      onClick={handleManualCycle}
      disabled={!normalizedSymbol || manualCycleMutation.isPending}
      className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-brand/35 bg-brand/10 px-3 py-2 text-xs font-semibold text-brand-bright transition-colors hover:bg-brand/18 disabled:cursor-not-allowed disabled:opacity-55"
    >
      {manualCycleMutation.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      ) : (
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
      )}
      {manualCycleMutation.isPending
        ? '실행 중'
        : paperTradeAllowed
          ? 'AI 분석 + 모의매매'
          : liveTradeAllowed
            ? 'AI 분석 + 실거래 평가'
            : 'AI 분석만 실행'}
    </button>
  )

  const manualCycleFeedback =
    manualCycleMessage || manualCycleError ? (
      <p
        role={manualCycleError ? 'alert' : 'status'}
        aria-live={manualCycleError ? 'assertive' : 'polite'}
        aria-atomic="true"
        className={`break-words rounded-lg bg-surface-lowest/75 px-3 py-2 text-xs font-semibold ${
          manualCycleError ? 'text-status-danger' : MANUAL_CYCLE_TONE_CLASS[manualCycleTone]
        }`}
      >
        {manualCycleError ?? manualCycleMessage}
      </p>
    ) : null

  if (!normalizedSymbol) {
    return (
      <EmptyInsightCard
        title="AI 브리핑 대기 중"
        description="종목을 선택하면 해당 코인에 대한 최신 AI 추론 로그를 실시간으로 표시합니다."
        action={manualCycleAction}
        feedback={manualCycleFeedback}
      />
    )
  }

  const analysis = analysisQuery.data
  const showSkeleton =
    !analysis &&
    !analysisQuery.isError &&
    (analysisQuery.isLoading || analysisQuery.isPending)

  if (showSkeleton) {
    return <InsightSkeleton />
  }

  if (!analysis) {
    if (analysisQuery.isError) {
      return (
        <EmptyInsightCard
          title={`${normalizedSymbol} AI 분석 조회 실패`}
          description="최신 AI 판단 근거를 불러오지 못했습니다. 백엔드 연결 또는 provider 상태가 회복되면 이 영역에 다시 표시됩니다."
          action={manualCycleAction}
          feedback={manualCycleFeedback}
        />
      )
    }

    return (
      <EmptyInsightCard
        title={`${normalizedSymbol} 최신 추론 없음`}
        description="아직 이 종목에 대해 저장된 AI 분석 로그가 없습니다. 백그라운드 추론 엔진이 다음 회차에 로그를 쌓으면 이 영역에 즉시 반영됩니다."
        action={manualCycleAction}
        feedback={manualCycleFeedback}
      />
    )
  }

  const tone = resolveDecisionTone(analysis.decision)
  const confidence = clampPercentage(analysis.confidence)
  const recommendedWeight = clampPercentage(analysis.recommended_weight)
  const reasoningCards = buildReasoningCards(analysis.reasoning)
  const reasoningHealth = resolveReasoningHealth(
    analysis.reasoning,
    analysisQuery.isError,
    analysisQuery.isFetching,
  )
  const healthStyle = TONE_STYLES[reasoningHealth.tone]

  let syncStatus = `업데이트 ${formatUpdatedAt(analysis.created_at)}`
  if (analysisQuery.isFetching) {
    syncStatus = `${syncStatus} · 최신 추론 동기화 중`
  } else if (analysisQuery.isError) {
    syncStatus = `${syncStatus} · 최근 데이터 기준 표시`
  }

  return (
    <section className="quantum-card flex min-h-0 flex-col overflow-hidden rounded-xl">
      <div className="grid min-h-0 gap-5 p-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
        <div className="quantum-panel relative overflow-hidden rounded-lg p-5 text-content">
          <div className="relative flex h-full min-h-0 flex-col gap-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="break-words text-2xl font-semibold">판단 요약</h3>
                <p className="mt-2 break-words text-sm leading-6 text-content-secondary">
                  {normalizedSymbol} · {tone.caption}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                {manualCycleAction}
                <span
                  className={`inline-flex shrink-0 items-center rounded-full px-3 py-1 text-xs font-semibold ${tone.chipClassName}`}
                >
                  {analysis.decision}
                </span>
              </div>
            </div>

            {manualCycleFeedback}

            <div className="grid gap-3 sm:grid-cols-2">
              <div className={`rounded-lg border-l-2 p-4 ${TONE_STYLES[tone.tone].cardClassName}`}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-content-muted">
                  스탠스
                </p>
                <p className="mt-2 text-3xl font-semibold">{analysis.decision}</p>
                <p className={`mt-2 text-sm font-semibold ${TONE_STYLES[tone.tone].labelClassName}`}>
                  {tone.label}
                </p>
              </div>

              <div className="rounded-lg border-l-2 border-brand-secondary/40 bg-surface-lowest/45 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-content-muted">
                  추천 비중
                </p>
                <p className="mt-2 text-3xl font-semibold">{recommendedWeight}%</p>
                <p className="mt-2 text-sm text-content-secondary">리스크 조절 반영</p>
              </div>
            </div>

            <div className="rounded-lg bg-surface-lowest/45 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-content-muted">
                    확신도
                  </p>
                  <p className="mt-2 text-2xl font-semibold">{confidence}%</p>
                </div>
                <span
                  className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${healthStyle.chipClassName}`}
                >
                  {reasoningHealth.label}
                </span>
              </div>

              <div className="mt-4">
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-highest/70">
                  <div
                    className={`h-full rounded-full transition-[width] duration-500 ${tone.progressClassName}`}
                    style={{ width: `${confidence}%` }}
                  />
                </div>
                <p className="mt-2 break-words text-xs leading-5 text-content-muted">{syncStatus}</p>
              </div>
            </div>
          </div>
        </div>

        <div className="quantum-panel flex min-h-0 flex-col overflow-hidden rounded-lg p-5">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-xl font-bold text-content">판단 근거</h3>
              <p className="mt-2 break-words text-sm leading-6 text-content-muted">
                긴 원문 대신 항목별 핵심 근거를 먼저 보여줍니다.
              </p>
            </div>
            <span className="shrink-0 rounded bg-brand/10 px-2.5 py-1 font-mono text-[10px] font-bold text-brand-bright">
              XAI MAP
            </span>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {reasoningCards.map((card) => {
              const style = TONE_STYLES[card.tone]

              return (
                <article
                  key={card.key}
                  className={`flex min-h-[138px] min-w-0 flex-col justify-between rounded-lg border-l-2 p-4 ${style.cardClassName}`}
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-bold text-content">{card.title}</p>
                      <p className="mt-1 font-mono text-[10px] font-bold tracking-[0.12em] text-content-muted">
                        {card.label}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 rounded px-2 py-1 text-[10px] font-bold ${style.chipClassName}`}
                    >
                      {card.status}
                    </span>
                  </div>
                  <p className="mt-3 break-words text-sm leading-6 text-content-secondary">{card.body}</p>
                </article>
              )
            })}
          </div>

        </div>
      </div>
    </section>
  )
}

export default AiInsightBriefing
