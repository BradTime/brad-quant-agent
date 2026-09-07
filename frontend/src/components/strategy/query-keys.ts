import type { StrategyListParams } from '@/types/strategy';

export const strategyQueryKeys = {
  all: (userId: string | undefined) => ['strategies', userId ?? 'anonymous'] as const,
  list: (userId: string | undefined, params: StrategyListParams) =>
    [...strategyQueryKeys.all(userId), params] as const,
  detail: (userId: string | undefined, strategyId: string) =>
    ['strategy', userId ?? 'anonymous', strategyId] as const,
};
