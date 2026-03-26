import { useState } from 'react'

type SettingsTabKey = 'bot' | 'schedule' | 'watchlist' | 'admin'

interface SettingsTabItem {
  key: SettingsTabKey
  label: string
  description: string
}

const SETTINGS_TABS: SettingsTabItem[] = [
  {
    key: 'bot',
    label: '트레이딩 봇 파라미터',
    description: '봇 전략 파라미터와 실행 조건을 조정하는 구역입니다.',
  },
  {
    key: 'schedule',
    label: '동적 스케줄링 동기화',
    description: '자동 실행 스케줄과 외부 동기화 작업을 관리하는 구역입니다.',
  },
  {
    key: 'watchlist',
    label: '관심 종목 집중 관리',
    description: '핵심 감시 종목과 우선순위를 구성하는 구역입니다.',
  },
  {
    key: 'admin',
    label: '시스템 어드민',
    description: '운영 상태, 관리자 설정, 유지보수 항목을 배치할 구역입니다.',
  },
]

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
          환경설정 전용 페이지 뼈대입니다. 좌측 메뉴에서 카테고리를 고르면 우측 작업 영역에 각 설정 모듈이 배치됩니다.
        </p>
      </section>

      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <div className="mb-4 border-b border-gray-200 pb-3 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">설정 카테고리</h2>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">좌측 탭 구조의 기본 뼈대입니다.</p>
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

        <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <div className="flex h-full min-h-[360px] flex-col justify-between gap-6">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-600 dark:text-sky-300">
                Active Module
              </p>
              <h2 className="mt-3 text-2xl font-semibold text-gray-900 dark:text-gray-100">{activeItem.label}</h2>
              <p className="mt-2 max-w-2xl text-sm text-gray-600 dark:text-gray-300">{activeItem.description}</p>
            </div>

            <div className="flex min-h-[260px] items-center justify-center rounded-2xl border border-dashed border-gray-300 bg-gray-50 px-6 text-center dark:border-gray-600 dark:bg-gray-700/30">
              <div>
                <p className="text-base font-semibold text-gray-900 dark:text-gray-100">
                  {activeItem.label} 설정 패널 준비 중
                </p>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  다음 단계에서 이 영역에 실제 입력 폼과 저장 로직이 연결됩니다.
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

export default SettingsPage
