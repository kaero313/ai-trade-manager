import { AlertTriangle, Cloud, DatabaseZap, Loader2, Radio, RefreshCw, WalletCards } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import PortfolioAiBriefing from '../components/portfolio/PortfolioAiBriefing'
import PortfolioAllocationChart from '../components/portfolio/PortfolioAllocationChart'
import PortfolioHoldingsTable from '../components/portfolio/PortfolioHoldingsTable'
import PortfolioMiniChat from '../components/portfolio/PortfolioMiniChat'
import PortfolioPeriodPnlChart from '../components/portfolio/PortfolioPeriodPnlChart'
import PortfolioSummaryCard from '../components/portfolio/PortfolioSummaryCard'
import { usePortfolioSummary } from '../hooks/usePortfolioSummary'
import { createChatSession } from '../services/api'
import {
  fetchLatestAnalysisBatch,
  fetchPortfolioSnapshots,
} from '../services/portfolioService'
import type {
  AIAnalysisItem,
  AssetItem,
  PortfolioSnapshotItem,
} from '../services/portfolioService'
import {
  resolvePortfolioDataState,
  resolvePortfolioUnavailableMessage,
  type PortfolioDataState,
} from './portfolioDataState'

function buildPortfolioSymbols(items: AssetItem[]): string[] {
  const symbols = items
    .map((item) => String(item.currency || '').trim().toUpperCase())
    .filter((currency) => currency.length > 0 && currency !== 'KRW')
    .map((currency) => `KRW-${currency}`)

  return Array.from(new Set(symbols))
}

function isKrwAsset(item: AssetItem): boolean {
  return String(item.currency || '').trim().toUpperCase() === 'KRW'
}

function formatUpdatedAt(value: string | null): string {
  if (!value) {
    return '관측 시각 없음'
  }

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return '관측 시각 확인 불가'
  }

  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(parsed)
}

function resolveStatePresentation(state: PortfolioDataState) {
  if (state.kind === 'live') {
    return {
      icon: Radio,
      label: 'LIVE',
      badgeClassName: 'border-border-strong bg-surface-high text-brand-bright',
      description: 'Upbit 계좌에서 최신 자산 정보를 확인했습니다.',
    }
  }
  if (state.kind === 'snapshot') {
    return {
      icon: Cloud,
      label: 'SNAPSHOT',
      badgeClassName: 'border-border-strong bg-surface-high text-warning',
      description: '실시간 조회 대신 마지막으로 확인된 스냅샷을 표시합니다.',
    }
  }
  if (state.kind === 'cached-refetch-error') {
    return {
      icon: DatabaseZap,
      label: 'STALE',
      badgeClassName: 'border-border-strong bg-surface-high text-warning',
      description: '새로고침에 실패해 마지막으로 확인된 수치를 유지합니다.',
    }
  }
  if (state.kind === 'loading') {
    return {
      icon: Loader2,
      label: 'LOADING',
      badgeClassName: 'border-border-subtle bg-surface-high text-content-secondary',
      description: '계좌 정보를 안전하게 확인하고 있습니다.',
    }
  }
  if (state.kind === 'empty') {
    return {
      icon: WalletCards,
      label: 'EMPTY',
      badgeClassName: 'border-border-strong bg-surface-high text-warning',
      description: resolvePortfolioUnavailableMessage(state),
    }
  }
  return {
    icon: AlertTriangle,
    label: 'UNAVAILABLE',
    badgeClassName: 'border-border-strong bg-surface-high text-status-danger',
    description: resolvePortfolioUnavailableMessage(state),
  }
}

function PortfolioStateBanner({ state }: { state: PortfolioDataState }) {
  const presentation = resolveStatePresentation(state)
  const StateIcon = presentation.icon
  const showBanner = state.kind !== 'live'

  if (!showBanner) {
    return null
  }

  return (
    <div
      role={state.kind === 'hard-error' ? 'alert' : 'status'}
      className="flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface-low px-4 py-4 sm:flex-row sm:items-start sm:justify-between"
    >
      <div className="flex min-w-0 items-start gap-3">
        <StateIcon
          className={`mt-0.5 h-5 w-5 shrink-0 ${state.kind === 'loading' ? 'animate-spin' : ''}`}
          aria-hidden="true"
        />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-content">{presentation.description}</p>
          {state.errorCode ? (
            <p className="mt-1 break-words font-mono text-xs text-content-muted">
              오류: {state.errorCode}
            </p>
          ) : null}
        </div>
      </div>
      {state.updatedAt ? (
        <p className="shrink-0 text-xs text-content-secondary">
          마지막 관측 {formatUpdatedAt(state.updatedAt)}
        </p>
      ) : null}
    </div>
  )
}

function PortfolioUnavailablePanel({ state }: { state: PortfolioDataState }) {
  const presentation = resolveStatePresentation(state)
  const StateIcon = presentation.icon

  return (
    <section className="rounded-2xl border border-border-subtle bg-surface px-6 py-12 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-high text-content-secondary">
        <StateIcon
          className={`h-7 w-7 ${state.kind === 'loading' ? 'animate-spin' : ''}`}
          aria-hidden="true"
        />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-content">
        {state.kind === 'loading' ? '포트폴리오를 불러오는 중입니다' : '포트폴리오 금액을 표시할 수 없습니다'}
      </h2>
      <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-content-secondary">
        {state.kind === 'loading'
          ? '조회가 끝날 때까지 자산 금액과 AI 기능을 안전하게 숨깁니다.'
          : resolvePortfolioUnavailableMessage(state)}
      </p>
      <p className="mt-4 text-xs font-medium text-content-muted">
        조회 불가 상태를 정상 ₩0 포트폴리오로 대체하지 않습니다.
      </p>
    </section>
  )
}

function PortfolioPage() {
  const portfolioSummaryQuery = usePortfolioSummary()
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotItem[]>([])
  const [aiAnalysisMap, setAiAnalysisMap] = useState<Record<string, AIAnalysisItem | null>>({})
  const [isSnapshotsLoading, setIsSnapshotsLoading] = useState(true)
  const [snapshotsError, setSnapshotsError] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  const portfolioState = resolvePortfolioDataState({
    data: portfolioSummaryQuery.data,
    error: portfolioSummaryQuery.error,
    isError: portfolioSummaryQuery.isError,
    isLoading: portfolioSummaryQuery.isLoading,
    isRefetchError: portfolioSummaryQuery.isRefetchError,
  })
  const portfolio = portfolioState.portfolio
  const portfolioItems = useMemo(() => portfolio?.items ?? [], [portfolio?.items])
  const portfolioSymbols = useMemo(() => buildPortfolioSymbols(portfolioItems), [portfolioItems])
  const portfolioSymbolKey = portfolioSymbols.join(',')
  const aiContextAvailable = portfolioState.canUseAiContext
  const aiUnavailableMessage = aiContextAvailable
    ? null
    : portfolioState.kind === 'loading'
      ? '계좌 정보를 확인하는 동안 AI 포트폴리오 기능을 사용할 수 없습니다.'
      : resolvePortfolioUnavailableMessage(portfolioState)

  useEffect(() => {
    let isMounted = true

    const loadSnapshots = async () => {
      setIsSnapshotsLoading(true)
      setSnapshotsError(null)

      try {
        const nextSnapshots = await fetchPortfolioSnapshots()
        if (isMounted) {
          setSnapshots(nextSnapshots)
        }
      } catch (error) {
        if (isMounted) {
          setSnapshots([])
          setSnapshotsError(error instanceof Error ? error.message : '성과 스냅샷 조회 실패')
          console.warn('[PortfolioPage initial] snapshots fetch failed', error)
        }
      } finally {
        if (isMounted) {
          setIsSnapshotsLoading(false)
        }
      }
    }

    void loadSnapshots()

    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    const refreshAiAnalysis = async () => {
      if (!aiContextAvailable || portfolioSymbols.length === 0) {
        setAiAnalysisMap({})
        return
      }

      try {
        const nextAiAnalysisMap = await fetchLatestAnalysisBatch(portfolioSymbols)
        if (isMounted) {
          setAiAnalysisMap(nextAiAnalysisMap)
        }
      } catch (error) {
        if (isMounted) {
          setAiAnalysisMap({})
          console.warn('[PortfolioPage] ai analysis fetch failed', error)
        }
      }
    }

    void refreshAiAnalysis()

    return () => {
      isMounted = false
    }
  }, [aiContextAvailable, portfolioSymbolKey, portfolioSymbols])

  useEffect(() => {
    let isMounted = true

    const initializeChatSession = async () => {
      if (!aiContextAvailable || sessionId) {
        return
      }

      try {
        const result = await createChatSession('portfolio')
        if (isMounted) {
          setSessionId(result.session_id)
        }
      } catch (error) {
        console.warn('[PortfolioPage] chat session initialization failed', error)
      }
    }

    void initializeChatSession()

    return () => {
      isMounted = false
    }
  }, [aiContextAvailable, sessionId])

  const krwAsset = portfolioItems.find(isKrwAsset)
  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const totalPnl = portfolio?.total_pnl ?? 0
  const krwBalance = krwAsset?.total_value ?? 0
  const coinCount = portfolioItems.filter((item) => !isKrwAsset(item)).length
  const presentation = resolveStatePresentation(portfolioState)
  const PortfolioStatusIcon = presentation.icon

  const handleCreateSession = async (): Promise<string | null> => {
    if (!aiContextAvailable) {
      return null
    }

    try {
      const result = await createChatSession('portfolio')
      setSessionId(result.session_id)
      return result.session_id
    } catch (error) {
      console.warn('[PortfolioPage] chat session creation failed', error)
      return null
    }
  }

  return (
    <div className="min-h-full space-y-6 text-content">
      <header className="flex flex-col gap-4 border-b border-border-subtle pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand">Portfolio</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-content sm:text-4xl">
            자산 현황
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-content-secondary">
            실제 Upbit 계좌의 자산 배분, 기간 성과와 AI 분석을 한곳에서 확인합니다.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex min-h-10 items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold ${presentation.badgeClassName}`}
          >
            <PortfolioStatusIcon className="h-4 w-4" aria-hidden="true" />
            {presentation.label}
          </span>
          {portfolioState.updatedAt ? (
            <span className="text-xs text-content-secondary">
              {formatUpdatedAt(portfolioState.updatedAt)}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => void portfolioSummaryQuery.refetch()}
            disabled={portfolioSummaryQuery.isFetching}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm font-semibold text-content transition hover:bg-surface-high disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw
              className={`h-4 w-4 ${portfolioSummaryQuery.isFetching ? 'animate-spin' : ''}`}
              aria-hidden="true"
            />
            새로고침
          </button>
        </div>
      </header>

      <PortfolioStateBanner state={portfolioState} />

      {portfolioState.canDisplayAmounts ? (
        <>
          <section
            aria-label="자산 요약과 기간 성과"
            className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(300px,0.72fr)_minmax(0,1.45fr)]"
          >
            <PortfolioSummaryCard
              totalNetWorth={totalNetWorth}
              totalPnl={totalPnl}
              krwBalance={krwBalance}
              coinCount={coinCount}
              isLoading={false}
            />
            <div className="min-w-0">
              <PortfolioPeriodPnlChart snapshots={snapshots} isLoading={isSnapshotsLoading} />
              {snapshotsError ? (
                <p role="status" className="mt-2 text-xs text-warning">
                  성과 기록을 새로 불러오지 못했습니다: {snapshotsError}
                </p>
              ) : null}
            </div>
          </section>

          <section
            aria-label="자산 배분과 보유 종목"
            className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(320px,0.8fr)_minmax(0,1.4fr)]"
          >
            <PortfolioAllocationChart items={portfolioItems} isLoading={false} />
            <PortfolioHoldingsTable
              items={portfolioItems}
              aiAnalysisMap={aiAnalysisMap}
              isLoading={false}
            />
          </section>
        </>
      ) : (
        <PortfolioUnavailablePanel state={portfolioState} />
      )}

      <section aria-label="읽기 전용 AI 포트폴리오 지원" className="space-y-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand-secondary">
            AI Review
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-content">포트폴리오 AI 검토</h2>
          <p className="mt-2 text-sm text-content-secondary">
            AI 응답은 읽기 전용 참고 정보이며 자동 주문이나 전략 적용을 수행하지 않습니다.
          </p>
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,440px)]">
          <div className="min-h-[360px]">
            <PortfolioAiBriefing
              items={portfolioItems}
              snapshots={snapshots}
              totalNetWorth={totalNetWorth}
              totalPnl={totalPnl}
              aiAnalysisMap={aiAnalysisMap}
              isPortfolioLoading={portfolioState.kind === 'loading'}
              isPortfolioAvailable={aiContextAvailable}
              unavailableMessage={aiUnavailableMessage}
            />
          </div>
          <div className="h-[560px] min-h-0 xl:h-[420px]">
            <PortfolioMiniChat
              sessionId={sessionId}
              onCreateSession={handleCreateSession}
              isPortfolioAvailable={aiContextAvailable}
              unavailableMessage={aiUnavailableMessage}
            />
          </div>
        </div>
      </section>
    </div>
  )
}

export default PortfolioPage
