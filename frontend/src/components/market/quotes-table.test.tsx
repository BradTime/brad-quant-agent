import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { StockQuote } from '@/lib/api/market';
import { QuotesTable } from './quotes-table';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

function quote(overrides: Partial<StockQuote> = {}): StockQuote {
  return {
    code: '600000.SH',
    name: '浦发银行',
    price: 10,
    change: 0,
    changePercent: 0,
    volume: 0,
    amount: 0,
    high: null,
    low: null,
    open: null,
    yesterdayClose: null,
    timestamp: 0,
    asOf: null,
    ageMs: null,
    maxAgeMs: 60_000,
    stale: true,
    staleReason: 'missing_as_of',
    executable: false,
    ...overrides,
  };
}

describe('QuotesTable', () => {
  it('renders missing quote fields as em dashes without throwing', () => {
    const html = renderToStaticMarkup(
      <QuotesTable
        stocks={[
          quote({
            price: null,
            change: null,
            changePercent: null,
            volume: null,
            amount: null,
          }),
        ]}
      />
    );

    expect(html.match(/—/g)?.length).toBeGreaterThanOrEqual(3);
    expect(html).not.toContain('0.00%');
  });

  it('keeps real zero changes visible as zero', () => {
    const html = renderToStaticMarkup(<QuotesTable stocks={[quote()]} />);

    expect(html).toContain('10.00');
    expect(html).toContain('+0.00%');
    expect(html).toContain('0');
  });

  it('shows market-closed freshness instead of a realtime label', () => {
    const html = renderToStaticMarkup(
      <QuotesTable
        stocks={[
          quote({
            asOf: Date.UTC(2026, 6, 17, 4, 0),
            stale: false,
            staleReason: 'market_closed',
            executable: false,
          }),
        ]}
      />
    );

    expect(html).toContain('市场休市');
    expect(html).toContain('12:00');
    expect(html).not.toContain('实时可成交');
  });
});
