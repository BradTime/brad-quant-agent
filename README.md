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
uvicorn app.main:app --reload --port 3001   # 文档 http://localhost:3001/docs
```

### 数据库（本地）
```bash
docker compose up -d postgres
cd backend && source .venv/bin/activate
python -m app.cli init-db          # 建表（含自选股 watchlist_items）
```

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

## Phase 2 功能（AI 盘前早报）
- **盘前早报** `/brief`：基于已落库公开数据（指数 / 自选股 / 资金流 / 龙虎榜 / 新闻）离线装配「数据包」，由 DeepSeek 单轮合成**条件式**研究计划（1 分钟结论 / 5 分钟重点 / 三档建议 / 交易计划或观察名单 / 来源与复盘）。免费源不覆盖的板块（隔夜外盘 / 宏观政策）显式标注缺口、不杜撰；附免责、不输出确定性买卖指令。
- **生成方式**：页面「生成今日早报」按钮（SSE 流式，结束落库）；调度器每日 `BRIEF_CRON_HOUR:BRIEF_CRON_MINUTE`（默认 08:30 Asia/Shanghai）生成全局早报。每份早报连同依据数据快照落库（`morning_briefs`，便于复盘 / PIT）。
- **接口**：`GET /api/v1/brief/latest|global/latest`、`GET /api/v1/brief`（历史）、`GET /api/v1/brief/{id}`、`POST /api/v1/brief/generate`（SSE）。

```bash
# 手动生成一份全局早报（需 DEEPSEEK_API_KEY + 已落库数据）
python -c "from app.services import brief; print(brief.generate(None)['title'])"
```

## 开发阶段
Phase 0 地基 ✅ → Phase 1 看盘 + AI 问答 ✅ → Phase 2 盘前早报 ✅ → Phase 3 模拟交易 → Phase 4 量化研究 / 回测。详见 `SPEC.md`。

## 许可证
MIT
