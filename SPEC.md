# AI 原生 A 股个人投研平台 — SPEC v1（定稿）

- 状态：定稿（Approved）
- 日期：2026-05-29
- 适用范围：本仓库后续所有开发的总纲；与 `前端开发需求文档.md`（旧版纯前端需求）冲突时，以本 SPEC 为准。

---

## 1. Problem Statement（问题陈述）

现有项目是 `Next.js 前端 + Express(JSON 文件存储)` 的半成品：回测是 `Math.random()` 假数据、无 AI、无真实交易/研究能力、数据来源单一（仅东方财富）且不落库。

目标用户是**作者本人（个人投资者 / 研究者）**，核心诉求是拥有一个**每天真的会用的、AI 原生的 A 股投研驾驶舱**：

- 随时**看盘**（个股 / K线 / 指标 / 资金流 / 自选股）；
- 随口向 **AI** 问行情、板块、个股，并由 AI 自动取数作答；
- 后续能**模拟交易**练手；
- 最终能做严肃的**量化研究与回测**。

**定位**：个人优先，架构为多用户 / 产品化**预留**；以"AI 看盘驾驶舱"切入，区别于聚宽 / BigQuant / 米筐这类"以研究回测为中心的云平台"。

**现状缺口**：① 看盘能力薄弱（无个股详情 / K线 / 指标 / 资金流 / 自选股）；② 完全无 AI；③ 回测是假的；④ 无模拟交易；⑤ 数据来源单一且无落库。

---

## 2. Proposed Solution（方案描述）

### 2.1 形态
- 保留并复用 **Next.js 前端**（复用 UI / 图表 / shadcn 组件，新增"看盘工作台"页面 + 全局导航壳）；
- 新建 **Python FastAPI** 后端替换原 Node/Express（Node 计算层废弃）；
- **DeepSeek function calling** 驱动统一的"工具 / 能力层"，所有平台能力（查行情、查K线、查财务、选股、跑回测、下模拟单…）均封装为可被 AI 调用的工具。

### 2.2 AI 原生主轴
- MVP = **AI 增强型**（GUI 为主，每个模块嵌入 AI 助手）+ **一次性建好工具调用底座**；
- "对话中枢"与"自主 Agent（深度研究 / 定时早报 / 自动交易闭环）"在后期增量复用同一底座。

### 2.3 阶段路线

| 阶段 | 内容 |
|---|---|
| **Phase 0（地基）** | 仓库结构 frontend/backend 分离；FastAPI 骨架；数据源三件套 + `DataProvider` 抽象 + Postgres 落库（含 PIT 字段）；行情拉取调度器；DeepSeek 工具层；WebSocket 基座；前端全局导航壳；认证迁移到 FastAPI |
| **Phase 1（MVP）** | 看盘"进阶版" + AI 看盘问答（含选股工具）✅ |
| **Phase 2** | AI 盘前早报 / 对话问答 ✅ |
| **AI 增强（增量）** | RAG 检索增强（pgvector + 本地 bge）✅；多智能体早报（LangGraph）+ 可观测 ✅；后续 记忆 / MCP / 微调 |
| **Phase 3** | 模拟交易（T+1 撮合 / 持仓 / 订单 + WS 回报 + AI 复盘） |
| **Phase 4** | 量化研究 + 真回测引擎（backtrader/qlib，策略 API 向 RQAlpha/JoinQuant 对齐） |
| **产品化扩展期** | 完整 RBAC + 商业化；其他市场（期货 / 港股 / 美股 / 加密）；i18n；（接付费源后）真实时 / Level-2 |

---

## 3. Technical Constraints（技术约束）

- **前端**：Next.js 15 / React 19 / shadcn/ui / ECharts / Zustand / React Query；国际化用 `next-intl` **预留**（MVP 仅中文，文案不写死）。
- **后端**：Python **FastAPI**（异步 + 原生 WebSocket）；废弃 Express。
- **数据源**：AkShare（主力，覆盖最广）+ BaoStock（历史 K线 / 财务，最稳，用于落库与 Phase 4 回测）+ efinance（补实时快照）；统一经 **`DataProvider` 抽象**、可热插拔（预留 Tushare Pro / 付费源）。
- **存储**：**Postgres**（业务数据 + 历史 K线，多用户就绪）；Redis **后置**（行情缓存 / 限流 / 任务队列，按需引入）；DuckDB/Parquet 列存留 **Phase 4** 回测时再引入。
- **数据正确性（PIT, point-in-time）**：落库时记录数据获取 / 发布时间、复权因子、停复牌 / 退市标记，为 Phase 4 回测严谨性预留，避免未来函数与幸存者偏差。
- **实时**：**WebSocket**（心跳 / 重连 / 订阅退订 / 鉴权 + 后端行情拉取调度与广播）；定位为"可复用基座"（看盘先用，Phase 3 交易回报、AI 流式、风险告警共用）。
  - ⚠️ 明确预期：**上 WS ≠ 真实时**。免费快照的刷新粒度是上限；每个数据面板**标题需标注数据来源 / 新鲜度**，拿不到或延迟的明确标注（如「快照·可能延迟」「来源有限」「免费源数据有限 / 缺失」）。
- **AI**：DeepSeek，经 function calling 驱动工具层；**强制附免责声明、禁止输出确定性买卖指令、数据缺失必须显式声明不得杜撰**。
- **部署**：本地 **Docker Compose** 起步（Postgres + backend + frontend）；代码"云就绪"（配置走环境变量、不硬编码 localhost、数据可备份），云部署留后期。
- **多用户预留**：所有数据按 `user_id` 隔离；认证体系可平滑长成 RBAC（**MVP 仍单用户**，不实现完整权限矩阵）。
- **工程**：统一响应格式 `{ code, message, data, timestamp }`；关键模块测试；Sentry 等可后置。

### 3.1 项目结构（前后端分离，本次落地）

```
brad-quant-agent/
├── frontend/                 # Next.js 15 + React 19（看盘 / AI / 交易 / 研究 UI）
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── ...（next.config.ts / tsconfig.json / eslint / prettier / components.json）
├── backend/                  # Python FastAPI（数据 / AI 工具层 / WS / 交易 / 回测）
│   ├── app/
│   │   ├── main.py
│   │   ├── core/             # 配置、统一响应、安全
│   │   ├── api/              # 路由（auth / market / ai / ...）
│   │   ├── providers/        # DataProvider 抽象 + akshare/baostock/efinance 实现
│   │   ├── services/         # 行情调度、AI 工具层、撮合（后期）、回测（后期）
│   │   ├── models/           # ORM + schema（含 PIT 字段）
│   │   └── ws/               # WebSocket
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
├── SPEC.md                   # 本文件
├── docker-compose.yml        # 本地编排（Phase 0 完善）
└── README.md
```

---

## 4. Non-goals（明确不做的事）

**真正不做：**
1. 实盘交易 / 真实下单（只做模拟盘）。
2. 移动端 App 与移动端深度适配 / 手势（桌面优先）。
3. 社区 / 策略分享 / 策略市场。
4. PWA 离线 / WCAG 无障碍等高级 NFR。

**阶段性"暂不做但已规划"：**
5. 完整 RBAC 与商业化计费——仅 MVP 不做，产品化阶段做（MVP 只建可成长为 RBAC 的数据模型与认证）。
6. 真实时 / Level-2 逐笔——免费阶段做不到；移入范围 = 预留可插拔接口，接入付费数据源后启用。

---

## 5. Success Criteria（成功标准 — 先定 MVP / Phase 1）

1. **数据底座**：用三件套拉取并落库（全市场日 K线 + 自选股分钟 K线 + 资金流 / 财务 / 龙虎榜 / 新闻公告）；每个面板标题正确显示来源与新鲜度，缺失项明确标注。
2. **看盘**：自选股增删 / 分组；个股详情含 实时快照报价 + 日 / 分钟 K线 + 指标（MA/MACD/KDJ/RSI/BOLL）+ 资金流 + 所属板块 + 财务摘要 + 龙虎榜 + 新闻公告；大盘指数概览。
3. **实时**：WebSocket 通道打通，行情按固定间隔推送，断线自动重连、心跳正常。
4. **AI 看盘问答**：自然语言问个股 / 板块 / 大盘，AI 经工具调用取**真实落库数据**流式作答；每次附免责声明、不给确定性买卖指令。
5. **可运行**：本地 `docker compose up` 一键起全栈；个股详情页首屏 < 2s。
6. **质量底线**：数据层与 AI 工具层有基础测试；关键路径有错误兜底与友好提示。
7. **AI 准确性（可衡量）**：
   - 维护 **≥ 30 条**典型问题"黄金测试集"（报价 / 涨跌幅 / PE-PB / 资金流 / 板块 / 龙虎榜 / 财务摘要等）；
   - 数据型回答**数值与落库数据一致率 = 100%**（允许明确标注"数据缺失"）；
   - **杜撰率 = 0（红线）**：缺数据必须说"无法获取"，不得编造字段 / 数值；
   - **工具选择准确率 ≥ 95%**；
   - 合规 100%：附免责声明、0 条确定性买卖指令；
   - 通过该测试集回归校验。

---

## 6. 对标与借鉴（设计参考）

结论：方向合理且有差异化定位（AI 原生个人驾驶舱）。诚实风险：① 免费数据在深度 / 清洗 / 时点正确性上弱于专业平台，不与其拼数据广度；② 回测放最后，现阶段是"看盘 + AI"而非"量化平台"。

| 标杆 | 强项 | 借鉴点 | 阶段 |
|---|---|---|---|
| TradingView | 看盘 / 图表 UX | 多窗格 K线、画线、自选股 + 价格告警、键盘流 | Phase 1 |
| 同花顺问财 | 自然语言选股 | "NL→条件选股"做成 AI 工具 | Phase 1~2 |
| 聚宽 / 米筐 RQAlpha | 策略 API + 回测严谨 | initialize/handle_bar 规范、T+1/复权/滑点/印花税、vs 基准；策略 API 对齐以复用社区策略 | Phase 4 |
| BigQuant / 微软 qlib | AI/ML 因子流水线、数据层 | 因子挖掘、表达式引擎、PIT 数据；AI 辅助因子 | Phase 4 + AI |
| 雪球 | 模拟组合 + 关注 | 模拟组合体验（社区为 Non-goal） | Phase 3 |
| Wind / Bloomberg | 终端级数据 + 命令式 | "一切皆可一句话查到"——AI 驾驶舱北极星 | 长期 |

**现在就埋下的原则（功能在后期，数据层先支持，避免返工）：**
1. **PIT 时点数据正确性**（数据模型预留时点 / 复权 / 停复牌 / 退市）。
2. **选股工具早做**（AI 工具层加"条件选股"）。
3. **策略 API 向 RQAlpha/JoinQuant 对齐**（Phase 4 实现，方向现在定）。

---

## 7. 路线图与任务拆解（Phase 0 + Phase 1）

### Phase 0 — 地基
- [ ] 仓库结构 `frontend/` + `backend/` 分离（✅ 本次落地骨架）
- [ ] FastAPI 骨架：入口、配置（env）、统一响应、CORS、错误处理、健康检查（✅ 本次落地骨架）
- [ ] `DataProvider` 抽象接口 + AkShare / BaoStock / efinance 三个实现
- [ ] Postgres schema：标的、日 K、分钟 K、复权因子、停复牌 / 退市、资金流、财务摘要、龙虎榜、新闻公告（**含 PIT 字段**）
- [ ] 行情拉取调度器（定时任务）+ 落库 + 缓存
- [ ] DeepSeek 工具层：工具注册表（查行情 / K线 / 财务 / 资金流 / 选股 …）、function calling 编排、流式输出、免责与"不杜撰 / 不荐股"红线守卫
- [ ] WebSocket 基座：连接管理 / 心跳 / 重连 / 订阅退订 / 鉴权 + 行情广播
- [ ] 前端：全局布局 / 导航壳；数据层指向 FastAPI；WS 客户端封装
- [ ] 认证迁移：JWT 登录注册到 FastAPI；`user_id` 隔离；`role` 字段预留
- [ ] 部署：Docker Compose（postgres + backend + frontend）

### Phase 1 — MVP（看盘 + AI 看盘问答）
- [x] 自选股：增删 / 分组（持久化，`user_id` 隔离）
- [x] 个股详情页：实时快照报价（WS）、日 / 分钟 K线（ECharts candlestick + 周期切换）、指标 MA/MACD/KDJ/RSI/BOLL、资金流、所属板块、财务摘要、龙虎榜、新闻公告；标题数据来源 / 新鲜度 / 缺失标注（实时不可用降级展示最近收盘）
- [x] 大盘指数概览（看盘工作台 + dashboard 复用）
- [x] 选股工具（AI 可调用 `screen_stocks` + 手动条件筛选 UI）
- [x] AI 看盘问答：嵌入式助手（个股详情右栏）+ 独立 `/ai` 页，自然语言 → 工具调用 → 流式作答，免责 + 红线
- [x] AI 准确性测试集（36 题 `tests/golden_questions.json`）与回归校验脚本 `scripts/ai_eval.py`（离线/全量）
- [x] **AI 准确性全量回归已通过**（DeepSeek `deepseek-chat` 实跑 36 题）：工具选择 100%（32/32，目标 ≥95%）、合规含免责 100%（36/36，红线）、确定性买卖指令 0 条（红线）、报价数值与落库一致 14/14（软指标 100%）、缺数据诚实性 2/2；报告留存于 `backend/tests/reports/phase1_ai_eval_*.txt`
- [x] 健壮性：免费实时源限流时全市场快照抓取加硬超时降级（`realtime_fetch_timeout_seconds`），避免请求/调度无限挂起；实时不可用时选股/快照按 SPEC 显式标注，不杜撰
- [~] 验收：`docker compose up` 一键起（已就绪）；个股详情首屏 < 2s（本地达标，依赖数据已落库）

### Phase 2 — AI 盘前早报
- [x] 数据装配 `build_data_pack`：从已落库/缓存离线汇总（指数、自选股涨跌榜、自选股资金流、近期龙虎榜、近 48h 新闻），并显式标注覆盖缺口（隔夜外盘 / 宏观政策 / 机构研报）——只喂真实数据，绝不触发会阻塞的实时拉取
- [x] 单轮合成 `run_completion_stream`（无工具）+ 盘前早报提示词：1 分钟结论 / 5 分钟重点 / 三档建议（进攻·均衡·稳健）/ 条件式交易计划或观察名单 / 来源与复盘；强制免责、条件式、缺口如实声明、不杜撰
- [x] 落库 `morning_briefs`（含依据数据快照 `data_pack_json`，便于复盘 / PIT）；`user_id` 空=系统全局，非空=用户个性化（基于自选股）
- [x] 接口：`GET /brief/latest|global/latest`、`GET /brief`（历史）、`GET /brief/{id}`、`POST /brief/generate`（SSE 流式，结束落库）
- [x] 调度器每日定时（默认 08:30 Asia/Shanghai，`enable_brief_scheduler` / `brief_cron_*`）生成全局早报
- [x] 前端 `/brief`：最新早报 Markdown 渲染 + 「生成今日早报」流式 + 历史列表 + 来源/免责标注；侧栏导航
- [x] 冒烟验证：真实 DeepSeek 生成全局早报，正文具体数字（净买额/资金流向/公告）均可溯源至数据包新闻标题（无杜撰），缺口板块如实标注，免责齐全
- [ ] 对话中枢 / 自主深度研究（多轮规划编排）——留作 Phase 2 增量（当前 `/ai` 已具备多轮工具问答）

### AI 增强 — RAG 检索增强（Phase A，增量）
- [x] pgvector 向量库（docker 镜像 `pgvector/pgvector:pg16` + `CREATE EXTENSION vector`）+ `documents` 表（chunk/embedding/来源/时间，PIT 友好）
- [x] 可插拔 embedding 接口（`embedding_provider` local/api；默认本地 `BAAI/bge-small-zh-v1.5`，懒加载、离线免费；查询侧加 bge 检索指令、L2 归一化 + 余弦距离）
- [x] `services/rag`：切块 → 向量化 → upsert → 语义检索 `retrieve`；`cli rag-backfill` 把已落库新闻/历史早报灌入（回填 135 块）
- [x] 暴露 AI 工具 `search_knowledge`（问答可自动调用）；早报数据包接入 RAG 背景检索（更早新闻 / 历史早报，提供延续性）
- [x] 验证：语义检索相关性达标（白酒→茅台、半导体→封测/光通信）；39 项单测通过
- [ ] 后续：HNSW 索引（语料增大后）、混合检索（BM25+向量）

### AI 增强 — 多智能体早报 + 可观测（LangGraph，增量）
- [x] LangGraph 状态图：规划者 → [市场结构 / 资金面 / 消息面(RAG) / 海外宏观] 四分析师**并行** → 主编汇总 → 质量评审官 →（不达标且未修订过）主编修订 → 再评审 → 合规反思（代码化红线校验）
- [x] LLM 经 `langchain-openai` 接 DeepSeek（OpenAI 兼容）；`brief_engine=graph|single` 开关，图不可用/异常自动**降级单轮**
- [x] 可观测三件套：① 每节点 `{node, ms, chars, tools, scores...}` **轨迹落库**（`data_pack_json.agentTrace`）；② 生成时 **SSE step 事件**前端实时进度条；③ **LangSmith 追踪**（配置 `LANGCHAIN_API_KEY` 才开，默认关、离线无依赖）
- [x] 复用同一数据装配（含 RAG 背景）与合规守卫；早报正文仍为条件式、附免责、缺口如实
- [x] **反思回环（evaluator-optimizer，有界 1 轮）**：质量评审官按 grounding/honesty/conditional/structure/actionable 五维 JSON 打分，不达标触发主编修订再评审；评分入轨迹供观测
- [x] **分析师按需调工具**：消息面/研究分析师可调用 `search_knowledge`(RAG) 补背景（有界 1 轮，复用 `ai.tools.execute_tool` 能力层）
- [x] **前端可观测/可视化**：`/brief` 详情接口暴露 `dataPack`+`agentTrace`+`engine`；早报页右栏「智能体观测（含质量自评分数/工具调用/修订）/ 海外宏观 / 量化知识背景」卡片
- [x] **评审轮数可配**：`brief_max_revisions`（默认 1，`brief_graph` 封顶 3，防失控）
- [x] **分析师按域暴露更多工具**：市场结构→`get_market_overview`/`get_kline`、资金面→`get_capital_flow`/`get_dragon_tiger`、消息面→`search_knowledge`/`get_news`（均有界 1 轮、复用同一能力层）
- [x] **轨迹时序甘特图**：每节点记录 `start/end`（epoch ms），前端按真实起止绘制条带，直观呈现四分析师**并行重叠**与各段耗时
- [ ] 后续：分析师暴露行情实时工具（需配合超时降级）、轨迹下钻查看各节点输入输出

---

## 8. 决策记录（Decision Log）

| # | 决策 | 选择 |
|---|---|---|
| 1 | 产品定位 | 个人为主，架构为多用户 / 产品化预留 |
| 2 | "AI 原生"形态 | MVP 做 AI 增强型 + 建好工具调用底座；对话中枢 / 自主 Agent 后期 |
| 3 | MVP 优先顺序 | 看盘问答 → AI 早报 → 模拟交易 → 研究回测（地基为 Phase 0 公共前提） |
| 4 | 看盘数据范围 | 进阶版（含盘口 / 龙虎榜 / 新闻公告）；免费源拿不到的在标题标注 |
| 5 | 数据源 | AkShare（主）+ BaoStock（历史 / 财务）+ efinance（实时快照）；`DataProvider` 抽象 |
| 6 | 架构 | 保留 Next.js 前端 + 新建 FastAPI 后端，废弃 Node |
| 7 | 存储 | Postgres 起步；Redis / 列存分阶段引入 |
| 8 | 实时机制 | MVP 即上 WebSocket（可复用基座） |
| 9 | 部署 | 本地 Docker Compose 起步，云部署后期 |
| 10 | 范围 / Non-goals | 见第 4 节 |
| 11 | 成功标准 | 见第 5 节（含可衡量 AI 准确性） |
| 12 | 仓库结构 | 前后端分别置于 `frontend/` 与 `backend/` |
