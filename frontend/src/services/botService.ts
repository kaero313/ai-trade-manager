import { apiClient } from './api'

export interface BotStatus {
  running: boolean
  last_heartbeat: string | null
  last_error: string | null
}

export async function getBotStatus(): Promise<BotStatus> {
  const { data } = await apiClient.get<BotStatus>('/status')
  return data
}

export async function startBot(): Promise<BotStatus> {
  const { data } = await apiClient.post<BotStatus>('/bot/start')
  return data
}

export async function stopBot(): Promise<BotStatus> {
  const { data } = await apiClient.post<BotStatus>('/bot/stop')
  return data
}

export async function liquidateAll(): Promise<void> {
  await apiClient.post('/bot/liquidate')
}
