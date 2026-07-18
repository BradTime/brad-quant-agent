/** 自选股 QueryKey（按 user 隔离，避免换号串缓存）。 */
export const watchlistQueryKeys = {
  all: (userId: string | undefined) =>
    ['watchlist', userId ?? 'anonymous'] as const,
};
