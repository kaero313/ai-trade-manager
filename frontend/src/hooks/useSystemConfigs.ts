import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getAiProviderRuntimeStatus,
  getSystemConfigs,
  updateSystemConfigs,
  type AiProviderRuntimeStatusResponse,
  type SystemConfigItem,
  type SystemConfigUpdateItem,
} from '../services/api'

export const SYSTEM_CONFIGS_QUERY_KEY = ['system-configs'] as const
export const AI_PROVIDER_RUNTIME_STATUS_QUERY_KEY = ['ai-provider-runtime-status'] as const

export function useSystemConfigs() {
  return useQuery({
    queryKey: SYSTEM_CONFIGS_QUERY_KEY,
    queryFn: getSystemConfigs,
  })
}

export function useUpdateSystemConfigs() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (items: SystemConfigUpdateItem[]) => updateSystemConfigs(items),
    onSuccess: (items: SystemConfigItem[]) => {
      queryClient.setQueryData(SYSTEM_CONFIGS_QUERY_KEY, items)
      void queryClient.invalidateQueries({ queryKey: SYSTEM_CONFIGS_QUERY_KEY })
      void queryClient.invalidateQueries({ queryKey: AI_PROVIDER_RUNTIME_STATUS_QUERY_KEY })
    },
  })
}

export function useAiProviderRuntimeStatus() {
  return useQuery<AiProviderRuntimeStatusResponse>({
    queryKey: AI_PROVIDER_RUNTIME_STATUS_QUERY_KEY,
    queryFn: getAiProviderRuntimeStatus,
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })
}
