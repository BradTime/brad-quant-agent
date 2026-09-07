import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { SourceNote } from './source-note';

describe('SourceNote', () => {
  it('shows the quote data time and market-closed execution state', () => {
    const html = renderToStaticMarkup(
      <SourceNote
        source="东方财富"
        asOf={Date.UTC(2026, 6, 17, 2, 0)}
        staleReason="market_closed"
        executable={false}
      />
    );

    expect(html).toContain('数据截至');
    expect(html).toContain('市场休市');
  });

  it('explains an expired quote instead of calling it realtime', () => {
    const html = renderToStaticMarkup(
      <SourceNote
        source="东方财富"
        asOf={Date.UTC(2026, 6, 17, 1, 58)}
        staleReason="quote_expired"
        executable={false}
      />
    );

    expect(html).toContain('快照过期');
    expect(html).not.toContain('实时可成交');
  });
});
