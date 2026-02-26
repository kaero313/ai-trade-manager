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
