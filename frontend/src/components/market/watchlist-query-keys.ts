/** 自选股 QueryKey（按 user 隔离，避免换号串缓存）。 */
export const watchlistQueryKeys = {
  all: (userId: string | undefined) =>
    ['watchlist', userId ?? 'anonymous'] as const,
  groups: (userId: string | undefined) =>
    ['watchlist', 'groups', userId ?? 'anonymous'] as const,
};
