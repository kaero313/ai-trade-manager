import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getSystemConfigs,
  updateSystemConfigs,
  type SystemConfigItem,
  type SystemConfigUpdateItem,
} from '../services/api'

export const SYSTEM_CONFIGS_QUERY_KEY = ['system-configs'] as const

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
    },
  })
}
