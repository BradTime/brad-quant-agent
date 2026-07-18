import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import BacktestPage, { DataQualityNotice } from './page';

vi.mock('@/components/charts', () => ({
  LineChart: () => null,
}));

vi.mock('@/lib/api/backtest', () => ({
  backtestApi: {
    strategyCatalog: vi.fn(),
    run: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
    gridSearch: vi.fn(),
  },
  streamBacktestReview: vi.fn(),
}));

vi.mock('@/lib/api/strategies', () => ({
  strategiesApi: {
    getList: vi.fn(),
  },
}));

describe('BacktestPage', () => {
  it('offers every supported daily and minute frequency', () => {
    const html = renderToStaticMarkup(<BacktestPage />);

    expect(html).toContain('回测周期');
    for (const frequency of ['1d', '5m', '15m', '30m', '60m']) {
      expect(html).toContain(`value="${frequency}"`);
    }
  });

  it('offers native and backtrader engines', () => {
    const html = renderToStaticMarkup(<BacktestPage />);

    expect(html).toContain('回测引擎');
    expect(html).toContain('value="native"');
    expect(html).toContain('value="backtrader"');
  });

  it('warns that an untracked ingestion snapshot is allowed only for compatibility', () => {
    const html = renderToStaticMarkup(
      <DataQualityNotice dataQuality={{ '600000.SH': 'untracked' }} />,
    );

    expect(html).toContain('untracked');
    expect(html).toContain('兼容历史库');
    expect(html).toContain('对应周期或区间');
    expect(html).toContain('确认数据完整性');
  });
});
