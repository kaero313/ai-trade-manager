import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'

import { apiClient } from '../../services/api'

interface NewsItem {
  title: string
  summary: string
  link: string
}

interface NewsResponse {
  analysis_completed_at: string
  count: number
  items: NewsItem[]
}

type NewsContextTone = {
  label: string
  badgeClassName: string
  borderClassName: string
  textClassName: string
}

function resolveNewsContextTone(article: NewsItem, index: number): NewsContextTone {
  const corpus = `${article.title} ${article.summary}`.toLowerCase()
  const riskKeywords = [
    'risk',
    'down',
    'fall',
    'outage',
    'hack',
    'lawsuit',
    '하락',
    '급락',
    '위험',
    '리스크',
    '소송',
    '해킹',
    '장애',
    '규제',
  ]
  const positiveKeywords = [
    'positive',
    'rise',
    'up',
    'approve',
    'adoption',
    'institutional',
    '상승',
    '반등',
    '승인',
    '호재',
    '유입',
    '기관',
  ]

  if (riskKeywords.some((keyword) => corpus.includes(keyword))) {
    return {
      label: 'Risk',
      badgeClassName: 'bg-[#ffb4ab]/10 text-[#ffb4ab]',
      borderClassName: 'border-[#ffb4ab]',
      textClassName: 'text-[#ffb4ab]',
    }
  }

  if (positiveKeywords.some((keyword) => corpus.includes(keyword))) {
    return {
      label: 'Positive',
      badgeClassName: 'bg-[#77e2a8]/10 text-[#77e2a8]',
      borderClassName: 'border-[#77e2a8]',
      textClassName: 'text-[#77e2a8]',
    }
  }

  if (index === 0) {
    return {
      label: 'Watch',
      badgeClassName: 'bg-[#ffe179]/10 text-[#ffe179]',
      borderClassName: 'border-[#ffe179]',
      textClassName: 'text-[#ffe179]',
    }
  }

  return {
    label: 'Context',
    badgeClassName: 'bg-[#00dbe9]/10 text-[#7df4ff]',
    borderClassName: 'border-[#00dbe9]',
    textClassName: 'text-[#7df4ff]',
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
  return '뉴스 데이터를 불러오지 못했습니다.'
}

function formatUpdatedAt(value: string): string {
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

function compactSummary(article: NewsItem): string {
  const source = article.summary.trim() || article.title.trim()
  const firstSentence = source.split(/(?<=[.!?。！？])\s+/)[0] ?? source
  return firstSentence.length > 118 ? `${firstSentence.slice(0, 118)}...` : firstSentence
}

function AiNewsBoard() {
  const newsQuery = useQuery({
    queryKey: ['ai-news-board'],
    queryFn: async () => {
      const { data } = await apiClient.get<NewsResponse>('/news')
      return {
        analysis_completed_at: String(data.analysis_completed_at ?? ''),
        count: Number(data.count ?? 0),
        items: Array.isArray(data.items) ? data.items : [],
      }
    },
    refetchInterval: 1000 * 60 * 15,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  const articles = newsQuery.data?.items ?? []
  const articleCount = newsQuery.data?.count ?? articles.length
  const updatedAt = formatUpdatedAt(newsQuery.data?.analysis_completed_at ?? '')
  const visibleArticles = articles.slice(0, 3)
  const missingContextCount = articles.filter(
    (article) => !article.summary.trim() || !article.link.trim(),
  ).length
  const fallbackCount = newsQuery.isError && articles.length === 0 ? 1 : 0
  const statusLabel =
    newsQuery.isError && articles.length === 0
      ? 'ERROR'
      : missingContextCount > 0
        ? 'PARTIAL'
        : articles.length > 0
          ? 'SYNCED'
          : 'EMPTY'
  const statusClassName =
    statusLabel === 'SYNCED'
      ? 'bg-[#77e2a8]/10 text-[#77e2a8]'
      : statusLabel === 'PARTIAL'
        ? 'bg-[#ffe179]/10 text-[#ffe179]'
        : statusLabel === 'ERROR'
          ? 'bg-[#ffb4ab]/10 text-[#ffb4ab]'
          : 'bg-[#262a31] text-[#849495]'

  return (
    <section className="quantum-card flex h-full min-h-0 flex-col overflow-hidden rounded-xl p-4 sm:p-5">
      <header className="shrink-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="break-words text-lg font-bold text-[#dfe2eb]">
              뉴스 문맥 관측
            </h2>
            <p className="mt-2 text-xs text-[#849495]">업데이트: {updatedAt}</p>
          </div>
          <span className={`shrink-0 rounded-md px-2.5 py-1 text-[10px] font-bold ${statusClassName}`}>
            {statusLabel}
          </span>
        </div>
      </header>

      <div className="mt-4 grid shrink-0 grid-cols-3 gap-2">
        <div className="rounded-lg bg-[#77e2a8]/10 p-3 text-center">
          <p className="font-mono text-xl font-semibold text-[#77e2a8]">{articleCount}</p>
          <p className="mt-1 break-words text-[11px] text-[#849495]">real_news</p>
        </div>
        <div className="rounded-lg bg-[#ffe179]/10 p-3 text-center">
          <p className="font-mono text-xl font-semibold text-[#ffe179]">{fallbackCount}</p>
          <p className="mt-1 break-words text-[11px] text-[#849495]">fallback</p>
        </div>
        <div className="rounded-lg bg-[#ffb4ab]/10 p-3 text-center">
          <p className="font-mono text-xl font-semibold text-[#ffb4ab]">
            {missingContextCount}
          </p>
          <p className="mt-1 break-words text-[11px] text-[#849495]">context_gap</p>
        </div>
      </div>

      <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
        {newsQuery.isLoading && !newsQuery.data ? (
          <div className="space-y-3">
            <div className="h-16 animate-pulse rounded-lg bg-[#262a31]/50" />
            <div className="h-16 animate-pulse rounded-lg bg-[#262a31]/50" />
            <div className="h-16 animate-pulse rounded-lg bg-[#262a31]/50" />
          </div>
        ) : newsQuery.isError ? (
          <p className="rounded-lg bg-[#0a0e14]/80 px-4 py-3 text-sm font-semibold text-[#ffb4ab]">
            {resolveErrorMessage(newsQuery.error)}
          </p>
        ) : articles.length === 0 ? (
          <p className="rounded-lg bg-[#0a0e14]/80 px-4 py-3 text-sm leading-6 text-[#849495]">
            관측 가능한 뉴스 문맥이 없습니다. RAG 수집기가 새 문서를 확보하면 이 영역에 요약됩니다.
          </p>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <div className="space-y-4">
              {visibleArticles.map((article, index) => {
                const tone = resolveNewsContextTone(article, index)

                return (
                  <article
                    key={`${article.link}-${index}`}
                    className={`border-l-2 ${tone.borderClassName} pl-3`}
                  >
                    <div className="mb-1 flex items-center justify-between gap-3">
                      <span
                        className={`shrink-0 rounded px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] ${tone.badgeClassName}`}
                      >
                        {tone.label}
                      </span>
                      {article.link.trim() && (
                        <a
                          href={article.link}
                          target="_blank"
                          rel="noreferrer noopener"
                          className={`font-mono text-[10px] transition hover:text-[#dfe2eb] ${tone.textClassName}`}
                        >
                          SOURCE
                        </a>
                      )}
                    </div>
                    <p className="line-clamp-2 break-words text-sm font-bold leading-6 text-[#dfe2eb]">
                      {article.title}
                    </p>
                    <p className="mt-1 line-clamp-2 break-words text-sm leading-6 text-[#b9cacb]">
                      {compactSummary(article)}
                    </p>
                  </article>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

export default AiNewsBoard
