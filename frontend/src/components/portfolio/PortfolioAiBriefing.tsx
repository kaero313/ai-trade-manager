import { Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { streamChatMessage } from '../../services/api'
import {
  PORTFOLIO_BODY_TEXT_CLASS_NAME,
  PORTFOLIO_CARD_CLASS_NAME,
  PORTFOLIO_PANEL_CLASS_NAME,
  PORTFOLIO_SECTION_LABEL_CLASS_NAME,
  PORTFOLIO_TITLE_CLASS_NAME,
} from './portfolioStyles'

interface PortfolioAiBriefingProps {
  sessionId: string | null
}

interface BriefingEntry {
  content: string
  errorMessage: string | null
}

const AUTO_BRIEFING_PROMPT =
  '현재 포트폴리오 요약과 시장 상황을 기반으로 간단한 투자 브리핑을 작성해줘. 3줄 이내로 핵심만 요약해줘.'

const BRIEFING_FALLBACK_TEXT =
  'AI 브리핑 응답을 받지 못했습니다. 현재 포트폴리오 카드, 자산 추이, 공포/탐욕 지수, 최근 AI 매매 기록을 먼저 확인한 뒤 다시 분석을 시도해주세요.'

const BRIEFING_FALLBACK_ERROR = 'AI 브리핑을 불러오지 못해 기본 안내를 표시합니다.'

function PortfolioAiBriefing({ sessionId }: PortfolioAiBriefingProps) {
  const [briefingEntries, setBriefingEntries] = useState<Record<string, BriefingEntry>>({})
  const [loadingSessionId, setLoadingSessionId] = useState<string | null>(null)
  const autoTriggeredSessionIdsRef = useRef<Set<string>>(new Set())
  const requestSequenceRef = useRef(0)
  const activeRequestIdRef = useRef(0)

  const currentEntry = sessionId ? briefingEntries[sessionId] : undefined
  const briefingText = currentEntry?.content ?? ''
  const errorMessage = currentEntry?.errorMessage ?? null
  const isLoading = Boolean(sessionId) && loadingSessionId === sessionId

  const runBriefingRequest = async (targetSessionId: string) => {
    const requestId = ++requestSequenceRef.current
    activeRequestIdRef.current = requestId
    setLoadingSessionId(targetSessionId)
    setBriefingEntries((current) => ({
      ...current,
      [targetSessionId]: {
        content: current[targetSessionId]?.content ?? '',
        errorMessage: null,
      },
    }))

    let finalAnswerContent = ''
    let hasFinalAnswer = false

    try {
      await streamChatMessage(
        targetSessionId,
        AUTO_BRIEFING_PROMPT,
        (streamEvent) => {
          if (activeRequestIdRef.current !== requestId) {
            return
          }

          if (streamEvent.type === 'final_answer') {
            hasFinalAnswer = true
            finalAnswerContent = String(streamEvent.content || '').trim()
          }
        },
        { timeoutMs: 45000 },
      )

      if (activeRequestIdRef.current !== requestId) {
        return
      }

      if (!hasFinalAnswer || !finalAnswerContent) {
        setBriefingEntries((current) => ({
          ...current,
          [targetSessionId]: {
            content: current[targetSessionId]?.content || BRIEFING_FALLBACK_TEXT,
            errorMessage: BRIEFING_FALLBACK_ERROR,
          },
        }))
        return
      }

      setBriefingEntries((current) => ({
        ...current,
        [targetSessionId]: {
          content: finalAnswerContent,
          errorMessage: null,
        },
      }))
    } catch {
      if (activeRequestIdRef.current !== requestId) {
        return
      }

      setBriefingEntries((current) => ({
        ...current,
        [targetSessionId]: {
          content: current[targetSessionId]?.content || BRIEFING_FALLBACK_TEXT,
          errorMessage: BRIEFING_FALLBACK_ERROR,
        },
      }))
    } finally {
      if (activeRequestIdRef.current === requestId) {
        setLoadingSessionId(null)
      }
    }
  }

  useEffect(() => {
    return () => {
      activeRequestIdRef.current += 1
    }
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setLoadingSessionId(null)
      return
    }

    if (autoTriggeredSessionIdsRef.current.has(sessionId)) {
      return
    }

    autoTriggeredSessionIdsRef.current.add(sessionId)
    void runBriefingRequest(sessionId)
  }, [sessionId])

  return (
    <section className={`${PORTFOLIO_CARD_CLASS_NAME} h-full overflow-hidden p-6`}>
      <div>
        <header className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className={PORTFOLIO_SECTION_LABEL_CLASS_NAME}>
              AI PORTFOLIO BRIEFING
            </p>
            <h2 className={PORTFOLIO_TITLE_CLASS_NAME}>
              🤖 AI 포트폴리오 브리핑
            </h2>
            <p className={PORTFOLIO_BODY_TEXT_CLASS_NAME}>
              현재 포트폴리오와 시장 상황을 AI가 짧게 요약합니다.
            </p>
          </div>

          <button
            type="button"
            onClick={() => {
              if (!sessionId || isLoading) {
                return
              }
              void runBriefingRequest(sessionId)
            }}
            disabled={!sessionId || isLoading}
            className="inline-flex shrink-0 items-center rounded-full border border-gray-200 bg-gray-50 px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-950"
          >
            다시 분석
          </button>
        </header>

        {!sessionId ? (
          <div className="rounded-xl border border-gray-200 bg-gray-50 px-5 py-6 text-sm font-medium text-gray-600 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-300">
            채팅 세션을 먼저 생성해주세요.
          </div>
        ) : null}

        {sessionId && isLoading ? (
          <div className={`${PORTFOLIO_PANEL_CLASS_NAME} flex min-h-[180px] items-center justify-center px-6 text-center`}>
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="h-8 w-8 animate-spin text-emerald-500 dark:text-emerald-300" />
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
                AI가 포트폴리오를 분석하고 있습니다...
              </p>
            </div>
          </div>
        ) : null}

        {sessionId && !isLoading && !briefingText && errorMessage ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-6 text-sm font-medium text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/12 dark:text-rose-200">
            {errorMessage}
          </div>
        ) : null}

        {sessionId && !isLoading && briefingText ? (
          <div className="space-y-4">
            {errorMessage ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/12 dark:text-rose-200">
                {errorMessage}
              </div>
            ) : null}

            <div className={`${PORTFOLIO_PANEL_CLASS_NAME} px-5 py-6`}>
              <p className="whitespace-pre-wrap break-words text-sm leading-7 text-gray-700 dark:text-gray-200">
                {briefingText}
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}

export default PortfolioAiBriefing
