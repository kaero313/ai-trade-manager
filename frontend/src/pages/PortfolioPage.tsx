import { useEffect, useState } from 'react'

import AiTradeTimeline from '../components/portfolio/AiTradeTimeline'
import AiRiskAlert from '../components/portfolio/AiRiskAlert'
import AssetHoldingList from '../components/portfolio/AssetHoldingList'
import PortfolioAiBriefing from '../components/portfolio/PortfolioAiBriefing'
import PortfolioAllocationChart from '../components/portfolio/PortfolioAllocationChart'
import PortfolioMiniChat from '../components/portfolio/PortfolioMiniChat'
import PortfolioSummaryCard from '../components/portfolio/PortfolioSummaryCard'
import PortfolioTrendChart from '../components/portfolio/PortfolioTrendChart'
import { createChatSession } from '../services/api'
import {
  fetchLatestAnalysisBatch,
  fetchPortfolioSnapshots,
  getPortfolioSummary,
} from '../services/portfolioService'
import type {
  AIAnalysisItem,
  AssetItem,
  PortfolioSnapshotItem,
  PortfolioSummary,
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
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotItem[]>([])
  const [aiAnalysisMap, setAiAnalysisMap] = useState<Record<string, AIAnalysisItem | null>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [isSnapshotsLoading, setIsSnapshotsLoading] = useState(true)
  const [sessionId, setSessionId] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    let isPolling = false
    let pollingIntervalId: number | undefined

    const loadInitialData = async () => {
      setIsLoading(true)
      setIsSnapshotsLoading(true)

      const [portfolioResult, snapshotsResult] = await Promise.allSettled([
        getPortfolioSummary(),
        fetchPortfolioSnapshots(),
      ])

      if (!isMounted) {
        return
      }

      let nextPortfolio: PortfolioSummary | null = null

      if (portfolioResult.status === 'fulfilled') {
        nextPortfolio = portfolioResult.value
        setPortfolio(portfolioResult.value)
      } else {
        setPortfolio(null)
        console.warn('[PortfolioPage initial] portfolio fetch failed', portfolioResult.reason)
      }

      if (snapshotsResult.status === 'fulfilled') {
        setSnapshots(snapshotsResult.value)
      } else {
        setSnapshots([])
        console.warn('[PortfolioPage initial] snapshots fetch failed', snapshotsResult.reason)
      }

      setIsSnapshotsLoading(false)

      const symbols = buildPortfolioSymbols(nextPortfolio?.items ?? [])
      if (symbols.length > 0) {
        try {
          const nextAiAnalysisMap = await fetchLatestAnalysisBatch(symbols)
          if (!isMounted) {
            return
          }
          setAiAnalysisMap(nextAiAnalysisMap)
        } catch (error) {
          if (!isMounted) {
            return
          }
          setAiAnalysisMap({})
          console.warn('[PortfolioPage initial] ai analysis fetch failed', error)
        }
      } else {
        setAiAnalysisMap({})
      }

      setIsLoading(false)
    }

    const refreshPortfolioData = async () => {
      if (isPolling) {
        return
      }

      isPolling = true
      try {
        const nextPortfolio = await getPortfolioSummary()
        if (!isMounted) {
          return
        }

        setPortfolio(nextPortfolio)

        const symbols = buildPortfolioSymbols(nextPortfolio.items)
        if (symbols.length > 0) {
          try {
            const nextAiAnalysisMap = await fetchLatestAnalysisBatch(symbols)
            if (!isMounted) {
              return
            }
            setAiAnalysisMap(nextAiAnalysisMap)
          } catch (error) {
            if (!isMounted) {
              return
            }
            console.warn('[PortfolioPage polling] ai analysis refresh failed', error)
          }
        } else {
          setAiAnalysisMap({})
        }
      } catch (error) {
        console.warn('[PortfolioPage polling] portfolio refresh failed', error)
      } finally {
        isPolling = false
      }
    }

    const bootstrap = async () => {
      await loadInitialData()
      if (!isMounted) {
        return
      }

      pollingIntervalId = window.setInterval(() => {
        void refreshPortfolioData()
      }, 30000)
    }

    void bootstrap()

    return () => {
      isMounted = false
      if (pollingIntervalId !== undefined) {
        window.clearInterval(pollingIntervalId)
      }
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    const initializeChatSession = async () => {
      try {
        const result = await createChatSession()
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

  const portfolioItems = portfolio?.items ?? []
  const krwAsset = portfolioItems.find(isKrwAsset)
  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const totalPnl = portfolio?.total_pnl ?? 0
  const krwBalance = krwAsset?.total_value ?? 0
  const coinCount = portfolioItems.filter((item) => !isKrwAsset(item)).length

  const handleCreateSession = async (): Promise<string | null> => {
    try {
      const result = await createChatSession()
      setSessionId(result.session_id)
      return result.session_id
    } catch (error) {
      console.warn('[PortfolioPage] chat session creation failed', error)
      return null
    }
  }

  return (
    <div className="min-h-full lg:grid lg:grid-cols-[1fr_400px] lg:gap-6">
      <section className="min-w-0 space-y-6 lg:h-[calc(100vh-8rem)] lg:overflow-y-auto lg:pr-2">
        <PortfolioSummaryCard
          totalNetWorth={totalNetWorth}
          totalPnl={totalPnl}
          krwBalance={krwBalance}
          coinCount={coinCount}
          isLoading={isLoading}
        />
        <AiRiskAlert items={portfolioItems} totalNetWorth={totalNetWorth} />
        <PortfolioAllocationChart items={portfolioItems} isLoading={isLoading} />
        <PortfolioTrendChart snapshots={snapshots} isLoading={isSnapshotsLoading} />
        <AssetHoldingList
          items={portfolioItems}
          aiAnalysisMap={aiAnalysisMap}
          isLoading={isLoading}
        />
      </section>

      <aside className="hidden lg:flex lg:h-[calc(100vh-8rem)] lg:min-h-0 lg:w-[400px] lg:flex-col lg:gap-6">
        <div className="h-[240px] min-h-0 overflow-y-auto pr-1">
          <PortfolioAiBriefing sessionId={sessionId} />
        </div>

        <div className="h-[300px] min-h-0 overflow-y-auto pr-1">
          <AiTradeTimeline />
        </div>

        <div className="min-h-0 flex-1">
          <PortfolioMiniChat sessionId={sessionId} onCreateSession={handleCreateSession} />
        </div>
      </aside>
    </div>
  )
}

export default PortfolioPage
