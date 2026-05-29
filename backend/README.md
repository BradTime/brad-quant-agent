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

```bash
# 1. 虚拟环境 + 依赖
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 环境变量
cp .env.example .env   # 填入 DEEPSEEK_API_KEY 等

# 3. 启动
uvicorn app.main:app --reload --port 3001
```

- 健康检查：http://localhost:3001/health
- 接口文档（Swagger）：http://localhost:3001/docs

> 注：`requirements.txt` 暂未锁定版本；首次安装成功后建议 `pip freeze > requirements.lock` 固定。
