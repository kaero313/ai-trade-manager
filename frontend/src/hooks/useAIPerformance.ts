import { useQuery } from '@tanstack/react-query'

import { fetchAIPerformance } from '../services/api'

export const AI_PERFORMANCE_QUERY_KEY = ['ai-performance'] as const

export function useAIPerformance() {
  return useQuery({
    queryKey: AI_PERFORMANCE_QUERY_KEY,
    queryFn: fetchAIPerformance,
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
  })
}
