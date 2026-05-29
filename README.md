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
```

## 开发阶段
Phase 0 地基 → Phase 1 看盘 + AI 问答 → Phase 2 盘前早报 → Phase 3 模拟交易 → Phase 4 量化研究 / 回测。详见 `SPEC.md`。

## 许可证
MIT
