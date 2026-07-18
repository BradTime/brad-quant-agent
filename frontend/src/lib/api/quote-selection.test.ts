import { describe, expect, it } from 'vitest';
import type { StockQuote } from './market';
import * as quoteSelectionModule from './quote-selection';
import { selectDisplayQuote } from './quote-selection';

function quote(
  asOf: number,
  overrides: Partial<StockQuote> = {}
): StockQuote {
  return {
    code: '600000.SH',
    name: '浦发银行',
    price: 10,
    change: 0,
    changePercent: 0,
    volume: 0,
    amount: 0,
    timestamp: asOf,
    asOf,
    ageMs: 0,
    maxAgeMs: 60_000,
    stale: false,
    staleReason: null,
    executable: true,
    ...overrides,
  };
}

describe('selectDisplayQuote', () => {
  it('falls back to stale HTTP data after the websocket disconnects', () => {
    const httpQuote = quote(2_000, {
      stale: true,
      staleReason: 'quote_expired',
      executable: false,
    });
    const oldWsQuote = quote(1_000);

    expect(selectDisplayQuote(httpQuote, oldWsQuote, 'closed')).toBe(httpQuote);
  });

  it('does not let an older websocket payload overwrite newer HTTP data', () => {
    const httpQuote = quote(2_000);
    const oldWsQuote = quote(1_000);

    expect(
      selectDisplayQuote(httpQuote, oldWsQuote, 'open', 2_000, 3_000, 3_000)
    ).toBe(httpQuote);
  });

  it('uses a connected websocket payload only when it is at least as new', () => {
    const httpQuote = quote(2_000);
    const newWsQuote = quote(2_001);

    expect(selectDisplayQuote(httpQuote, newWsQuote, 'open')).toBe(newWsQuote);
  });

  it('uses later HTTP state when data asOf is identical', () => {
    const asOf = 2_000;
    const laterStaleHttp = quote(asOf, {
      stale: true,
      staleReason: 'quote_expired',
      executable: false,
    });
    const earlierExecutableWs = quote(asOf);

    expect(
      selectDisplayQuote(
        laterStaleHttp,
        earlierExecutableWs,
        'open',
        3_000,
        2_000,
        3_000
      )
    ).toBe(laterStaleHttp);
  });

  it('uses later websocket state when data asOf is identical', () => {
    const asOf = 2_000;
    const earlierStaleHttp = quote(asOf, {
      stale: true,
      staleReason: 'quote_expired',
      executable: false,
    });
    const laterExecutableWs = quote(asOf);

    expect(
      selectDisplayQuote(
        earlierStaleHttp,
        laterExecutableWs,
        'open',
        2_000,
        3_000,
        3_000
      )
    ).toBe(laterExecutableWs);
  });

  it('locally expires retained HTTP data when refreshes fail', () => {
    const retainedHttp = quote(1_000, { ageMs: 1_000 });

    const selected = selectDisplayQuote(
      retainedHttp,
      undefined,
      'closed',
      1_000,
      0,
      61_001
    );

    expect(selected).toMatchObject({
      stale: true,
      staleReason: 'quote_expired',
      executable: false,
      ageMs: 61_001,
    });
  });

  it('locally expires an old websocket value that remains connected', () => {
    const retainedWs = quote(1_000);

    const selected = selectDisplayQuote(
      undefined,
      retainedWs,
      'open',
      0,
      1_000,
      61_001
    );

    expect(selected).toMatchObject({
      stale: true,
      staleReason: 'quote_expired',
      executable: false,
      ageMs: 60_001,
    });
  });

  it('formats a market-closed quote with its data time', () => {
    const helpers = quoteSelectionModule as unknown as {
      formatQuoteFreshness?: (
        value: StockQuote
      ) => { label: string; asOfText: string | null };
    };
    expect(helpers.formatQuoteFreshness).toBeTypeOf('function');

    const formatted = helpers.formatQuoteFreshness!(
      quote(Date.UTC(2026, 6, 17, 4, 0), {
        staleReason: 'market_closed',
        executable: false,
      })
    );
    expect(formatted.label).toBe('市场休市');
    expect(formatted.asOfText).toContain('12:00');
  });
});
