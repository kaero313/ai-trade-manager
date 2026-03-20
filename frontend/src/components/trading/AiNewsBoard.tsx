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

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="shrink-0 border-b border-gray-200 px-4 py-4 dark:border-gray-700">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-sky-600 dark:text-sky-300">
              Global News
            </p>
            <h2 className="mt-2 break-words text-lg font-bold text-gray-900 dark:text-gray-100">
              글로벌 시황 뉴스
            </h2>
          </div>
          <span className="shrink-0 rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700 ring-1 ring-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/20">
            {articleCount}건
          </span>
        </div>
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">업데이트: {updatedAt}</p>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-4 py-4">
        {newsQuery.isLoading && !newsQuery.data ? (
          <div className="space-y-3">
            <div className="h-4 w-1/2 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
            <div className="h-20 animate-pulse rounded-xl bg-gray-100 dark:bg-gray-700/50" />
            <div className="h-20 animate-pulse rounded-xl bg-gray-100 dark:bg-gray-700/50" />
          </div>
        ) : newsQuery.isError ? (
          <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
            {resolveErrorMessage(newsQuery.error)}
          </p>
        ) : articles.length === 0 ? (
          <p className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-700/40 dark:text-gray-300">
            표시할 글로벌 시황 뉴스가 없습니다.
          </p>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <div className="space-y-3">
              {articles.map((article, index) => (
                <article
                  key={`${article.link}-${index}`}
                  className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-700/40"
                >
                  <a
                    href={article.link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="block text-sm font-semibold leading-6 text-gray-900 transition hover:text-sky-600 dark:text-gray-100 dark:hover:text-sky-300"
                  >
                    {article.title}
                  </a>
                  <p className="mt-2 line-clamp-3 text-sm leading-6 text-gray-600 dark:text-gray-300">
                    {article.summary}
                  </p>
                </article>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

export default AiNewsBoard
