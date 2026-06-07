import { defineConfig, devices } from '@playwright/test';

/**
 * 端到端测试配置。覆盖**确定性关键路径**（注册/登录/各页渲染/到达后端），
 * 这类用例无需 LLM、快速可靠，正是能抓出"前端连错端口致全链路 Network Error"一类问题的回归网。
 *
 * 前置：后端(:8000) + Postgres 需已运行；前端 dev 由 webServer 自动拉起（已在跑则复用）。
 * 文件用 `*.e2e.ts`，与 Vitest(`*.test.ts`) 区分，互不抢占。
 * 可选的 AI 流用例默认跳过，设 `RUN_AI_E2E=1` 才跑（会真实调用 LLM）。
 */
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    actionTimeout: 10_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
