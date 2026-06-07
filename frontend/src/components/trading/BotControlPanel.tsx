import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useSystemConfigs } from '../../hooks/useSystemConfigs'
import { getBotStatus, startBot, stopBot } from '../../services/api'

type ActionType = 'start' | 'stop' | null
type NoticeType = 'success' | 'error'

interface NoticeState {
  message: string
  type: NoticeType
}

interface BotControlPanelProps {
  portfolioError?: string | null
}

const TRADING_MODE_KEY = 'trading_mode'
const LIVE_BUY_ENABLED_KEY = 'live_buy_enabled'
const AI_ENTRY_SHADOW_MODE_KEY = 'ai_entry_shadow_mode'

function resolveErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (error.message) {
      return error.message
    }
  }
  return fallback
}

function resolvePortfolioWarningMessage(portfolioError: string | null | undefined): string | null {
  if (portfolioError === null || portfolioError === undefined) {
    return null
  }

  if (portfolioError === 'UPBIT_KEY_MISSING') {
    return '업비트 API 키가 설정되지 않아 자산 조회 및 매매 기능이 제한됩니다.'
  }
  if (portfolioError === 'UPBIT_AUTH_IP_NOT_ALLOWED') {
    return '현재 서버 IP가 업비트 API 허용 목록에 없어 자산 조회 및 매매 기능이 제한됩니다.'
  }
  if (portfolioError === 'UPBIT_AUTH_ERROR') {
    return '업비트 API 인증 또는 권한 설정 문제로 자산 조회 및 매매 기능이 제한됩니다.'
  }

  return '업비트 자산 정보를 불러오지 못해 자산 조회 및 매매 기능이 제한됩니다.'
}

function findConfigValue(
  configs: Array<{ config_key: string; config_value: string }> | undefined,
  key: string,
  fallback: string,
): string {
  return configs?.find((item) => item.config_key === key)?.config_value ?? fallback
}

function parseBooleanConfig(rawValue: string, fallback: boolean): boolean {
  const normalized = rawValue.trim().toLowerCase()
  if (['true', '1', 'yes', 'on'].includes(normalized)) {
    return true
  }
  if (['false', '0', 'no', 'off'].includes(normalized)) {
    return false
  }
  return fallback
}

function BotControlPanel({ portfolioError = null }: BotControlPanelProps) {
  const queryClient = useQueryClient()
  const [activeAction, setActiveAction] = useState<ActionType>(null)
  const [notice, setNotice] = useState<NoticeState | null>(null)
  const systemConfigsQuery = useSystemConfigs()

  const botStatusQuery = useQuery({
    queryKey: ['bot-status'],
    queryFn: getBotStatus,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })

  useEffect(() => {
    if (notice === null) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setNotice(null)
    }, 3000)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [notice])

  const isLoading = botStatusQuery.isLoading
  const isError = botStatusQuery.isError
  const isActive = botStatusQuery.data?.running ?? false
  const isSubmitting = activeAction !== null
  const isConfigLoading = systemConfigsQuery.isLoading && systemConfigsQuery.data === undefined
  const tradingMode = findConfigValue(systemConfigsQuery.data, TRADING_MODE_KEY, 'live').toLowerCase()
  const liveBuyEnabled = parseBooleanConfig(
    findConfigValue(systemConfigsQuery.data, LIVE_BUY_ENABLED_KEY, 'false'),
    false,
  )
  const aiEntryShadowMode = parseBooleanConfig(
    findConfigValue(systemConfigsQuery.data, AI_ENTRY_SHADOW_MODE_KEY, 'true'),
    true,
  )
  const buyMode = aiEntryShadowMode ? 'shadow' : liveBuyEnabled ? 'live' : 'locked'
  const buyModeLabel =
    isConfigLoading ? 'CHECK' : buyMode === 'live' ? 'LIVE BUY' : buyMode === 'shadow' ? 'SHADOW' : 'LOCKED'
  const buyModeClassName =
    isConfigLoading
      ? 'text-[#849495]'
      : buyMode === 'live'
      ? 'text-[#7df4ff]'
      : buyMode === 'shadow'
        ? 'text-[#ffe179]'
        : 'text-[#ffb4ab]'
  const liveBuyLabel =
    isConfigLoading ? 'CHECK' : liveBuyEnabled && !aiEntryShadowMode ? 'ENABLED' : 'LOCKED'
  const liveBuyClassName =
    isConfigLoading
      ? 'text-[#849495]'
      : liveBuyEnabled && !aiEntryShadowMode
        ? 'text-[#7df4ff]'
        : 'text-[#ffb4ab]'
  const badgeLabel = isError ? 'ERROR' : isLoading ? 'CHECK' : isActive ? 'ACTIVE' : 'STOP'
  const badgeClassName = isError
    ? 'bg-[#ffb4ab]/10 text-[#ffb4ab]'
    : isActive
      ? 'bg-[#00dbe9]/10 text-[#7df4ff]'
      : 'bg-[#262a31] text-[#b9cacb]'
  const portfolioWarningMessage = resolvePortfolioWarningMessage(portfolioError)

  const handleStart = async () => {
    setActiveAction('start')
    setNotice(null)

    try {
      const nextStatus = await startBot()
      queryClient.setQueryData(['bot-status'], nextStatus)
      void queryClient.invalidateQueries({ queryKey: ['bot-status'] })
      setNotice({ message: '봇 가동 요청을 전송했습니다.', type: 'success' })
    } catch (error) {
      setNotice({ message: resolveErrorMessage(error, '봇 가동 요청에 실패했습니다.'), type: 'error' })
    } finally {
      setActiveAction(null)
    }
  }

  const handleStop = async () => {
    setActiveAction('stop')
    setNotice(null)

    try {
      const nextStatus = await stopBot()
      queryClient.setQueryData(['bot-status'], nextStatus)
      void queryClient.invalidateQueries({ queryKey: ['bot-status'] })
      setNotice({ message: '봇 정지 요청을 전송했습니다.', type: 'success' })
    } catch (error) {
      setNotice({ message: resolveErrorMessage(error, '봇 정지 요청에 실패했습니다.'), type: 'error' })
    } finally {
      setActiveAction(null)
    }
  }

  return (
    <aside className="quantum-card rounded-xl p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#ffe179]">
            Bot Control
          </p>
          <h2 className="mt-2 text-lg font-bold text-[#dfe2eb]">실시간 파라미터 제어</h2>
        </div>
        <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-md px-2.5 py-1 text-[11px] font-bold ${badgeClassName}`}>
          {badgeLabel}
        </span>
      </header>

      <p className="mt-3 text-sm leading-6 text-[#849495]">
        봇 런타임과 매매 잠금 상태를 확인하고, 원격 시작/정지를 즉시 전송합니다.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="border-l-2 border-[#00dbe9] pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-[#849495]">Runtime</p>
          <p className="mt-2 font-mono text-base font-bold text-[#dfe2eb]">
            {isActive ? 'RUNNING' : isError ? 'UNKNOWN' : 'STOPPED'}
          </p>
        </div>
        <div className="border-l-2 border-[#ffe179] pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-[#849495]">Refresh</p>
          <p className="mt-2 font-mono text-base font-bold text-[#dfe2eb]">
            {isError ? '30s retry' : '5s live'}
          </p>
        </div>
        <div className="border-l-2 border-[#cdbdff] pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-[#849495]">Mode</p>
          <p className={`mt-2 font-mono text-base font-bold ${buyModeClassName}`}>
            {buyModeLabel}
          </p>
        </div>
        <div className="border-l-2 border-[#ffb4ab] pl-3">
          <p className="font-semibold uppercase tracking-[0.16em] text-[#849495]">Live Buy</p>
          <p className={`mt-2 font-mono text-base font-bold ${liveBuyClassName}`}>
            {liveBuyLabel}
          </p>
        </div>
      </div>

      {portfolioWarningMessage && (
        <div className="mt-4 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold leading-5 text-[#ffe179]">
          자산 연결 제한
        </div>
      )}

      <section className="mt-5 border-t border-[#29363a]/80 pt-5">
        <div className="mb-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded bg-[#77e2a8]/10 px-2 py-1 text-[#77e2a8]">
            {isConfigLoading ? 'mode checking' : tradingMode}
          </span>
          <span
            className={`rounded px-2 py-1 ${
              isConfigLoading
                ? 'bg-[#262a31]/70 text-[#b9cacb]'
                : buyMode === 'live'
                ? 'bg-[#00dbe9]/10 text-[#7df4ff]'
                : buyMode === 'shadow'
                  ? 'bg-[#ffe179]/10 text-[#ffe179]'
                  : 'bg-[#ffb4ab]/10 text-[#ffb4ab]'
            }`}
          >
            {isConfigLoading
              ? 'buy mode check'
              : buyMode === 'live'
                ? 'live buy armed'
                : buyMode === 'shadow'
                  ? 'shadow'
                  : 'buy locked'}
          </span>
          <span
            className={`rounded px-2 py-1 ${
              isConfigLoading
                ? 'bg-[#262a31]/70 text-[#b9cacb]'
                : liveBuyEnabled && !aiEntryShadowMode
                ? 'bg-[#00dbe9]/10 text-[#7df4ff]'
                : 'bg-[#ffb4ab]/10 text-[#ffb4ab]'
            }`}
          >
            {isConfigLoading
              ? 'live buy check'
              : liveBuyEnabled && !aiEntryShadowMode
                ? 'live buy on'
                : 'live buy off'}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={handleStart}
            disabled={isSubmitting || isLoading || isActive}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              isActive
                ? 'cursor-not-allowed bg-[#00dbe9]/10 text-[#00dbe9]/45'
                : 'bg-[#00dbe9]/14 text-[#7df4ff] hover:bg-[#00dbe9]/22'
            } disabled:opacity-70`}
          >
            {activeAction === 'start' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>{activeAction === 'start' ? '가동 중...' : '봇 가동'}</span>
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={isSubmitting || isLoading || !isActive}
            className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
              !isActive
                ? 'cursor-not-allowed bg-[#0a0e14]/75 text-[#849495]'
                : 'bg-[#0a0e14] text-[#dfe2eb] hover:bg-[#262a31]'
            } disabled:opacity-70`}
          >
            {activeAction === 'stop' && <Loader2 className="h-4 w-4 animate-spin" />}
            <span>{activeAction === 'stop' ? '정지 중...' : '봇 정지'}</span>
          </button>
        </div>
      </section>

      {notice && (
        <p
          className={`mt-4 rounded-lg bg-[#0a0e14]/75 px-3 py-2 text-xs font-semibold ${
            notice.type === 'success'
              ? 'text-[#77e2a8]'
              : 'text-[#ffb4ab]'
          }`}
        >
          {notice.message}
        </p>
      )}

    </aside>
  )
}

export default BotControlPanel
