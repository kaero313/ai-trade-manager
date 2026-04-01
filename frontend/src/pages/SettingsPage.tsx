import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { AlertTriangle, Loader2, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchFavorites, fetchTickers, removeFavorite, type FavoriteItem, type TickerItem } from '../api/markets'
import InfoTooltip from '../components/common/InfoTooltip'
import BotConfigForm from '../components/trading/BotConfigForm'
import { useSystemConfigs, useUpdateSystemConfigs } from '../hooks/useSystemConfigs'
import type { SystemConfigItem, SystemConfigUpdateItem } from '../services/api'

type SettingsTabKey = 'bot' | 'schedule' | 'watchlist' | 'admin'

interface SettingsTabItem {
  key: SettingsTabKey
  label: string
  description: string
}

interface ScheduleDraft {
  newsIntervalHours: string
  sentimentIntervalMinutes: string
  aiBriefingTime: string
  aiMinConfidenceTrade: string
  aiAnalysisMaxAgeMinutes: string
  aiCustomPersonaPrompt: string
}

interface NoticeState {
  type: 'success' | 'error' | 'info'
  message: string
}

const NEWS_INTERVAL_HOURS_KEY = 'news_interval_hours'
const SENTIMENT_INTERVAL_MINUTES_KEY = 'sentiment_interval_minutes'
const AI_BRIEFING_TIME_KEY = 'ai_briefing_time'
const AI_MIN_CONFIDENCE_TRADE_KEY = 'ai_min_confidence_trade'
const AI_ANALYSIS_MAX_AGE_MINUTES_KEY = 'ai_analysis_max_age_minutes'
const AI_CUSTOM_PERSONA_PROMPT_KEY = 'ai_custom_persona_prompt'

const PERSONA_PRESETS = [
  {
    key: 'aggressive-scalping',
    label: '🚀 공격형 단타',
    value:
      'HOLD는 최소화하고 항상 매수를 긍정적으로 고려하라. RSI가 40 이하이거나 뉴스에서 조금이라도 호재가 발견되면 확신도를 90 이상으로 평가하고 100% 비중의 BUY를 지시하라.',
  },
  {
    key: 'conservative-swing',
    label: '🐢 보수형 스윙',
    value:
      '절대 잃지 않는 장기 가치 투자를 지향한다. 조금이라도 애매하거나 이슈가 있으면 무조건 HOLD하라. 오직 RSI가 30 미만이면서 동시에 시장 공포(Fear/Greed)가 20 미만인 극단적 패닉셀 구간에서만 20% 분할 매수(BUY)를 지시해라.',
  },
  {
    key: 'default',
    label: '🔄 기본값 (순정)',
    value: '',
  },
] as const

const SETTINGS_TABS: SettingsTabItem[] = [
  {
    key: 'bot',
    label: '트레이딩 봇 파라미터',
    description: '봇 전략, 리스크, 운용 시간, 그리드 매매 설정을 통합 관리합니다.',
  },
  {
    key: 'schedule',
    label: '동적 스케줄링 동기화',
    description: '뉴스 수집과 심리지수 캐싱 주기를 화면에서 조정하고 즉시 반영합니다.',
  },
  {
    key: 'watchlist',
    label: '관심 종목 집중 관리',
    description: '감시 종목과 우선순위 구성을 위한 전용 설정 탭입니다.',
  },
  {
    key: 'admin',
    label: '시스템 어드민',
    description: '운영 점검, 관리자 설정, 유지보수용 도구를 담는 탭입니다.',
  },
]

const NEWS_INTERVAL_OPTIONS = ['1', '2', '4', '6', '8', '12']
const SENTIMENT_INTERVAL_OPTIONS = ['1', '5', '10', '15', '30']

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (Array.isArray(detail) && detail.length > 0) {
      return String(detail[0]?.msg ?? fallback)
    }
    if (error.message) {
      return error.message
    }
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function findConfigValue(items: SystemConfigItem[] | undefined, configKey: string, fallback: string): string {
  return items?.find((item) => item.config_key === configKey)?.config_value ?? fallback
}

function buildScheduleDraft(items: SystemConfigItem[] | undefined): ScheduleDraft {
  return {
    newsIntervalHours: findConfigValue(items, NEWS_INTERVAL_HOURS_KEY, '4'),
    sentimentIntervalMinutes: findConfigValue(items, SENTIMENT_INTERVAL_MINUTES_KEY, '5'),
    aiBriefingTime: findConfigValue(items, AI_BRIEFING_TIME_KEY, '08:30'),
    aiMinConfidenceTrade: findConfigValue(items, AI_MIN_CONFIDENCE_TRADE_KEY, '70'),
    aiAnalysisMaxAgeMinutes: findConfigValue(items, AI_ANALYSIS_MAX_AGE_MINUTES_KEY, '90'),
    aiCustomPersonaPrompt: findConfigValue(items, AI_CUSTOM_PERSONA_PROMPT_KEY, ''),
  }
}

function formatPrice(value: number | undefined): string {
  if (value === undefined) {
    return '-'
  }

  return `${new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: 0,
  }).format(value)} KRW`
}

function formatSignedPercent(rate: number | undefined): string {
  if (rate === undefined) {
    return '-'
  }

  const percent = rate * 100
  const sign = percent > 0 ? '+' : ''
  return `${sign}${percent.toFixed(2)}%`
}

function formatCreatedAt(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return '-'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

function resolveTickerTone(rate: number | undefined): string {
  if (rate === undefined || rate === 0) {
    return 'text-gray-600 dark:text-gray-300'
  }

  return rate > 0
    ? 'text-rose-600 dark:text-rose-300'
    : 'text-blue-600 dark:text-blue-300'
}
interface BulkDeleteResult {
  succeededSymbols: string[]
  failedSymbols: string[]
}

function BulkWatchlistPanel() {
  const queryClient = useQueryClient()
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [notice, setNotice] = useState<NoticeState | null>(null)

  const favoritesQuery = useQuery({
    queryKey: ['favorites'],
    queryFn: fetchFavorites,
  })

  const symbols = useMemo(() => {
    return (favoritesQuery.data ?? []).map((item) => item.symbol.toUpperCase())
  }, [favoritesQuery.data])

  const tickersQueryKey = useMemo(() => ['watchlist-tickers', symbols.join(',')], [symbols])

  const tickersQuery = useQuery({
    queryKey: tickersQueryKey,
    queryFn: () => fetchTickers(symbols),
    enabled: symbols.length > 0,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  useEffect(() => {
    setSelectedSymbols((current) => current.filter((symbol) => symbols.includes(symbol)))
  }, [symbols])

  const tickerMap = useMemo(() => {
    const map = new Map<string, TickerItem>()
    for (const row of tickersQuery.data ?? []) {
      map.set(row.symbol.toUpperCase(), row)
    }
    return map
  }, [tickersQuery.data])

  const bulkDeleteMutation = useMutation({
    mutationFn: async (symbolsToDelete: string[]): Promise<BulkDeleteResult> => {
      const results = await Promise.allSettled(symbolsToDelete.map((symbol) => removeFavorite(symbol)))
      const failedSymbols = results.flatMap((result, index) =>
        result.status === 'rejected' ? [symbolsToDelete[index]] : [],
      )
      const succeededSymbols = symbolsToDelete.filter((symbol) => !failedSymbols.includes(symbol))

      if (succeededSymbols.length > 0) {
        await queryClient.invalidateQueries({ queryKey: ['favorites'] })
        await queryClient.invalidateQueries({ queryKey: ['watchlist-tickers'] })
      }

      return { succeededSymbols, failedSymbols }
    },
  })

  const allSelected = symbols.length > 0 && selectedSymbols.length === symbols.length

  const handleToggleAll = () => {
    setSelectedSymbols(allSelected ? [] : symbols)
  }

  const handleToggleSymbol = (symbol: string) => {
    setSelectedSymbols((current) =>
      current.includes(symbol) ? current.filter((item) => item !== symbol) : [...current, symbol],
    )
  }

  const handleBulkDelete = async () => {
    if (selectedSymbols.length === 0) {
      setNotice({ type: 'info', message: '삭제할 관심 종목을 먼저 선택해 주세요.' })
      return
    }

    try {
      const result = await bulkDeleteMutation.mutateAsync(selectedSymbols)
      setSelectedSymbols(result.failedSymbols)

      if (result.failedSymbols.length === 0) {
        setNotice({
          type: 'success',
          message: `${result.succeededSymbols.length}개의 관심 종목을 일괄 삭제했습니다.`,
        })
        return
      }

      if (result.succeededSymbols.length === 0) {
        setNotice({
          type: 'error',
          message: '선택한 관심 종목을 삭제하지 못했습니다. 잠시 후 다시 시도해 주세요.',
        })
        return
      }

      setNotice({
        type: 'info',
        message: `${result.succeededSymbols.length}개 삭제, ${result.failedSymbols.length}개는 유지되었습니다.`,
      })
    } catch (error) {
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '관심 종목 일괄 삭제 중 오류가 발생했습니다.'),
      })
    }
  }

  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="border-b border-gray-200 pb-5 dark:border-gray-700">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-300">
          Bulk Watchlist Manager
        </p>
        <div className="mt-3 flex items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">관심 종목 집중 관리</h2>
          <InfoTooltip
            title="관심 종목 집중 관리"
            content="표에서 체크박스로 여러 종목을 선택해 한 번에 삭제할 수 있습니다. 종목명 링크를 누르면 대시보드 차트 화면으로 바로 이동합니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          현재 백엔드는 실현 수익률 대신 실시간 24시간 등락률을 제공합니다. 관심 종목이 많아져도 표로
          일괄 관리하고, 불필요한 심볼은 한 번에 정리할 수 있습니다.
        </p>
      </header>

      <div className="mt-6 space-y-5">
        <div className="flex flex-col gap-3 rounded-2xl border border-gray-200 bg-gray-50/80 px-4 py-4 dark:border-gray-700 dark:bg-gray-700/20 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-3 text-sm text-gray-700 dark:text-gray-200">
            <span className="rounded-full bg-white px-3 py-1 font-semibold shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
              총 {symbols.length}개 종목
            </span>
            <span className="rounded-full bg-white px-3 py-1 font-semibold shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
              선택 {selectedSymbols.length}개
            </span>
            <label className="inline-flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-200">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={handleToggleAll}
                disabled={symbols.length === 0 || bulkDeleteMutation.isPending}
                className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
              />
              전체 선택
            </label>
          </div>

          <button
            type="button"
            onClick={() => void handleBulkDelete()}
            disabled={selectedSymbols.length === 0 || bulkDeleteMutation.isPending}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:bg-rose-300"
          >
            {bulkDeleteMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            <span>{bulkDeleteMutation.isPending ? '삭제 중...' : '선택 종목 삭제'}</span>
          </button>
        </div>

        {notice && (
          <div
            className={`rounded-xl px-4 py-3 text-sm ${
              notice.type === 'success'
                ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200'
                : notice.type === 'info'
                  ? 'border border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-700/40 dark:text-gray-200'
                  : 'border border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200'
            }`}
          >
            {notice.message}
          </div>
        )}

        {favoritesQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-gray-500 dark:text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin" />
            관심 종목 목록을 불러오는 중입니다.
          </div>
        )}

        {favoritesQuery.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            {resolveErrorMessage(favoritesQuery.error, '관심 종목 목록을 불러오지 못했습니다.')}
          </div>
        )}

        {!favoritesQuery.isLoading && !favoritesQuery.isError && symbols.length === 0 && (
          <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 px-6 py-10 text-center dark:border-gray-600 dark:bg-gray-700/30">
            <p className="text-base font-semibold text-gray-900 dark:text-gray-100">아직 등록된 관심 종목이 없습니다.</p>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              대시보드 검색창의 별표 버튼으로 종목을 추가하면 여기에서 표 형태로 관리할 수 있습니다.
            </p>
          </div>
        )}

        {!favoritesQuery.isLoading && !favoritesQuery.isError && symbols.length > 0 && (
          <div className="overflow-hidden rounded-2xl border border-gray-200 dark:border-gray-700">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-700/40">
                  <tr>
                    <th className="w-14 px-4 py-3 text-left font-semibold text-gray-600 dark:text-gray-200">
                      선택
                    </th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600 dark:text-gray-200">종목명</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600 dark:text-gray-200">브로커</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600 dark:text-gray-200">현재가</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600 dark:text-gray-200">
                      24시간 등락률
                    </th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600 dark:text-gray-200">추가일자</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-700 dark:bg-gray-800">
                  {(favoritesQuery.data ?? []).map((favorite: FavoriteItem) => {
                    const symbol = favorite.symbol.toUpperCase()
                    const ticker = tickerMap.get(symbol)
                    const isSelected = selectedSymbols.includes(symbol)

                    return (
                      <tr
                        key={favorite.id}
                        className={
                          isSelected
                            ? 'bg-emerald-50/70 dark:bg-emerald-500/5'
                            : 'hover:bg-gray-50/80 dark:hover:bg-gray-700/30'
                        }
                      >
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleToggleSymbol(symbol)}
                            disabled={bulkDeleteMutation.isPending}
                            className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                          />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex min-w-[180px] flex-col">
                            <Link
                              to={`/?symbol=${encodeURIComponent(symbol)}`}
                              className="font-semibold text-slate-900 transition hover:text-emerald-600 dark:text-gray-100 dark:hover:text-emerald-300"
                            >
                              {symbol}
                            </Link>
                            <span className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                              대시보드 차트로 바로 이동
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">{favorite.broker}</td>
                        <td className="px-4 py-3 text-right font-medium text-gray-900 dark:text-gray-100">
                          {formatPrice(ticker?.current_price)}
                        </td>
                        <td className={`px-4 py-3 text-right font-semibold ${resolveTickerTone(ticker?.signed_change_rate)}`}>
                          {formatSignedPercent(ticker?.signed_change_rate)}
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                          {formatCreatedAt(favorite.created_at)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {tickersQuery.isError && (
              <div className="border-t border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">
                {resolveErrorMessage(tickersQuery.error, '일부 실시간 시세를 불러오지 못했습니다. 저장된 관심 종목 표는 계속 사용할 수 있습니다.')}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function DangerZonePanel() {
  return (
    <section className="rounded-2xl border border-rose-200 bg-rose-50/80 p-6 shadow-sm ring-1 ring-rose-100 dark:border-rose-500/20 dark:bg-rose-500/10 dark:ring-rose-500/10">
      <header className="border-b border-rose-200 pb-5 dark:border-rose-500/20">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-rose-600 text-white shadow-sm">
            <AlertTriangle className="h-5 w-5" />
          </span>
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-rose-600 dark:text-rose-300">
              Danger Zone
            </p>
            <h2 className="mt-1 text-2xl font-semibold text-rose-900 dark:text-rose-100">
              시스템 어드민
            </h2>
          </div>
        </div>
        <p className="mt-4 max-w-3xl text-sm leading-6 text-rose-800 dark:text-rose-100/90">
          시스템 장애나 백테스트 찌꺼기 누적 상황에 대비한 관리자용 정리 구역입니다. 현재는 UI 뼈대만
          선점해 두고, 실제 삭제 API는 후속 작업에서 연결됩니다.
        </p>
      </header>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {[
          {
            title: '백테스트 캐시 정리',
            description: '로컬 백테스트 산출물과 누적 캐시를 정리하는 버튼 자리입니다.',
          },
          {
            title: '시장 심리 캐시 초기화',
            description: '심리지수 캐시를 강제로 비우고 다시 수집하는 관리자용 버튼 자리입니다.',
          },
          {
            title: '뉴스 인덱스 정리',
            description: 'OpenSearch 뉴스 데이터 또는 실패한 적재 부산물을 초기화하는 버튼 자리입니다.',
          },
        ].map((item) => (
          <div
            key={item.title}
            className="rounded-2xl border border-rose-200 bg-white/80 p-4 dark:border-rose-500/20 dark:bg-gray-900/20"
          >
            <h3 className="text-base font-semibold text-rose-900 dark:text-rose-100">{item.title}</h3>
            <p className="mt-2 min-h-[72px] text-sm leading-6 text-rose-800/90 dark:text-rose-100/80">
              {item.description}
            </p>
            <button
              type="button"
              disabled
              className="mt-4 inline-flex w-full cursor-not-allowed items-center justify-center rounded-lg border border-rose-300 bg-rose-100 px-4 py-2 text-sm font-semibold text-rose-700 opacity-70 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-100"
            >
              준비 중
            </button>
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-xl border border-rose-200 bg-white/70 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-gray-900/20 dark:text-rose-100/90">
        실제 정리 버튼이 연결되면 복구가 어려운 데이터 삭제가 포함될 수 있으므로, 운영 환경에서는 권한과
        확인 절차를 함께 묶어야 합니다.
      </div>
    </section>
  )
}

function ScheduleSettingsPanel() {
  const systemConfigsQuery = useSystemConfigs()
  const updateSystemConfigsMutation = useUpdateSystemConfigs()
  const [draft, setDraft] = useState<ScheduleDraft>(() => buildScheduleDraft(undefined))
  const [notice, setNotice] = useState<NoticeState | null>(null)

  useEffect(() => {
    setDraft(buildScheduleDraft(systemConfigsQuery.data))
  }, [systemConfigsQuery.data])

  const handleSave = async () => {
    const current = buildScheduleDraft(systemConfigsQuery.data)
    const updates: SystemConfigUpdateItem[] = []

    if (draft.newsIntervalHours !== current.newsIntervalHours) {
      updates.push({
        config_key: NEWS_INTERVAL_HOURS_KEY,
        config_value: draft.newsIntervalHours,
      })
    }
    if (draft.sentimentIntervalMinutes !== current.sentimentIntervalMinutes) {
      updates.push({
        config_key: SENTIMENT_INTERVAL_MINUTES_KEY,
        config_value: draft.sentimentIntervalMinutes,
      })
    }
    if (draft.aiBriefingTime !== current.aiBriefingTime) {
      updates.push({
        config_key: AI_BRIEFING_TIME_KEY,
        config_value: draft.aiBriefingTime,
      })
    }
    if (draft.aiMinConfidenceTrade !== current.aiMinConfidenceTrade) {
      updates.push({
        config_key: AI_MIN_CONFIDENCE_TRADE_KEY,
        config_value: draft.aiMinConfidenceTrade,
      })
    }
    if (draft.aiAnalysisMaxAgeMinutes !== current.aiAnalysisMaxAgeMinutes) {
      updates.push({
        config_key: AI_ANALYSIS_MAX_AGE_MINUTES_KEY,
        config_value: draft.aiAnalysisMaxAgeMinutes,
      })
    }
    if (draft.aiCustomPersonaPrompt !== current.aiCustomPersonaPrompt) {
      updates.push({
        config_key: AI_CUSTOM_PERSONA_PROMPT_KEY,
        config_value: draft.aiCustomPersonaPrompt,
      })
    }

    if (updates.length === 0) {
      setNotice({ type: 'info', message: '변경된 시스템 주기 설정이 없습니다.' })
      return
    }

    try {
      await updateSystemConfigsMutation.mutateAsync(updates)
      setNotice({
        type: 'success',
        message: '시스템 주기가 저장되었고 백그라운드 워커에 즉시 반영되었습니다.',
      })
    } catch (error) {
      setNotice({
        type: 'error',
        message: resolveErrorMessage(error, '시스템 주기 설정을 저장하지 못했습니다.'),
      })
    }
  }

  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <header className="border-b border-gray-200 pb-5 dark:border-gray-700">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-600 dark:text-sky-300">
          Runtime Scheduler Control
        </p>
        <div className="mt-3 flex items-center gap-2">
          <h2 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
            동적 스케줄링 동기화
          </h2>
          <InfoTooltip
            title="동적 스케줄링 동기화"
            content="이 탭에서 저장한 값은 SystemConfig에 기록되고, 백엔드 스케줄러가 서버 재시작 없이 즉시 핫스왑됩니다."
          />
        </div>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          시황 뉴스 수집 주기, 심리지수 캐싱 주기, 일일 AI 브리핑 시각을 운영 중에도 조정할 수 있는
          런타임 제어 구역입니다.
        </p>
      </header>

      <div className="mt-6 space-y-6">
        {systemConfigsQuery.isLoading && (
          <div className="flex min-h-64 items-center justify-center gap-3 text-sm text-gray-500 dark:text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin" />
            시스템 주기 설정을 불러오는 중입니다.
          </div>
        )}

        {systemConfigsQuery.isError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            시스템 주기 설정을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
          </div>
        )}

        {!systemConfigsQuery.isLoading && !systemConfigsQuery.isError && (
          <>
            <div className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-4 text-sm text-sky-900 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-100">
              <p className="font-semibold">운영 안내</p>
              <p className="mt-2 leading-6">
                저장 버튼을 누르면 선택한 값이 DB에 기록되고, 백엔드 스케줄러가 같은 순간에 새 주기로
                다시 맞춰집니다. 주기를 너무 짧게 잡으면 외부 API 호출량이 커질 수 있으니 보수적으로
                조정하는 편이 안전합니다.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>시황 뉴스 수집 쿨타임 (시간)</span>
                  <InfoTooltip
                    title="시황 뉴스 수집 쿨타임"
                    content="CryptoPanic와 네이버 뉴스 ETL이 몇 시간마다 한 번씩 돌지 결정합니다. 값이 작을수록 최신성은 좋아지지만 외부 호출량이 늘어납니다."
                  />
                </span>
                <select
                  value={draft.newsIntervalHours}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, newsIntervalHours: event.target.value }))
                  }
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                >
                  {NEWS_INTERVAL_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}시간마다
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  현재 추천값은 4시간입니다.
                </p>
              </label>

              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>심리지수 캐싱 쿨타임 (분)</span>
                  <InfoTooltip
                    title="심리지수 캐싱 쿨타임"
                    content="Alternative.me 공포/탐욕 지수를 몇 분마다 새로 가져올지 정합니다. 무료 API 보호를 위해 과도하게 짧은 간격은 피하는 편이 안전합니다."
                  />
                </span>
                <select
                  value={draft.sentimentIntervalMinutes}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      sentimentIntervalMinutes: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                >
                  {SENTIMENT_INTERVAL_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}분마다
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  현재 추천값은 5분입니다.
                </p>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>AI 자율 체결 최소 확신도</span>
                  <InfoTooltip
                    title="AI 자율 체결 최소 확신도"
                    content="AI가 지시한 확신 점수(0~100)가 이 값보다 낮으면 실제 주문을 내지 않고 스킵합니다."
                  />
                </span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={draft.aiMinConfidenceTrade}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      aiMinConfidenceTrade: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  추천값: 70~80 (안전 지향시 높게 설정)
                </p>
              </label>

              <label className="block rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-700/30">
                <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                  <span>AI 분석 로그 유효 기간 (분)</span>
                  <InfoTooltip
                    title="AI 분석 로그 유효 기간 (분)"
                    content="스케줄러가 분석한 리포트가 생성된 지 몇 분 이내여야 주문을 실행할지 결정합니다."
                  />
                </span>
                <input
                  type="number"
                  min="1"
                  value={draft.aiAnalysisMaxAgeMinutes}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      aiAnalysisMaxAgeMinutes: event.target.value,
                    }))
                  }
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  추천값: 90분 (시장 급변 시 짧게 설정)
                </p>
              </label>
            </div>

            <label className="block rounded-2xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
              <span className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                <span>일일 AI 브리핑 실행 시각</span>
                <InfoTooltip
                  title="일일 AI 브리핑 실행 시각"
                  content="슬랙/메신저용 일일 브리핑 배치가 매일 몇 시에 동작할지 정합니다. 24시간 형식으로 설정되며 저장 즉시 다음 실행 시각이 다시 계산됩니다."
                />
              </span>
              <input
                type="time"
                value={draft.aiBriefingTime}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, aiBriefingTime: event.target.value }))
                }
                className="w-full max-w-[220px] rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:focus:border-blue-400 dark:focus:ring-blue-400"
              />
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                예: 오전 8시 30분 실행은 08:30 으로 설정합니다.
              </p>
            </label>

            <div className="rounded-2xl border border-violet-200 bg-violet-50/70 p-5 dark:border-violet-500/20 dark:bg-violet-500/10">
              <div className="flex flex-col gap-3 border-b border-violet-200 pb-4 dark:border-violet-500/20">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    AI 매매 철학 및 페르소나 주입 (God Mode)
                  </h3>
                  <InfoTooltip
                    title="AI 매매 철학 및 페르소나 주입"
                    content="여기에 입력한 텍스트는 SystemConfig의 ai_custom_persona_prompt로 저장되고, 백엔드 AI 분석 System Prompt의 맨 앞에 안전하게 덧붙여집니다. 코어 JSON 규칙은 그대로 유지되고, 사용자가 원하는 매매 철학만 추가 주입됩니다."
                  />
                </div>
                <p className="text-sm leading-6 text-gray-600 dark:text-gray-300">
                  AI가 어떤 성향으로 BUY, SELL, HOLD를 판단할지 자유롭게 적을 수 있는 전용 영역입니다. 아래 프리셋을 눌러 바로 채우거나,
                  직접 문장을 수정해 저장할 수 있습니다.
                </p>
                <div className="flex flex-wrap gap-2">
                  {PERSONA_PRESETS.map((preset) => (
                    <button
                      key={preset.key}
                      type="button"
                      onClick={() =>
                        setDraft((current) => ({
                          ...current,
                          aiCustomPersonaPrompt: preset.value,
                        }))
                      }
                      className="inline-flex items-center rounded-full border border-violet-200 bg-white px-3 py-1.5 text-xs font-semibold text-violet-700 transition hover:border-violet-300 hover:bg-violet-100 dark:border-violet-400/20 dark:bg-gray-800 dark:text-violet-200 dark:hover:border-violet-300/40 dark:hover:bg-violet-500/10"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4">
                <textarea
                  value={draft.aiCustomPersonaPrompt}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      aiCustomPersonaPrompt: event.target.value,
                    }))
                  }
                  placeholder="예: 손실 회피를 최우선으로 삼고, 뉴스 리스크가 있으면 HOLD를 우선하라. RSI와 심리지수, 뉴스 출처를 모두 인용해 reasoning을 작성하라."
                  className="min-h-[260px] w-full rounded-2xl border border-violet-200 bg-white px-4 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-300 dark:border-violet-400/20 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500 dark:focus:border-violet-300 dark:focus:ring-violet-400/30"
                />
                <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                  저장 시 기존 주기 설정과 함께 한 번에 PUT 요청으로 반영됩니다.
                </p>
              </div>
            </div>

            {notice && (
              <div
                className={`rounded-xl px-4 py-3 text-sm ${
                  notice.type === 'success'
                    ? 'border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200'
                    : notice.type === 'info'
                      ? 'border border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-700/40 dark:text-gray-200'
                      : 'border border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200'
                }`}
              >
                {notice.message}
              </div>
            )}

            <div className="flex items-center justify-between gap-4 border-t border-gray-200 pt-4 dark:border-gray-700">
              <div className="text-xs text-gray-500 dark:text-gray-400">
                저장 즉시 서버 메모리 상의 APScheduler 주기가 다시 등록됩니다.
              </div>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={updateSystemConfigsMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-70"
              >
                {updateSystemConfigsMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                <span>{updateSystemConfigsMutation.isPending ? '저장 중...' : '주기 설정 저장'}</span>
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTabKey>('bot')

  return (
    <div className="flex h-full min-h-0 flex-col gap-6">
      <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-300">
          System Settings
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
          시스템 설정
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-gray-600 dark:text-gray-300">
          트레이딩 전략과 시스템 배치 주기를 한 화면에서 다루는 전용 설정 공간입니다. 좌측 탭에서
          원하는 카테고리를 고르면 우측 본문에 상세 편집 화면이 열립니다.
        </p>
      </section>

      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <div className="mb-4 border-b border-gray-200 pb-3 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">설정 카테고리</h2>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              좌측 탭에서 조정할 모듈을 선택하세요.
            </p>
          </div>

          <nav className="flex flex-col gap-2">
            {SETTINGS_TABS.map((item, index) => {
              const isActive = item.key === activeTab

              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setActiveTab(item.key)}
                  className={`rounded-xl border px-4 py-3 text-left transition ${
                    isActive
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700 shadow-sm dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300'
                      : 'border-transparent bg-gray-50 text-gray-700 hover:border-gray-200 hover:bg-gray-100 dark:bg-gray-700/40 dark:text-gray-200 dark:hover:border-gray-600 dark:hover:bg-gray-700'
                  }`}
                >
                  <div className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-400 dark:text-gray-500">
                    {String(index + 1).padStart(2, '0')}
                  </div>
                  <div className="mt-1 text-sm font-semibold">{item.label}</div>
                </button>
              )
            })}
          </nav>
        </aside>

        <div className="min-h-0 overflow-y-auto pr-1">
          {activeTab === 'bot' && <BotConfigForm />}
          {activeTab === 'schedule' && <ScheduleSettingsPanel />}
          {activeTab === 'watchlist' && <BulkWatchlistPanel />}
          {activeTab === 'admin' && <DangerZonePanel />}
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
