import { expect, test } from '@playwright/test';

test('真实全栈个股详情冷导航小于 2 秒', async ({ page }) => {
  test.skip(
    process.env.RUN_FULLSTACK_PERF !== '1',
    '需要真实 Postgres/FastAPI 与已回填 600000.SH 数据',
  );

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

  const started = performance.now();
  const response = await page.goto('/market/600000.SH');
  expect(response?.status()).toBe(200);
  await expect(page.getByTestId('stock-quote-price')).toBeVisible();
  await expect(page.getByTestId('stock-quote-price')).not.toHaveText('—');
  await expect(page.getByTestId('stock-kline-chart').locator('canvas')).toBeVisible();
  const elapsedMs = Math.round(performance.now() - started);
  console.log(`PERF_RESULT fullstack-market-detail cold=${elapsedMs}ms`);

  if (process.env.PERF_ENFORCE === '1') {
    expect(elapsedMs).toBeLessThan(2000);
  }
});
