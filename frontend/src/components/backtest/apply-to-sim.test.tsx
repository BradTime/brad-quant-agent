import { describe, expect, it } from 'vitest';
import { draftFromBacktest } from '@/components/backtest/apply-to-sim';

describe('draftFromBacktest', () => {
  it('prefers last trade symbol then config codes', () => {
    expect(
      draftFromBacktest({
        config: { codes: ['600000.SH'] },
        trades: [{ symbol: '000001.SZ' }],
      })
    ).toEqual({ code: '000001.SZ', side: 'buy', qty: 100 });

    expect(
      draftFromBacktest({
        config: { codes: ['600000.SH'] },
        trades: [],
      })
    ).toEqual({ code: '600000.SH', side: 'buy', qty: 100 });

    expect(draftFromBacktest({ config: { codes: [] }, trades: [] })).toBeNull();
  });

  it('safely ignores non-array codes from an API config record', () => {
    expect(
      draftFromBacktest({
        config: { engine: 'native', codes: '600000.SH' },
        trades: [],
      }),
    ).toBeNull();
  });
});
