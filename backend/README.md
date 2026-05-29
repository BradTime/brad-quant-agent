# Quant Agent Backend (Python / FastAPI)

A 股投研平台后端：数据接入（AkShare / BaoStock / efinance）、AI 工具层（DeepSeek function calling）、WebSocket 行情广播、（后期）模拟交易与回测引擎。

完整设计见仓库根目录 [`SPEC.md`](../SPEC.md)。

## 目录结构

```
backend/
├── app/
│   ├── main.py          # FastAPI 入口
│   ├── core/            # 配置、统一响应、安全
│   ├── api/             # 路由（health + /api/v1 聚合）
│   ├── providers/       # DataProvider 抽象 + akshare/baostock/efinance 实现
│   ├── services/        # 行情调度、AI 工具层、撮合（后期）、回测（后期）
│   ├── models/          # ORM + schema（含 PIT 字段）
│   └── ws/              # WebSocket 基座
├── requirements.txt
└── .env.example
```

## 本地开发

> ⚠️ **Python 版本**：建议使用 **3.11 / 3.12**。`akshare`、`pandas` 等数据库在最新的 3.14 上可能尚无预编译 wheel，安装会失败或很慢。

```bash
# 1. 虚拟环境 + 依赖（推荐 python3.12）
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 环境变量
cp .env.example .env   # 填入 DEEPSEEK_API_KEY 等

# 3. 启动
uvicorn app.main:app --reload --port 3001
```

- 健康检查：http://localhost:3001/health
- 接口文档（Swagger）：http://localhost:3001/docs

> 注：`requirements.txt` 暂未锁定版本；首次安装成功后建议 `pip freeze > requirements.lock` 固定。

## 数据接入（Phase 0）

前置：Postgres 已启动（仓库根目录 `docker compose up -d postgres`），且本机可访问公网（AkShare/BaoStock/efinance 需联网）。

数据源经 `app/providers` 的 `DataProvider` 抽象接入，按能力路由（历史/分钟/复权/标的 → BaoStock；实时快照 → efinance，退 AkShare）；落库到 Postgres（`app/models/market.py`，含 PIT 审计字段 `source`/`fetched_at`）。

```bash
# 建表
python -m app.cli init-db

# 标的列表
python -m app.cli ingest-instruments

# 日K线（不复权）/ 复权因子 / 分钟K线
python -m app.cli ingest-daily  --code 600000.SH --start 2024-01-01 --end 2024-12-31
python -m app.cli ingest-adjust --code 600000.SH --start 2020-01-01 --end 2024-12-31
python -m app.cli ingest-minute --code 600000.SH --period 5 --start 2024-12-01 --end 2024-12-31

# 实时快照（不落库，验证连通性）
python -m app.cli quotes --codes 600000.SH,000001.SZ
```

数据说明：日/分钟K线落库为**不复权**原始价，复权由 `adjust_factors` 表按需计算，以保证回测的时点正确性（PIT）。

