import { useEffect, useState } from 'react'

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

function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [snapshots, setSnapshots] = useState<PortfolioSnapshotItem[]>([])
  const [aiAnalysisMap, setAiAnalysisMap] = useState<Record<string, AIAnalysisItem | null>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [isSnapshotsLoading, setIsSnapshotsLoading] = useState(true)

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

  const assetCount = portfolio?.items.length ?? 0
  const snapshotCount = snapshots.length
  const aiAnalysisCount = Object.keys(aiAnalysisMap).length

  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold">포트폴리오 페이지</h1>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        {isLoading ? '포트폴리오 데이터를 불러오는 중입니다.' : `현재 자산 항목 수: ${assetCount}`}
      </p>
      <p className="text-sm text-slate-600 dark:text-slate-300">
        {isSnapshotsLoading ? '스냅샷 데이터를 불러오는 중입니다.' : `스냅샷 수: ${snapshotCount}`}
      </p>
      <p className="text-sm text-slate-600 dark:text-slate-300">{`AI 분석 대상 수: ${aiAnalysisCount}`}</p>
    </div>
  )
}

export default PortfolioPage
