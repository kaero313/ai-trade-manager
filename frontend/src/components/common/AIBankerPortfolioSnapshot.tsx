import { AlertTriangle, Loader2, Menu, Wallet } from 'lucide-react'

import { usePortfolioSummary } from '../../hooks/usePortfolioSummary'
import {
  resolvePortfolioDataState,
  resolvePortfolioUnavailableMessage,
} from '../../pages/portfolioDataState'
import type { AssetItem } from '../../services/portfolioService'

interface TopHoldingItem {
  symbol: string
  totalValue: number
}

interface AIBankerPortfolioSnapshotProps {
  onOpenSessions?: () => void
}

function formatKrw(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(Math.round(value))
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
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

function isKrwAsset(item: AssetItem): boolean {
  return String(item.currency || '').trim().toUpperCase() === 'KRW'
}

function getAssetSymbol(item: AssetItem): string {
  return String(item.currency || '').trim().toUpperCase() || '-'
}

function buildTopHoldings(items: AssetItem[]): TopHoldingItem[] {
  return items
    .filter((item) => !isKrwAsset(item))
    .sort((left, right) => right.total_value - left.total_value)
    .slice(0, 3)
    .map((item) => ({
      symbol: getAssetSymbol(item),
      totalValue: item.total_value,
    }))
}

function AIBankerPortfolioSnapshot({ onOpenSessions }: AIBankerPortfolioSnapshotProps) {
  const portfolioQuery = usePortfolioSummary()
  const state = resolvePortfolioDataState({
    data: portfolioQuery.data,
    error: portfolioQuery.error,
    isError: portfolioQuery.isError,
    isLoading: portfolioQuery.isLoading,
    isRefetchError: portfolioQuery.isRefetchError,
  })
  const portfolio = state.portfolio
  const assets = portfolio?.items ?? []
  const totalNetWorth = portfolio?.total_net_worth ?? 0
  const krwBalance = assets.find(isKrwAsset)?.total_value ?? 0
  const topHoldings = buildTopHoldings(assets)
  const stateLabel =
    state.kind === 'live'
      ? 'LIVE'
      : state.kind === 'snapshot'
        ? 'SNAPSHOT'
        : state.kind === 'cached-refetch-error'
          ? 'STALE'
          : null

  return (
    <section className="rounded-2xl border border-border-subtle bg-surface px-5 py-4 text-content">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-high text-brand-bright">
            <Wallet className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[11px] font-bold uppercase tracking-[0.22em] text-brand">
                Portfolio
              </p>
              {stateLabel ? (
                <span className="rounded-full border border-border-subtle bg-surface-high px-2 py-0.5 text-[10px] font-semibold text-content-secondary">
                  {stateLabel}
                </span>
              ) : null}
            </div>
            <p className="truncate text-sm font-bold text-content">포트폴리오 요약</p>
          </div>
        </div>

        {onOpenSessions ? (
          <button
            type="button"
            onClick={onOpenSessions}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-border-strong text-content-secondary transition hover:bg-surface-high hover:text-content lg:hidden"
            aria-label="세션 목록 열기"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {state.kind === 'loading' ? (
        <div className="mt-4 flex flex-wrap gap-2" aria-label="포트폴리오를 불러오는 중">
          {[0, 1, 2].map((index) => (
            <div
              key={index}
              className="h-[72px] min-w-[150px] flex-1 animate-pulse rounded-lg border border-border-subtle bg-surface-lowest"
            />
          ))}
        </div>
      ) : null}

      {!state.canDisplayAmounts && state.kind !== 'loading' ? (
        <div role="status" className="mt-4 rounded-lg bg-surface-high px-3 py-3">
          <div className="flex items-start gap-2 text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p className="text-sm font-medium">포트폴리오 금액을 표시할 수 없습니다</p>
          </div>
          <p className="mt-2 text-xs leading-5 text-content-secondary">
            {resolvePortfolioUnavailableMessage(state)}
          </p>
        </div>
      ) : null}

      {state.canDisplayAmounts ? (
        <>
          {state.isStale ? (
            <div role="status" className="mt-4 flex items-start gap-2 rounded-lg bg-surface-high px-3 py-2 text-xs text-warning">
              {portfolioQuery.isFetching ? (
                <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden="true" />
              ) : (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              )}
              <span>
                마지막 확인 수치 · {formatUpdatedAt(state.updatedAt)}
                {state.errorCode ? ` · ${state.errorCode}` : ''}
              </span>
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-2">
            <div className="min-w-[150px] rounded-lg border border-border-subtle bg-surface-lowest px-4 py-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand">총 자산</p>
              <p className="mt-1 font-mono text-sm font-bold text-content">{formatKrw(totalNetWorth)}</p>
            </div>

            <div className="min-w-[150px] rounded-lg border border-border-subtle bg-surface-lowest px-4 py-3">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand">KRW 잔고</p>
              <p className="mt-1 font-mono text-sm font-bold text-content">{formatKrw(krwBalance)}</p>
            </div>

            <div className="min-w-[260px] flex-1 rounded-lg border border-border-subtle bg-surface-lowest px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand">
                  상위 보유 종목
                </p>
                {portfolioQuery.isFetching ? (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    갱신 중
                  </span>
                ) : null}
              </div>

              {topHoldings.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                  {topHoldings.map((holding) => (
                    <div key={holding.symbol} className="min-w-[96px]">
                      <p className="text-sm font-bold text-content">{holding.symbol}</p>
                      <p className="text-xs text-content-secondary">{formatKrw(holding.totalValue)}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-content-muted">보유 종목 없음</p>
              )}
            </div>
          </div>
        </>
      ) : null}
    </section>
  )
}

export default AIBankerPortfolioSnapshot
