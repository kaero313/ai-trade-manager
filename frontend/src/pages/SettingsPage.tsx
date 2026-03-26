import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

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
}

interface NoticeState {
  type: 'success' | 'error' | 'info'
  message: string
}

const NEWS_INTERVAL_HOURS_KEY = 'news_interval_hours'
const SENTIMENT_INTERVAL_MINUTES_KEY = 'sentiment_interval_minutes'
const AI_BRIEFING_TIME_KEY = 'ai_briefing_time'

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
  }
}

function PlaceholderCard({ title, description }: { title: string; description: string }) {
  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="flex min-h-[360px] items-center justify-center rounded-2xl border border-dashed border-gray-300 bg-gray-50 px-6 text-center dark:border-gray-600 dark:bg-gray-700/30">
        <div>
          <p className="text-base font-semibold text-gray-900 dark:text-gray-100">{title} 준비 중</p>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">{description}</p>
        </div>
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
  const activeItem = SETTINGS_TABS.find((item) => item.key === activeTab) ?? SETTINGS_TABS[0]

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
          {activeTab === 'watchlist' && (
            <PlaceholderCard title={activeItem.label} description={activeItem.description} />
          )}
          {activeTab === 'admin' && (
            <PlaceholderCard title={activeItem.label} description={activeItem.description} />
          )}
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
