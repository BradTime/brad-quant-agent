import { describe, expect, it } from 'vitest';

import { strategyQueryKeys } from './query-keys';

describe('strategyQueryKeys', () => {
  it('isolates cached strategy data by user id', () => {
    expect(strategyQueryKeys.list('user-a', { page: 1 })).not.toEqual(
      strategyQueryKeys.list('user-b', { page: 1 }),
    );
    expect(strategyQueryKeys.detail('user-a', 'strategy-1')).not.toEqual(
      strategyQueryKeys.detail('user-b', 'strategy-1'),
    );
  });
});
