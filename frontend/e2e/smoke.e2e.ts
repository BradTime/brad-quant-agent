import { test, expect, type Page } from '@playwright/test';

/**
 * 关键路径冒烟（确定性、无 LLM）：注册→登录→进应用、登录鉴权门、各页渲染、到达后端。
 * 这套用例若早就存在，能直接抓到"前端默认连 :3001 旧后端致全链路 Network Error"的回归。
 */

/** 注册唯一账号后显式登录（同时验证前端能真正打到后端 :8000）。 */
async function registerFresh(page: Page): Promise<{ email: string; password: string }> {
  const ts = Date.now() + Math.floor(Math.random() * 1000);
  const email = `e2e_${ts}@test.com`;
  const password = 'Test123456!';
  await page.goto('/register');
  await page.locator('#name').fill(`e2e ${ts}`);
  await page.locator('#email').fill(email);
  await page.locator('#password').fill(password);
  await page.locator('#confirmPassword').fill(password);
  await page.getByRole('button', { name: '注册' }).click();
  await expect(page).toHaveURL(/\/login\?registered=1/, { timeout: 15_000 });
  await expect(page.getByText('注册请求已受理', { exact: false })).toBeVisible();
  await page.locator('#email').fill(email);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  return { email, password };
}

test('注册新账号并登录后进入应用（前端→后端连通）', async ({ page }) => {
  await registerFresh(page);
  // 应用外壳（侧栏品牌）渲染，证明已进入受保护区
  await expect(page.getByText('A股投研终端')).toBeVisible();
});

test('未登录访问受保护页会被重定向到登录页', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
});

test('登录后关键页可正常渲染', async ({ page }) => {
  await registerFresh(page);

  await page.goto('/market');
  await expect(page.getByRole('link', { name: /看盘/ })).toBeVisible();

  await page.goto('/ai');
  await expect(page.getByRole('heading', { name: 'AI 看盘问答' })).toBeVisible();
  // 深度研究模式开关存在（本项目特性）
  await expect(page.getByRole('button', { name: '深度研究' })).toBeVisible();

  await page.goto('/brief');
  await expect(page.getByRole('heading', { name: 'AI 盘前早报' })).toBeVisible();
  await expect(page.getByRole('button', { name: /生成今日早报/ })).toBeVisible();

  await page.goto('/sim');
  await expect(page.getByRole('heading', { name: '模拟交易' })).toBeVisible();
  await expect(page.getByText('总资产')).toBeVisible();
});

// 可选：真实 AI 流冒烟（会调用 DeepSeek，默认跳过；设 RUN_AI_E2E=1 才跑）
test('AI 问答可流式作答', async ({ page }) => {
  test.skip(!process.env.RUN_AI_E2E, '默认跳过：会真实调用 LLM。设 RUN_AI_E2E=1 启用。');
  await registerFresh(page);
  await page.goto('/ai');
  await page.getByRole('textbox').fill('上证、深证、创业板现在多少点？');
  await page.getByRole('textbox').press('Enter');
  await expect(page.getByText('不构成投资建议', { exact: false })).toBeVisible({ timeout: 60_000 });
});
