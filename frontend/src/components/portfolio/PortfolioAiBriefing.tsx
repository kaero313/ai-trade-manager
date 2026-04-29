import { Loader2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AIAnalysisItem,
  AssetItem,
  PortfolioSnapshotItem,
} from '../../services/portfolioService'
import { fetchPortfolioBriefing } from '../../services/portfolioService'
import {
  PORTFOLIO_BODY_TEXT_CLASS_NAME,
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
} from './portfolioStyles'

interface PortfolioAiBriefingProps {
  items: AssetItem[]
  snapshots: PortfolioSnapshotItem[]
  totalNetWorth: number
  totalPnl: number
  aiAnalysisMap: Record<string, AIAnalysisItem | null>
  isPortfolioLoading: boolean
}

interface BriefingEntry {
  content: string
  errorMessage: string | null
}

const BRIEFING_FALLBACK_ERROR =
  'AI provider가 일시적으로 응답하지 않아 현재 데이터 기반 요약을 표시합니다.'

function formatKrw(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(Math.abs(safeValue)))}`
}

function formatSignedKrw(value: number): string {
  if (value > 0) {
    return `+${formatKrw(value)}`
  }
  if (value < 0) {
    return `-${formatKrw(value)}`
  }
  return formatKrw(value)
}

function formatPercent(value: number): string {
  const safeValue = Number.isFinite(value) ? value : 0
  const sign = safeValue > 0 ? '+' : ''
  return `${sign}${safeValue.toFixed(2)}%`
}

function isKrwAsset(item: AssetItem): boolean {
  return String(item.currency || '').trim().toUpperCase() === 'KRW'
}

function buildAllocationSummary(items: AssetItem[]): string {
  const coinItems = items
    .filter((item) => !isKrwAsset(item) && item.total_value > 0)
    .sort((a, b) => b.total_value - a.total_value)

  if (coinItems.length === 0) {
    return 'KRW 외 보유 종목이 없어 신규 진입 전 현금 비중과 진입 기준 점검이 우선입니다.'
  }

  const totalCoinValue = coinItems.reduce((sum, item) => sum + item.total_value, 0)
  const topAssets = coinItems.slice(0, 3).map((item) => {
    const currency = item.currency.trim().toUpperCase()
    const weight = totalCoinValue > 0 ? (item.total_value / totalCoinValue) * 100 : 0
    return `${currency} ${weight.toFixed(1)}%`
  })

  return `보유 비중은 ${topAssets.join(', ')} 순으로 높아 상위 종목 변동성이 전체 성과를 좌우합니다.`
}

function buildAiDecisionSummary(aiAnalysisMap: Record<string, AIAnalysisItem | null>): string {
  const analyses = Object.values(aiAnalysisMap).filter((item): item is AIAnalysisItem => Boolean(item))

  if (analyses.length === 0) {
    return '최근 AI 판단 데이터가 없어 가격 흐름과 손익 변화를 먼저 확인해야 합니다.'
  }

  const decisionCounts = analyses.reduce<Record<AIAnalysisItem['decision'], number>>(
    (counts, item) => ({
      ...counts,
      [item.decision]: counts[item.decision] + 1,
    }),
    { BUY: 0, SELL: 0, HOLD: 0 },
  )
  const strongest = [...analyses].sort((a, b) => b.confidence - a.confidence)[0]
  const decisionLabel =
    strongest.decision === 'BUY' ? '매수' : strongest.decision === 'SELL' ? '매도' : '관망'

  return `최근 AI 판단은 매수 ${decisionCounts.BUY}건, 관망 ${decisionCounts.HOLD}건, 매도 ${decisionCounts.SELL}건이며 ${strongest.symbol} ${decisionLabel} 신뢰도가 가장 높습니다.`
}

function buildTrendSummary(snapshots: PortfolioSnapshotItem[]): string {
  const sortedSnapshots = [...snapshots].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )
  const firstSnapshot = sortedSnapshots[0]
  const latestSnapshot = sortedSnapshots[sortedSnapshots.length - 1]

  if (!firstSnapshot || !latestSnapshot) {
    return '기간 손익 데이터가 아직 부족해 현재 보유 종목의 개별 수익률을 기준으로 판단해야 합니다.'
  }

  const netWorthDelta =
    Number(latestSnapshot.total_net_worth || 0) - Number(firstSnapshot.total_net_worth || 0)

  return `스냅샷 기준 기간 손익은 ${formatSignedKrw(netWorthDelta)}로, 반등 여부보다 손실 종목의 회복 강도 확인이 중요합니다.`
}

function buildLocalBriefing({
  items,
  snapshots,
  totalNetWorth,
  totalPnl,
  aiAnalysisMap,
}: {
  items: AssetItem[]
  snapshots: PortfolioSnapshotItem[]
  totalNetWorth: number
  totalPnl: number
  aiAnalysisMap: Record<string, AIAnalysisItem | null>
}): string {
  const coinItems = items.filter((item) => !isKrwAsset(item))
  const worstHolding = [...coinItems].sort((a, b) => a.pnl_percentage - b.pnl_percentage)[0]
  const riskText = worstHolding
    ? `가장 약한 종목은 ${worstHolding.currency.toUpperCase()}(${formatPercent(worstHolding.pnl_percentage)})입니다.`
    : '현재 KRW 외 보유 종목이 없습니다.'

  return [
    `현재 총 자산은 ${formatKrw(totalNetWorth)}, 총 손익은 ${formatSignedKrw(totalPnl)}입니다. ${riskText}`,
    buildAllocationSummary(items),
    `${buildTrendSummary(snapshots)} ${buildAiDecisionSummary(aiAnalysisMap)}`,
  ].join('\n')
}

function normalizeBriefingText(rawText: string): string {
  const cleanedLines = rawText
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) =>
      line
        .trim()
        .replace(/^#{1,6}\s*/, '')
        .replace(/^[-*]\s+/, '')
        .replace(/^\d+[.)]\s+/, '')
        .replace(/^[^\w가-힣]*포트폴리오 분석 리포트\s*/i, '')
        .replace(/^portfolio briefing[:\s-]*(analysis\s*&\s*outlook)?\s*/i, '')
        .replace(/^[-*]\s+/, '')
        .replace(/^\*\*([^*]+?):\*\*\s*/, '$1: ')
        .replace(/^\*\*([^*]+)\*\*:\s*/, '$1: '),
    )
    .filter((line) => {
      if (!line) {
        return false
      }

      const normalizedLine = line.toLowerCase()
      const isHeading =
        line.length <= 80 &&
        (normalizedLine.includes('portfolio briefing') ||
          normalizedLine.includes('analysis & outlook') ||
          line.includes('포트폴리오 분석') ||
          line.includes('분석 리포트'))

      return !isHeading
    })

  return cleanedLines.slice(0, 3).join('\n').trim()
}

function PortfolioAiBriefing({
  items,
  snapshots,
  totalNetWorth,
  totalPnl,
  aiAnalysisMap,
  isPortfolioLoading,
}: PortfolioAiBriefingProps) {
  const [briefingEntry, setBriefingEntry] = useState<BriefingEntry | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const autoTriggeredRef = useRef(false)
  const requestSequenceRef = useRef(0)
  const activeRequestIdRef = useRef(0)

  const localBriefingText = buildLocalBriefing({
    items,
    snapshots,
    totalNetWorth,
    totalPnl,
    aiAnalysisMap,
  })
  const visibleBriefingText = briefingEntry?.content || localBriefingText

  const runBriefingRequest = useCallback(async () => {
    const requestId = ++requestSequenceRef.current
    activeRequestIdRef.current = requestId
    setIsLoading(true)
    setBriefingEntry((current) =>
      current
        ? {
            ...current,
            errorMessage: null,
          }
        : null,
    )

    try {
      const result = await fetchPortfolioBriefing()
      if (activeRequestIdRef.current !== requestId) {
        return
      }

      const report = normalizeBriefingText(String(result.report || ''))
      if (!report) {
        setBriefingEntry({
          content: '',
          errorMessage: BRIEFING_FALLBACK_ERROR,
        })
        return
      }

      setBriefingEntry({
        content: report,
        errorMessage: result.fallback ? BRIEFING_FALLBACK_ERROR : null,
      })
    } catch {
      if (activeRequestIdRef.current !== requestId) {
        return
      }

      setBriefingEntry({
        content: '',
        errorMessage: BRIEFING_FALLBACK_ERROR,
      })
    } finally {
      if (activeRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    return () => {
      activeRequestIdRef.current += 1
    }
  }, [])

  useEffect(() => {
    if (isPortfolioLoading || autoTriggeredRef.current) {
      return
    }

    autoTriggeredRef.current = true
    void runBriefingRequest()
  }, [isPortfolioLoading, runBriefingRequest])

  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} h-full overflow-hidden p-6`}>
      <div>
        <header className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
              AI PORTFOLIO BRIEFING
            </p>
            <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>
              AI 포트폴리오 브리핑
            </h2>
            <p className={PORTFOLIO_BODY_TEXT_CLASS_NAME}>
              현재 포트폴리오와 최근 손익 흐름을 AI가 짧게 요약합니다.
            </p>
          </div>

          <button
            type="button"
            onClick={() => {
              if (isPortfolioLoading || isLoading) {
                return
              }
              void runBriefingRequest()
            }}
            disabled={isPortfolioLoading || isLoading}
            className="inline-flex shrink-0 items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-950"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            다시 분석
          </button>
        </header>

        {isPortfolioLoading ? (
          <div className={`${PORTFOLIO_PANEL_CLASS_NAME} flex min-h-[180px] items-center justify-center px-6 text-center`}>
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="h-8 w-8 animate-spin text-emerald-500 dark:text-emerald-300" />
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
                포트폴리오 데이터를 불러오고 있습니다...
              </p>
            </div>
          </div>
        ) : null}

        {!isPortfolioLoading ? (
          <div className="space-y-4">
            {briefingEntry?.errorMessage ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-700 dark:border-amber-300/20 dark:bg-amber-500/12 dark:text-amber-200">
                {briefingEntry.errorMessage}
              </div>
            ) : null}

            {isLoading ? (
              <div className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 dark:border-emerald-300/20 dark:bg-emerald-500/12 dark:text-emerald-200">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                AI 브리핑 생성 중
              </div>
            ) : null}

            <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-5 py-6`}>
              <p className="whitespace-pre-wrap break-words text-sm leading-7 text-gray-700 dark:text-gray-200">
                {visibleBriefingText}
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default PortfolioAiBriefing
