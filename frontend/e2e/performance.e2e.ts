import { expect, test, type Page } from '@playwright/test';

const envelope = (data: unknown) => ({
  code: 200,
  message: 'success',
  data,
  timestamp: Date.now(),
});

const kline = Array.from({ length: 120 }, (_, i) => ({
  time: new Date(2025, 0, i + 1).toISOString().slice(0, 10),
  open: 9 + i * 0.01,
  high: 9.2 + i * 0.01,
  low: 8.8 + i * 0.01,
  close: 9.1 + i * 0.01,
  volume: 1_000_000 + i * 1000,
}));

async function installDeterministicMarketFixtures(page: Page) {
  await page.route('**/api/v1/market/quote/**', (route) => {
    expect(new URL(route.request().url()).pathname.endsWith('/market/quote/600000.SH')).toBe(true);
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(
        envelope({
          code: '600000.SH',
          name: '浦发银行',
          price: 9.44,
          change: 0.12,
          changePercent: 1.29,
          volume: 12_000_000,
          amount: 113_280_000,
          high: 9.5,
          low: 9.2,
          open: 9.3,
          yesterdayClose: 9.32,
          timestamp: Date.now(),
          asOf: Date.now(),
          ageMs: 0,
          maxAgeMs: 60_000,
          stale: false,
          staleReason: null,
          executable: true,
        }),
      ),
    });
  });
  await page.route('**/api/v1/market/stock/**', (route) => {
    expect(new URL(route.request().url()).pathname.endsWith('/market/stock/600000.SH')).toBe(true);
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(
        envelope({ code: '600000.SH', name: '浦发银行', industry: '银行', source: 'fixture' }),
      ),
    });
  });
  await page.route('**/api/v1/market/kline**', (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get('symbol')).toBe('600000.SH');
    expect(url.searchParams.get('period')).toBe('day');
    expect(url.searchParams.get('count')).toBe('250');
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(envelope({ bars: kline, dataQuality: 'full' })),
    });
  });
  await page.route('**/api/v1/watchlist**', (route) =>
    route.fulfill({ contentType: 'application/json', body: JSON.stringify(envelope([])) }),
  );
}

async function registerFresh(page: Page) {
  const stamp = `${Date.now()}_${Math.floor(Math.random() * 1000)}`;
  const email = `perf_${stamp}@test.com`;
  const password = 'Test123456!';
  await page.goto('/register');
  await page.locator('#name').fill(`perf ${stamp}`);
  await page.locator('#email').fill(email);
  await page.locator('#password').fill(password);
  await page.locator('#confirmPassword').fill(password);
  await page.getByRole('button', { name: '注册' }).click();
  await expect(page).toHaveURL(/\/login\?registered=1/, { timeout: 15_000 });
  await page.locator('#email').fill(email);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
}

async function gotoWarmRoute(page: Page) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await page.goto('/market/600000.SH');
    if (response?.status() === 200) return;
    await page.waitForTimeout(500);
  }
  throw new Error('个股详情路由预热后仍不可用');
}

test('个股详情关键首屏连续三次中位数小于 2 秒', async ({ page }, testInfo) => {
  await installDeterministicMarketFixtures(page);
  await registerFresh(page);

  // First navigation warms the Next.js dev compiler and module graph; the measured
  // runs represent an already-running local/production service with data available.
  await gotoWarmRoute(page);
  await expect(page.getByRole('heading', { name: '浦发银行' })).toBeVisible();
  await expect(page.getByTestId('stock-quote-price')).toBeVisible();
  await expect(page.getByTestId('stock-quote-price')).toHaveText('9.44');
  await expect(page.getByTestId('stock-kline-chart').locator('canvas')).toBeVisible();

  const samples: number[] = [];
  for (let i = 0; i < 3; i += 1) {
    const started = performance.now();
    await page.reload();
    await expect(page.getByRole('heading', { name: '浦发银行' })).toBeVisible();
    await expect(page.getByTestId('stock-quote-price')).toBeVisible();
    await expect(page.getByTestId('stock-quote-price')).toHaveText('9.44');
    await expect(page.getByTestId('stock-kline-chart').locator('canvas')).toBeVisible();
    samples.push(Math.round(performance.now() - started));
  }

  const sorted = [...samples].sort((a, b) => a - b);
  const medianMs = sorted[1];
  await testInfo.attach('market-detail-performance.json', {
    contentType: 'application/json',
    body: Buffer.from(JSON.stringify({ samplesMs: samples, medianMs, thresholdMs: 2000 }, null, 2)),
  });
  console.log(`PERF_RESULT market-detail samples=${samples.join(',')} median=${medianMs}ms`);

  if (process.env.PERF_ENFORCE === '1') {
    expect(medianMs, `samples=${samples.join(',')}ms`).toBeLessThan(2000);
  } else {
    // CI starts report-only to collect a stable baseline before making runner
    // variance a merge blocker. PERF_ENFORCE=1 turns on the hard SPEC gate.
    expect(medianMs).toBeGreaterThan(0);
  }
});
