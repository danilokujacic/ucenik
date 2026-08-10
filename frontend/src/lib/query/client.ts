import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/errors";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        retry: (failureCount, error) => {
          // Don't burn retries on errors that won't resolve themselves -
          // auth/permission/not-found/validation are all final answers.
          if (error instanceof ApiError && [401, 403, 404, 409, 413, 415, 422].includes(error.status)) {
            return false;
          }
          return failureCount < 2;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
