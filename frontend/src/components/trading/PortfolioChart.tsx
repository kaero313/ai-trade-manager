import type { AssetItem, PortfolioSummary } from '../../services/portfolioService'

interface PortfolioChartProps {
  items: AssetItem[]
  isLoading: boolean
  source: PortfolioSummary['source'] | null
  isStale: boolean
  updatedAt: string | null
  errorCode?: string | null
  totalNetWorth?: number
  totalPnl?: number
}

interface AllocationDatum {
  name: string
  value: number
  percent: number
  color: string
}

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral'

interface PortfolioStatusView {
  label: string
  tone: StatusTone
  notice: string | null
}

const COLORS = ['#00dbe9', '#cdbdff', '#ffe179', '#ffb4ab', '#77e2a8', '#849495']
const RING_RADIUS = 64
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

function formatKrw(value: number): string {
  return `₩${new Intl.NumberFormat('ko-KR').format(Math.round(value))}`
}

function formatSignedKrw(value: number): string {
  if (value > 0) {
    return `+${formatKrw(value)}`
  }
  if (value < 0) {
    return `-${formatKrw(Math.abs(value))}`
  }
  return formatKrw(value)
}

function formatUpdatedAt(value: string | null): string | null {
  if (!value) {
    return null
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }

  return date.toLocaleString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function resolveErrorMessage(errorCode?: string | null): string {
  if (errorCode === 'PORTFOLIO_FETCH_TIMEOUT') {
    return '실시간 자산 조회가 지연되어 마지막 정상 값을 표시하고 있습니다.'
  }
  if (errorCode === 'UPBIT_KEY_MISSING') {
    return 'Upbit API 키가 없어 실시간 자산을 조회할 수 없습니다.'
  }
  if (errorCode === 'UPBIT_AUTH_IP_NOT_ALLOWED') {
    return 'Upbit API 허용 IP 목록에 현재 서버 IP가 없어 자산 조회가 차단되었습니다.'
  }
  if (errorCode === 'UPBIT_AUTH_ERROR') {
    return 'Upbit API 인증 또는 권한 설정 문제로 자산 조회가 차단되었습니다.'
  }
  if (errorCode) {
    return '실시간 자산 조회에 실패해 마지막 정상 값을 유지하고 있습니다.'
  }
  return '최신 자산 조회가 지연되어 마지막 정상 값을 유지하고 있습니다.'
}

function resolveStatusStyle(tone: StatusTone): { bg: string; text: string } {
  if (tone === 'success') {
    return { bg: 'bg-[#77e2a8]/10', text: 'text-[#77e2a8]' }
  }
  if (tone === 'warning') {
    return { bg: 'bg-[#ffe179]/10', text: 'text-[#ffe179]' }
  }
  if (tone === 'danger') {
    return { bg: 'bg-[#ffb4ab]/10', text: 'text-[#ffb4ab]' }
  }
  return { bg: 'bg-[#262a31]/80', text: 'text-[#b9cacb]' }
}

function resolvePortfolioStatus({
  source,
  isStale,
  updatedAt,
  errorCode,
}: {
  source: PortfolioSummary['source'] | null
  isStale: boolean
  updatedAt: string | null
  errorCode?: string | null
}): PortfolioStatusView {
  const updatedAtLabel = formatUpdatedAt(updatedAt)
  const staleSuffix = updatedAtLabel ? ` 마지막 갱신 ${updatedAtLabel}` : ''

  if (source === 'live' && !isStale) {
    return { label: 'SYNCED', tone: 'success', notice: null }
  }

  if (source === 'snapshot') {
    return {
      label: 'SNAPSHOT',
      tone: 'warning',
      notice: `${resolveErrorMessage(errorCode)}${staleSuffix}`,
    }
  }

  if (source === 'empty') {
    return {
      label: 'DEGRADED',
      tone: 'danger',
      notice: resolveErrorMessage(errorCode),
    }
  }

  if (isStale) {
    return {
      label: 'STALE',
      tone: 'warning',
      notice: `${resolveErrorMessage(errorCode)}${staleSuffix}`,
    }
  }

  return { label: 'WAITING', tone: 'neutral', notice: '자산 조회를 준비하고 있습니다.' }
}

function buildAllocationData(items: AssetItem[]): AllocationDatum[] {
  const grouped = new Map<string, number>()

  for (const item of items) {
    const currency = String(item.currency || '').trim().toUpperCase() || 'UNKNOWN'
    const value = Number(item.total_value)
    if (!Number.isFinite(value) || value <= 0) {
      continue
    }
    grouped.set(currency, (grouped.get(currency) ?? 0) + value)
  }

  const sorted = Array.from(grouped.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  const total = sorted.reduce((acc, item) => acc + item.value, 0)
  if (total <= 0) {
    return []
  }

  return sorted.map((item, index) => ({
    name: item.name,
    value: item.value,
    percent: (item.value / total) * 100,
    color: COLORS[index % COLORS.length],
  }))
}

function resolvePortfolioBriefing(data: AllocationDatum[], status: PortfolioStatusView): string {
  if (data.length === 0) {
    return `AI 브리핑: ${
      status.notice ??
      '자산 비중 데이터가 확보되면 AI 브리핑과 리밸런싱 관찰 포인트를 표시합니다.'
    }`
  }

  const [topAsset, secondAsset] = data
  const krwPercent = data.find((item) => item.name === 'KRW')?.percent ?? 0

  if (topAsset.percent >= 70) {
    return `AI 브리핑: ${topAsset.name} 비중이 ${topAsset.percent.toFixed(
      1,
    )}%로 높습니다. 신규 진입보다 변동성 확인과 리밸런싱 후보 관찰이 우선입니다.`
  }

  if (krwPercent >= 35) {
    return `AI 브리핑: KRW 대기자금이 ${krwPercent.toFixed(
      1,
    )}%로 충분합니다. 추격 매수보다 Entry Policy 통과 신호를 기다리는 구성이 적절합니다.`
  }

  if (secondAsset) {
    return `AI 브리핑: ${topAsset.name}/${secondAsset.name} 중심의 보유 구조입니다. 대형 자산 흐름은 유지되지만 급격한 비중 쏠림 여부를 계속 확인합니다.`
  }

  return `AI 브리핑: ${topAsset.name} 단일 중심 포트폴리오입니다. 추가 매수보다 리스크 한도와 손익 변동성을 먼저 평가합니다.`
}

function resolveRiskScore(data: AllocationDatum[]): number {
  if (data.length === 0) {
    return 0
  }

  const topPercent = data[0]?.percent ?? 0
  const krwPercent = data.find((item) => item.name === 'KRW')?.percent ?? 0
  const diversificationBonus = Math.min(18, Math.max(0, data.length - 1) * 6)
  const cashBufferBonus = Math.min(12, krwPercent / 3)
  const concentrationPenalty = Math.max(0, topPercent - 45) * 0.7
  const score = 72 + diversificationBonus + cashBufferBonus - concentrationPenalty

  return Math.max(0, Math.min(99, Math.round(score)))
}

function AllocationRing({ data, riskScore }: { data: AllocationDatum[]; riskScore: number }) {
  const visibleData = data.slice(0, 4)
  const segments = visibleData.map((item, index) => {
    const offset = visibleData
      .slice(0, index)
      .reduce((acc, previousItem) => acc + (previousItem.percent / 100) * RING_CIRCUMFERENCE, 0)
    const dash = (item.percent / 100) * RING_CIRCUMFERENCE

    return {
      dashLength: Math.max(0, dash - 2),
      item,
      offset,
    }
  })

  return (
    <div className="relative mx-auto h-40 w-40">
      <svg className="h-full w-full -rotate-90" viewBox="0 0 160 160" aria-hidden="true">
        <circle cx="80" cy="80" fill="transparent" r={RING_RADIUS} stroke="#26323d" strokeWidth="12" />
        {segments.map(({ dashLength, item, offset }) => (
          <circle
            key={item.name}
            cx="80"
            cy="80"
            fill="transparent"
            r={RING_RADIUS}
            stroke={item.color}
            strokeDasharray={`${dashLength} ${RING_CIRCUMFERENCE - dashLength}`}
            strokeDashoffset={-offset}
            strokeLinecap="round"
            strokeWidth="12"
          />
        ))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="text-xs text-[#849495]">Risk Score</span>
        <span className="font-mono text-3xl font-semibold text-[#00dbe9]">{riskScore}</span>
      </div>
    </div>
  )
}

function PortfolioChart({
  items,
  isLoading,
  source,
  isStale,
  updatedAt,
  errorCode = null,
  totalNetWorth = 0,
  totalPnl = 0,
}: PortfolioChartProps) {
  const allocationData = buildAllocationData(items)
  const hasData = allocationData.length > 0
  const status = resolvePortfolioStatus({ source, isStale, updatedAt, errorCode })
  const statusStyle = resolveStatusStyle(status.tone)
  const briefing = resolvePortfolioBriefing(allocationData, status)
  const riskScore = resolveRiskScore(allocationData)
  const summaryNetWorth =
    totalNetWorth > 0 ? totalNetWorth : allocationData.reduce((acc, item) => acc + item.value, 0)
  const topAllocations = allocationData.slice(0, 3)

  return (
    <section className="quantum-card rounded-xl p-5">
      <header className="mb-5 flex items-start justify-between gap-4">
        <h2 className="min-w-0 text-xl font-bold text-[#dfe2eb]">AI 포트폴리오 요약</h2>
        <span
          className={`shrink-0 rounded px-2 py-1 font-mono text-[10px] font-bold ${statusStyle.bg} ${statusStyle.text}`}
        >
          {status.label}
        </span>
      </header>

      {status.notice && (
        <p className={`mb-4 rounded-lg bg-[#0a0e14]/72 p-3 text-sm font-semibold leading-6 ${statusStyle.text}`}>
          {status.notice}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-[#0a0e14]/72 p-3">
          <p className="text-xs text-[#849495]">총 순자산</p>
          <p className="mt-2 break-words font-mono text-lg font-semibold text-[#dfe2eb]">
            {formatKrw(summaryNetWorth)}
          </p>
        </div>
        <div className="rounded-lg bg-[#0a0e14]/72 p-3">
          <p className="text-xs text-[#849495]">평가손익</p>
          <p
            className={`mt-2 break-words font-mono text-lg font-semibold ${
              totalPnl > 0 ? 'text-[#77e2a8]' : totalPnl < 0 ? 'text-[#ffb4ab]' : 'text-[#849495]'
            }`}
          >
            {formatSignedKrw(totalPnl)}
          </p>
        </div>
      </div>

      {isLoading && (
        <div className="mt-5 flex min-h-48 items-center justify-center rounded-lg bg-[#0a0e14]/72 text-sm text-[#849495]">
          자산 비중을 불러오는 중입니다.
        </div>
      )}

      {!isLoading && (
        <div className="mt-5 grid grid-cols-[160px_1fr] items-center gap-5 max-sm:grid-cols-1">
          <AllocationRing data={allocationData} riskScore={riskScore} />

          {hasData ? (
            <div className="space-y-3 text-sm">
              {topAllocations.map((item) => (
                <div key={item.name}>
                  <div className="flex items-center justify-between gap-3">
                    <span className="min-w-0 truncate text-[#849495]">{item.name} 비중</span>
                    <span className="shrink-0 font-mono" style={{ color: item.color }}>
                      {item.percent.toFixed(1)}%
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[#262a31]">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.min(100, item.percent)}%`, backgroundColor: item.color }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg bg-[#0a0e14]/72 p-4 text-sm leading-6 text-[#849495]">
              <p className="font-semibold text-[#dfe2eb]">비중 데이터 대기</p>
              <p className="mt-2">
                실시간 자산 또는 마지막 스냅샷을 확보하면 상위 보유 비중이 여기에 표시됩니다.
              </p>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#262a31]">
                <div className="h-full w-0 rounded-full bg-[#00dbe9]" />
              </div>
            </div>
          )}
        </div>
      )}

      <p className="mt-5 rounded-lg bg-[#00dbe9]/10 p-3 text-sm leading-6 text-[#b9cacb]">
        {briefing}
      </p>
    </section>
  )
}

export default PortfolioChart
