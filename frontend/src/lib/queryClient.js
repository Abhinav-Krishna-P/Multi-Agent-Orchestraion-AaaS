import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      // Client errors (not found, signed out, refused) will not get better by asking again.
      retry: (failureCount, error) => failureCount < 2 && !(error?.status >= 400 && error?.status < 500),
    },
  },
})
