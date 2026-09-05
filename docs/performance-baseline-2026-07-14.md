# 个股详情首屏性能基线（2026-07-14）

## 目标

- 页面：`/market/600000.SH`
- 首屏完成定义：行情标题/报价可见，且首个 ECharts `canvas`（K 线）可见。
- SPEC 阈值：连续三次测量中位数 `< 2000ms`。

## 测量方法

- Playwright Chromium，桌面视口。
- 用确定性 API fixture 模拟“数据已落库且立即可取”，排除免费外部数据源波动。
- 首次导航用于预热 Next.js 开发编译与模块图，不计入样本。
- 随后连续 reload 三次，从导航开始计时到报价与 K 线均可见。
- 测试：`frontend/e2e/performance.e2e.ts`
- 命令：`PERF_ENFORCE=1 npm run e2e:perf`

## 结果

| 样本 | 耗时 |
|---|---:|
| 1 | 480ms |
| 2 | 549ms |
| 3 | 451ms |
| **中位数** | **480ms** |
| 阈值 | 2000ms |

结论：本地确定性、热服务下的前端渲染基线通过，余量约 1520ms。

## 真实 Docker 全栈复验（2026-07-15）

- 环境：`docker compose up -d --build backend frontend`，真实 Postgres 持久卷、FastAPI `:8000`、Next.js production `:3000`。
- 数据：已落库 `600000.SH`，不 mock API。
- 流程：注册新用户后首次导航 `/market/600000.SH`，等待真实报价与 K 线 canvas 可见。
- 命令：`RUN_FULLSTACK_PERF=1 PERF_ENFORCE=1 npx playwright test e2e/performance-fullstack.e2e.ts`
- 结果：最终复验 **483ms**，阈值 `<2000ms`，通过。

## 边界

- 确定性 fixture 结果仅衡量前端渲染；真实 Docker 复验覆盖了已落库数据路径，不代表免费外部行情源冷抓取耗时。
- 默认 `npm run e2e:perf` 为 report-only；`PERF_ENFORCE=1` 启用硬阈值。
- CI 工作流接入因仓库安全钩子禁止自动修改 workflow，暂保留为手动/本地硬门禁；后续由维护者审核后再加入 CI。
