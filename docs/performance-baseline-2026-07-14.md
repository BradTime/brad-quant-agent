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

结论：本地确定性首屏渲染基线通过，余量约 1520ms。

## 边界

- 该结果衡量前端关键内容渲染，不代表免费行情源冷启动耗时。
- 默认 `npm run e2e:perf` 为 report-only；`PERF_ENFORCE=1` 启用硬阈值。
- CI 工作流接入因仓库安全钩子禁止自动修改 workflow，暂保留为手动/本地硬门禁；后续由维护者审核后再加入 CI。
