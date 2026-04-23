import { Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { streamChatMessage } from '../../services/api'

interface PortfolioAiBriefingProps {
  sessionId: string | null
}

interface BriefingEntry {
  content: string
  errorMessage: string | null
}

const AUTO_BRIEFING_PROMPT =
  '현재 내 포트폴리오 요약과 시장 상황을 기반으로 간단한 투자 브리핑을 작성해줘. 3줄 이내로 핵심만 요약해.'

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
      await streamChatMessage(targetSessionId, AUTO_BRIEFING_PROMPT, (streamEvent) => {
        if (activeRequestIdRef.current !== requestId) {
          return
        }

        if (streamEvent.type === 'final_answer') {
          hasFinalAnswer = true
          finalAnswerContent = String(streamEvent.content || '').trim()
        }
      })

      if (activeRequestIdRef.current !== requestId) {
        return
      }

      if (!hasFinalAnswer || !finalAnswerContent) {
        setBriefingEntries((current) => ({
          ...current,
          [targetSessionId]: {
            content: current[targetSessionId]?.content ?? '',
            errorMessage: '브리핑을 불러오지 못했습니다.',
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
          content: current[targetSessionId]?.content ?? '',
          errorMessage: '브리핑을 불러오지 못했습니다.',
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
    <section className="relative h-full overflow-hidden rounded-[28px] border border-white/60 bg-white/70 p-6 shadow-[0_28px_90px_-36px_rgba(15,23,42,0.5)] backdrop-blur-xl transition-shadow duration-200 hover:shadow-[0_36px_110px_-44px_rgba(15,23,42,0.58)] dark:border-white/10 dark:bg-slate-900/60 dark:shadow-[0_28px_90px_-36px_rgba(2,6,23,0.95)] dark:hover:shadow-[0_36px_110px_-44px_rgba(2,6,23,1)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.16),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(59,130,246,0.12),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.34),rgba(255,255,255,0.05))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.18),_transparent_34%),radial-gradient(circle_at_bottom_right,_rgba(56,189,248,0.14),_transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.07),rgba(255,255,255,0.02))]" />
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-white/80 dark:bg-white/10" />

      <div className="relative">
        <header className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.24em] text-slate-500 dark:text-slate-400">
              AI PORTFOLIO BRIEFING
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">
              🤖 AI 포트폴리오 브리핑
            </h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
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
            className="inline-flex shrink-0 items-center rounded-full border border-slate-200/80 bg-white/80 px-4 py-2 text-sm font-semibold text-slate-700 shadow-[0_14px_28px_-24px_rgba(15,23,42,0.7)] transition hover:-translate-y-0.5 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900"
          >
            다시 분석
          </button>
        </header>

        {!sessionId ? (
          <div className="rounded-[24px] border border-slate-200/80 bg-slate-50/90 px-5 py-6 text-sm font-medium text-slate-600 shadow-[0_18px_40px_-30px_rgba(100,116,139,0.45)] dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-300">
            채팅 세션을 먼저 생성해주세요.
          </div>
        ) : null}

        {sessionId && isLoading ? (
          <div className="flex min-h-[180px] items-center justify-center rounded-[24px] border border-white/55 bg-white/45 px-6 text-center backdrop-blur dark:border-white/10 dark:bg-white/5">
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="h-8 w-8 animate-spin text-emerald-500 dark:text-emerald-300" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                AI가 포트폴리오를 분석하고 있습니다...
              </p>
            </div>
          </div>
        ) : null}

        {sessionId && !isLoading && !briefingText && errorMessage ? (
          <div className="rounded-[24px] border border-rose-200/80 bg-rose-50/90 px-5 py-6 text-sm font-medium text-rose-700 shadow-[0_18px_40px_-30px_rgba(225,29,72,0.65)] dark:border-rose-300/20 dark:bg-rose-500/12 dark:text-rose-200">
            브리핑을 불러오지 못했습니다.
          </div>
        ) : null}

        {sessionId && !isLoading && briefingText ? (
          <div className="space-y-4">
            {errorMessage ? (
              <div className="rounded-2xl border border-rose-200/80 bg-rose-50/90 px-4 py-3 text-sm font-medium text-rose-700 dark:border-rose-300/20 dark:bg-rose-500/12 dark:text-rose-200">
                브리핑을 불러오지 못했습니다.
              </div>
            ) : null}

            <div className="rounded-[24px] border border-white/55 bg-white/45 px-5 py-6 shadow-[0_18px_40px_-30px_rgba(15,23,42,0.45)] backdrop-blur dark:border-white/10 dark:bg-white/5">
              <p className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700 dark:text-slate-200">
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
