import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TodayFocus } from '@/components/dashboard/today-focus';

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector: (s: { user: { id: string } }) => unknown) =>
    selector({ user: { id: 'u1' } }),
}));

vi.mock('@/lib/api/brief', () => ({
  getLatestBrief: vi.fn(async () => ({
    id: 'b1',
    title: '测试早报标题',
    tradeDate: '2026-07-18',
  })),
}));

vi.mock('@/lib/api/watchlist', () => ({
  watchlistApi: {
    getList: vi.fn(async () => [
      {
        code: '600000.SH',
        name: '浦发银行',
        changePercent: 1.2,
        group: '默认',
        sortOrder: 0,
        price: 10,
        change: 0.1,
        createdAt: null,
      },
    ]),
  },
}));

vi.mock('@/lib/api/market', () => ({
  marketApi: {
    getFreshness: vi.fn(async () => ({
      quotesTs: Date.now(),
      quotesAgeMs: 1200,
      jobs: {},
      lastIngestion: null,
    })),
  },
}));

describe('TodayFocus', () => {
  it('renders shell with deep-link labels', () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <TodayFocus />
      </QueryClientProvider>
    );
    expect(html).toContain('今日关注');
    expect(html).toContain('data-testid="today-focus"');
    expect(html).toContain('/brief');
  });
});
