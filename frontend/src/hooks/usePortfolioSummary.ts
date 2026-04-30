import { useQuery } from '@tanstack/react-query'

import { getPortfolioSummary } from '../services/portfolioService'

export const PORTFOLIO_SUMMARY_QUERY_KEY = ['portfolio-summary'] as const

export function usePortfolioSummary() {
  return useQuery({
    queryKey: PORTFOLIO_SUMMARY_QUERY_KEY,
    queryFn: getPortfolioSummary,
    refetchInterval: (query) => {
      if (query.state.status === 'error' || query.state.data?.is_stale) {
        return 30000
      }
      return 15000
    },
    refetchIntervalInBackground: true,
    placeholderData: (previousData) => previousData,
    retry: 1,
  })
}
