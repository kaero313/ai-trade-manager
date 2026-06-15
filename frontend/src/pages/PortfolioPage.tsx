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

function PortfolioPage() {
  const portfolioSummaryQuery = usePortfolioSummary()
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotItem[]>([])
  const [aiAnalysisMap, setAiAnalysisMap] = useState<Record<string, AIAnalysisItem | null>>({})
  const [isSnapshotsLoading, setIsSnapshotsLoading] = useState(true)
  const [sessionId, setSessionId] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    const loadSnapshots = async () => {
      setIsSnapshotsLoading(true)

      try {
        const nextSnapshots = await fetchPortfolioSnapshots()
        if (!isMounted) {
          return
        }
        setSnapshots(nextSnapshots)
      } catch (error) {
        if (!isMounted) {
          return
        }
        setSnapshots([])
        console.warn('[PortfolioPage initial] snapshots fetch failed', error)
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

  const portfolio = portfolioSummaryQuery.data ?? null
  const portfolioItems = useMemo(() => portfolio?.items ?? [], [portfolio?.items])
  const portfolioSymbols = useMemo(() => buildPortfolioSymbols(portfolioItems), [portfolioItems])
  const portfolioSymbolKey = portfolioSymbols.join(',')
  const isLoading = portfolioSummaryQuery.isLoading && portfolio === null

  useEffect(() => {
    let isMounted = true

    const refreshAiAnalysis = async () => {
      if (portfolioSymbols.length === 0) {
        setAiAnalysisMap({})
        return
      }

      try {
        const nextAiAnalysisMap = await fetchLatestAnalysisBatch(portfolioSymbols)
        if (!isMounted) {
          return
        }
        setAiAnalysisMap(nextAiAnalysisMap)
      } catch (error) {
        if (!isMounted) {
          return
        }
        setAiAnalysisMap({})
        console.warn('[PortfolioPage] ai analysis fetch failed', error)
      }
    }

    void refreshAiAnalysis()

    return () => {
      isMounted = false
    }
  }, [portfolioSymbolKey, portfolioSymbols])

  useEffect(() => {
    let isMounted = true

    const initializeChatSession = async () => {
      try {
        const result = await createChatSession('portfolio')
        if (!isMounted) {
          return
        }
        setSessionId(result.session_id)
      } catch (error) {
        console.warn('[PortfolioPage] chat session initialization failed', error)
      }
    }

    void initializeChatSession()

    return () => {
      isMounted = false
    }
  }, [])

  const krwAsset = portfolioItems.find(isKrwAsset)
  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const totalPnl = portfolio?.total_pnl ?? 0
  const krwBalance = krwAsset?.total_value ?? 0
  const coinCount = portfolioItems.filter((item) => !isKrwAsset(item)).length

  const handleCreateSession = async (): Promise<string | null> => {
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
    <div className="dashboard-quantum min-h-full space-y-5">
      <section
        aria-label="AI 포트폴리오 분석"
        className="grid min-w-0 grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,440px)]"
      >
        <div className="min-h-[360px]">
          <PortfolioAiBriefing
            items={portfolioItems}
            snapshots={snapshots}
            totalNetWorth={totalNetWorth}
            totalPnl={totalPnl}
            aiAnalysisMap={aiAnalysisMap}
            isPortfolioLoading={isLoading}
          />
        </div>
        <div className="h-[560px] min-h-0 xl:h-[420px]">
          <PortfolioMiniChat sessionId={sessionId} onCreateSession={handleCreateSession} />
        </div>
      </section>

      <section className="grid min-w-0 grid-cols-1 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <PortfolioSummaryCard
          totalNetWorth={totalNetWorth}
          totalPnl={totalPnl}
          krwBalance={krwBalance}
          coinCount={coinCount}
          isLoading={isLoading}
        />
        <PortfolioPeriodPnlChart snapshots={snapshots} isLoading={isSnapshotsLoading} />
      </section>

      <section className="grid min-w-0 grid-cols-1 gap-5 xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]">
        <PortfolioAllocationChart items={portfolioItems} isLoading={isLoading} />
        <PortfolioHoldingsTable
          items={portfolioItems}
          aiAnalysisMap={aiAnalysisMap}
          isLoading={isLoading}
        />
      </section>
    </div>
  )
}

export default PortfolioPage
