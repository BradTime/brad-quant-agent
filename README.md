# 量化投资 Agent 平台（AI 原生 A 股个人投研平台）

基于 AI 的 A 股投研驾驶舱：看盘 · AI 看盘问答 · 模拟交易 · 量化研究与回测。

> 总体设计、约束与路线图见 [`SPEC.md`](./SPEC.md)（定稿）。

## 仓库结构（前后端分离）

```
brad-quant-agent/
├── frontend/   # Next.js 15 + React 19 + shadcn/ui + ECharts
├── backend/    # Python FastAPI（数据 / AI 工具层 / WS / 交易 / 回测）
├── SPEC.md     # 产品与技术规格（定稿）
└── docker-compose.yml
```

## 技术栈
- **前端**：Next.js 15 / React 19 / TypeScript / shadcn/ui / Tailwind / Zustand / React Query / ECharts
- **后端**：Python / FastAPI / SQLAlchemy / Postgres
- **数据源**：AkShare + BaoStock + efinance（经 `DataProvider` 抽象，免费）
- **AI**：DeepSeek（function calling 工具层）

## 快速开始

### 前端
```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

### 后端
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 DEEPSEEK_API_KEY 等
alembic upgrade head   # 迁移数据库（首次启动和每次部署都执行）
uvicorn app.main:app --reload --port 8000   # 文档 http://localhost:8000/docs
```

### 数据库（本地）
```bash
docker compose up -d postgres
cd backend && source .venv/bin/activate
python -m app.cli migrate          # 等价于 alembic upgrade head
alembic check                      # 开发/CI：确认 ORM 与数据库无 schema drift
```

`python -m app.cli init-db` 仅保留给临时开发库兼容使用；持久库、容器和 CI 均以
Alembic revision 为唯一迁移流程。Baseline 会为全新 Postgres 建完整 schema，也会
安全接管历史 `create_all` 数据库而不删除已有数据。

### 落库行情数据（看盘/AI 需要）
```bash
# 标的列表（搜索 + 名称）
python -m app.cli ingest-instruments
# 单只股票：日K + 资金流 + 财务 + 新闻（个股详情页也提供「刷新数据」按钮在线落库）
python -c "from app.services.market import refresh_stock; print(refresh_stock('600000.SH'))"
# 历史日K / 分钟K（分钟K需 BaoStock）
python -m app.cli ingest-daily  --code 600000.SH --start 2024-01-01 --end 2025-12-31
python -m app.cli ingest-minute --code 600000.SH --period 5 --start 2025-12-01 --end 2025-12-31
```
> 免费实时快照（东方财富）偶尔限流；实时不可用时个股详情会自动降级展示「最近收盘价」（带标注）。
>
> 财务摘要按 PIT 版本追加保存，不覆盖历史修订。`GET /api/v1/market/financials`
> 可传 `asOf`（RFC3339，或按上海时区日末解释的 `YYYY-MM-DD`）复原当时可见数据；
> 仅有公告日期的数据保守到上海当日 15:00 才可见。响应包含 `availableAt`、
> `announcedAt`、`availabilityQuality` 与 `source`；AI 财务工具也支持同一 `asOf`。

## Phase 1 功能（看盘 + AI 看盘问答）
- **看盘工作台** `/market`：指数概览、标的搜索、自选股分组、全市场行情表、条件选股。
- **个股详情** `/market/[code]`：实时报价（WebSocket）、日/分钟 K 线 + MA/BOLL/MACD/KDJ/RSI 指标、资金流 / 财务摘要 / 龙虎榜 / 新闻 / 概览面板（均标注数据来源与新鲜度），右侧嵌入式 AI 助手。
- **AI 看盘问答** `/ai`：自然语言 → DeepSeek function calling 调用行情/K线/财务/资金流/选股工具 → 流式作答；强制免责声明、不输出确定性买卖指令、缺数据如实声明。
- **自选股**：增删 / 分组，按 `user_id` 隔离持久化。

### AI 准确性回归（SPEC §5.7，黄金测试集 ≥30 题）
```bash
cd backend && source .venv/bin/activate
python scripts/ai_eval.py --offline      # 离线校验数据集结构与工具名
python scripts/ai_eval.py                # 全量：调用 DeepSeek 打分（工具准确率/合规/诚实性）
python -m pytest tests/                   # 离线单测
```
回归报告留存于 `backend/tests/reports/`。

### A 股撮合规则口径
- 佣金万 2.5、最低 5 元；印花税仅卖出收取，2023-08-28 起为 0.5‰，此前为 1‰。模拟交易按上海当前交易日，回测按每笔成交日计税。
- 涨跌停：主板 10%、主板 ST 5%、创业板 2020-08-24 前 10%/之后 20%、科创板（688/689）20%、北交所 30%。科创板、注册制创业板、北交所上市前 5 个 XSHG 中国交易日无涨跌停，第 6 个交易日恢复。
- 回测按每根 bar 日期和 `Instrument.list_date` 计算制度，不把当前名称倒灌到历史；模拟交易即时/挂单撮合均用完整行情快照的昨收校验，行情不可执行门禁优先。规则存在涨跌停但缺少有效昨收时拒绝市价单、挂单不成交；仅上市前 5 个交易日无涨跌停时可不依赖昨收。
- 当前数据模型没有历史 ST 名称/状态序列；缺少 PIT ST 状态的历史 bar 保守按代码、日期和板块规则处理，此局限会继续显式披露。

## Phase 2 功能（AI 盘前早报）
- **盘前早报** `/brief`：基于已落库公开数据（指数 / 自选股 / 资金流 / 龙虎榜 / 新闻）离线装配「数据包」，由 DeepSeek 单轮合成**条件式**研究计划（1 分钟结论 / 5 分钟重点 / 三档建议 / 交易计划或观察名单 / 来源与复盘）。免费源不覆盖的板块（隔夜外盘 / 宏观政策）显式标注缺口、不杜撰；附免责、不输出确定性买卖指令。
- **生成方式**：页面「生成今日早报」按钮（SSE 流式，结束落库）；调度器每日 `BRIEF_CRON_HOUR:BRIEF_CRON_MINUTE`（默认 08:30 Asia/Shanghai）生成全局早报。每份早报连同依据数据快照落库（`morning_briefs`，便于复盘 / PIT）。
- **接口**：`GET /api/v1/brief/latest|global/latest`、`GET /api/v1/brief`（历史）、`GET /api/v1/brief/{id}`、`POST /api/v1/brief/generate`（SSE）。

```bash
# 手动生成一份全局早报（需 DEEPSEEK_API_KEY + 已落库数据）
python -c "from app.services import brief; print(brief.generate(None)['title'])"
```

## AI 增强：RAG 检索增强（pgvector + 本地中文向量）
- **向量库**：Postgres + pgvector（docker 镜像使用 `pgvector/pgvector:pg16`，Alembic baseline 自动创建 `vector` 扩展、`documents` 表与 HNSW 索引）。
- **Embedding**：可插拔（`EMBEDDING_PROVIDER=local|api`），默认本地 `BAAI/bge-small-zh-v1.5`（离线免费，首次自动下载约 95MB）。
- **能力**：新闻/历史早报切块向量化后语义检索；AI 工具 `search_knowledge`（问答自动调用）+ 早报数据包注入 RAG 背景。

```bash
# 先确保用带 pgvector 的镜像起库
docker compose up -d postgres
cd backend && source .venv/bin/activate
pip install -r requirements.txt        # 含 pgvector / sentence-transformers
python -m app.cli migrate              # 建 vector 扩展 + documents 表 + HNSW
python -m app.cli rag-backfill         # 把已落库新闻/历史早报灌入向量库
```
> 切换 embedding 模型若维度变化（默认 512），需重建 `documents` 表（或调整 `EMBEDDING_DIM`）。

## AI 增强：多智能体早报（LangGraph）+ 可观测
盘前早报默认走 **LangGraph 多智能体**流水线（`BRIEF_ENGINE=graph`，可切 `single` 单轮兜底）：

```
规划者 → [市场结构 / 资金面 / 消息面(RAG)] 三分析师并行 → 主编汇总 → 合规反思
```
- **LLM**：经 `langchain-openai` 接 DeepSeek（OpenAI 兼容），复用同一 key。
- **可观测**：① 每节点 `{node, ms, chars}` 轨迹落库（`morning_briefs.data_pack_json.agentTrace`）；② 生成时前端实时显示「多智能体流水线」步骤；③ 可选 **LangSmith** 追踪——在 `.env` 配 `LANGCHAIN_API_KEY` 即自动开启（默认关、离线无依赖）。

```bash
# 依赖：pip install -r requirements.txt（含 langgraph / langchain-openai）
# 可选追踪：在 backend/.env 配 LANGCHAIN_API_KEY=ls-...
python -c "from app.services import brief; print(brief.generate(None)['title'])"  # 多智能体生成一份
```

## 开发阶段
Phase 0 地基 ✅ → Phase 1 看盘 + AI 问答 ✅ → Phase 2 盘前早报 ✅ →（AI 增强：RAG ✅ / 多智能体早报+可观测 ✅）→ Phase 3 模拟交易 → Phase 4 量化研究 / 回测。详见 `SPEC.md`。

## 许可证
MIT
