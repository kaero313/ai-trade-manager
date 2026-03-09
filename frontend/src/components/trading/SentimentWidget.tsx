import { isAxiosError } from 'axios'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { apiClient } from '../../services/api'

type RefreshIntervalMinutes = 15 | 30 | 60
type RefreshSource = 'initial' | 'manual' | 'auto'

interface SentimentArticle {
  title: string
  summary: string
  link: string
}

interface SentimentResponse {
  score: number
  summary: string[]
  news_articles: SentimentArticle[]
  updated_at: string
}

interface SentimentLevel {
  label: string
  badgeClassName: string
  description: string
}

const INTERVAL_OPTIONS: ReadonlyArray<RefreshIntervalMinutes> = [15, 30, 60]
const DEFAULT_SUMMARY = [
  '시장 요약을 불러오지 못했습니다.',
  '잠시 후 수동 갱신을 다시 시도해 주세요.',
  '리스크 관리 비중을 우선 점검하세요.',
]

function clampScore(rawScore: unknown): number {
  const parsed = Number(rawScore)
  if (!Number.isFinite(parsed)) {
    return 50
  }
  return Math.max(0, Math.min(100, Math.round(parsed)))
}

function normalizeSummary(rawSummary: unknown): string[] {
  const summary = Array.isArray(rawSummary)
    ? rawSummary.map((line) => String(line).trim()).filter(Boolean)
    : []

  while (summary.length < 3) {
    summary.push(DEFAULT_SUMMARY[summary.length])
  }

  return summary.slice(0, 3)
}

function formatUpdatedAt(value: string | null): string {
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
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

function resolveSentimentLevel(score: number): SentimentLevel {
  if (score >= 75) {
    return {
      label: '극단적 탐욕',
      badgeClassName: 'bg-rose-100 text-rose-700',
      description: '과열 구간입니다. 추격 매수에 주의하세요.',
    }
  }
  if (score >= 56) {
    return {
      label: '탐욕',
      badgeClassName: 'bg-orange-100 text-orange-700',
      description: '상승 기대가 높습니다. 분할 익절 전략을 점검하세요.',
    }
  }
  if (score >= 45) {
    return {
      label: '중립',
      badgeClassName: 'bg-slate-100 text-slate-700',
      description: '방향성이 약합니다. 진입/청산 기준을 유지하세요.',
    }
  }
  if (score >= 25) {
    return {
      label: '공포',
      badgeClassName: 'bg-sky-100 text-sky-700',
      description: '변동성 확대 구간입니다. 손절 규칙을 강화하세요.',
    }
  }
  return {
    label: '극단적 공포',
    badgeClassName: 'bg-blue-100 text-blue-700',
    description: '급락 리스크가 큽니다. 현금 비중을 우선 관리하세요.',
  }
}

function resolveErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (error.message) {
      return error.message
    }
  }
  return '심리 지수 데이터를 불러오지 못했습니다.'
}

function SentimentWidget() {
  const [data, setData] = useState<SentimentResponse | null>(null)
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState<boolean>(() => {
    const saved = localStorage.getItem('sentimentAutoRefresh')
    return saved ? JSON.parse(saved) : false
  })
  const [refreshIntervalMinutes, setRefreshIntervalMinutes] = useState<RefreshIntervalMinutes>(() => {
    const saved = localStorage.getItem('sentimentRefreshInterval')
    return saved ? (JSON.parse(saved) as RefreshIntervalMinutes) : 15
  })
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    localStorage.setItem('sentimentAutoRefresh', JSON.stringify(autoRefreshEnabled))
  }, [autoRefreshEnabled])

  useEffect(() => {
    localStorage.setItem('sentimentRefreshInterval', JSON.stringify(refreshIntervalMinutes))
  }, [refreshIntervalMinutes])

  const mountedRef = useRef(true)
  const inFlightRef = useRef(false)

  const loadSentiment = useCallback(async (forceRefresh: boolean, source: RefreshSource) => {
    if (inFlightRef.current) {
      return
    }

    inFlightRef.current = true
    if (source === 'initial') {
      setIsInitialLoading(true)
    } else {
      setIsRefreshing(true)
    }

    try {
      const { data: response } = await apiClient.get<SentimentResponse>('/news/sentiment', {
        params: { force_refresh: forceRefresh },
      })

      if (!mountedRef.current) {
        return
      }

      const normalized: SentimentResponse = {
        score: clampScore(response.score),
        summary: normalizeSummary(response.summary),
        news_articles: Array.isArray(response.news_articles) ? response.news_articles : [],
        updated_at: String(response.updated_at ?? ''),
      }
      setData(normalized)
      setErrorMessage(null)
    } catch (error) {
      if (!mountedRef.current) {
        return
      }
      setErrorMessage(resolveErrorMessage(error))
    } finally {
      inFlightRef.current = false
      if (mountedRef.current) {
        if (source === 'initial') {
          setIsInitialLoading(false)
        }
        setIsRefreshing(false)
      }
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void loadSentiment(false, 'initial')

    return () => {
      mountedRef.current = false
    }
  }, [loadSentiment])

  useEffect(() => {
    if (!autoRefreshEnabled) {
      return
    }

    const intervalMs = refreshIntervalMinutes * 60 * 1000
    const intervalId = window.setInterval(() => {
      void loadSentiment(false, 'auto')
    }, intervalMs)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [autoRefreshEnabled, refreshIntervalMinutes, loadSentiment])

  const handleManualRefresh = () => {
    void loadSentiment(true, 'manual')
  }

  const score = data?.score ?? 0
  const summaryLines = data?.summary ?? DEFAULT_SUMMARY
  const updatedAtText = formatUpdatedAt(data?.updated_at ?? null)
  const newsCount = data?.news_articles.length ?? 0
  const level = useMemo(() => resolveSentimentLevel(score), [score])

  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <header className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">AI 시장 심리 지수</h2>
        <p className="mt-1 text-sm text-slate-500">탐욕/공포 분위기와 핵심 뉴스 요약</p>
      </header>

      {isInitialLoading && !data ? (
        <div className="space-y-3">
          <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200" />
          <div className="h-3 w-full animate-pulse rounded bg-slate-200" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-slate-200" />
          <div className="h-3 w-4/6 animate-pulse rounded bg-slate-200" />
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="mb-2 flex items-end justify-between">
              <p className="text-3xl font-bold text-slate-900">{score}</p>
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${level.badgeClassName}`}>
                {level.label}
              </span>
            </div>
            <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-gradient-to-r from-blue-500 via-violet-500 via-orange-400 to-rose-500 transition-all duration-500"
                style={{ width: `${score}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-slate-600">{level.description}</p>
          </div>

          <div className="rounded-xl bg-slate-50 p-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">요약 3줄</h3>
            <ul className="space-y-1.5 text-sm text-slate-700">
              {summaryLines.map((line, index) => (
                <li key={`${line}-${index}`} className="flex gap-2">
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">
                    {index + 1}
                  </span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-2 text-xs text-slate-500">
            <p>기준 기사: {newsCount}건</p>
            <p>업데이트: {updatedAtText}</p>
          </div>
        </div>
      )}

      <div className="mt-5 border-t border-slate-200 pt-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-700">자동 갱신</span>
          <label className="relative inline-flex cursor-pointer items-center">
            <input
              type="checkbox"
              className="peer sr-only"
              checked={autoRefreshEnabled}
              onChange={(event) => setAutoRefreshEnabled(event.target.checked)}
              disabled={isRefreshing}
            />
            <span className="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-emerald-500 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-emerald-200 peer-checked:after:translate-x-full after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all" />
          </label>
        </div>

        <div className="mb-3">
          <label htmlFor="refresh-interval" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600">
            갱신 주기
          </label>
          <select
            id="refresh-interval"
            value={refreshIntervalMinutes}
            onChange={(event) => setRefreshIntervalMinutes(Number(event.target.value) as RefreshIntervalMinutes)}
            disabled={!autoRefreshEnabled || isRefreshing}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:bg-slate-100"
          >
            {INTERVAL_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}분
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          onClick={handleManualRefresh}
          disabled={isRefreshing}
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isRefreshing ? '갱신 중...' : '수동 갱신'}
        </button>

        {errorMessage && (
          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {errorMessage}
          </p>
        )}
      </div>
    </aside>
  )
}

export default SentimentWidget
