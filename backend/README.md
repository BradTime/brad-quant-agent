# Quant Agent Backend (Python / FastAPI)

A 股投研平台后端：数据接入（AkShare / BaoStock / efinance）、AI 工具层（DeepSeek function calling）、WebSocket 行情广播、（后期）模拟交易与回测引擎。

完整设计见仓库根目录 [`SPEC.md`](../SPEC.md)。

## 目录结构

```
backend/
├── alembic/            # 数据库 revision 与迁移环境
├── alembic.ini
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

# 3. 迁移数据库并启动
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

生产环境必须将 `APP_ENV=production`。`JWT_SECRET` 仅接受 64 位 hex
（`openssl rand -hex 32`），或解码后至少 32 字节的 base64url
（`openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n'`）；服务拒绝默认值、
周期重复、低多样性弱串和 HS256 之外的算法。开发环境可使用示例默认值，但启动会记录警告。

登录失败按规范化邮箱与客户端 IP 分别持久化限流：默认 15 分钟内 5 次失败后锁定
15 分钟；注册按 IP 默认每小时 10 次。状态存于 `auth_throttles`，Postgres advisory
lock + row lock 保证多 worker 原子更新。默认忽略 `X-Forwarded-For`；部署在反向代理
后时，仅将代理网段以 CIDR 写入 `AUTH_TRUSTED_PROXIES`。解析会从 XFF 右向左剥离

**M20 Cookie 会话**：`POST /auth/login` / `refresh` 设置 HttpOnly `qa_access` + `qa_refresh`
（JSON 仅返回 `user`）；`GET /auth/ws-ticket` 签发最长 120 秒的独立 `ws` JWT 供 WebSocket 握手；
`get_current_user` 仍接受 `Authorization: Bearer`（脚本/pytest）。前端经同源
`/api/v1` rewrite，使 Cookie 落在前端域并由 Next `proxy.ts` SSR 门控。
可信代理，采用首个不可信 hop；直连 peer 不在可信网段或 XFF 含无效地址时忽略整个头。

注册接口采用防枚举响应：合法请求无论邮箱是否已存在都返回 HTTP 202 与相同
`{accepted:true,message}`，不签发 token。生产 pending 阶段不创建 `users` 行、也不保存
`password_hash`，只在 `email_verifications` 保存 email、请求姓名、有效期和 SHA-256 token
hash，原 token 仅交给 SMTP sender。同邮箱存在未过期 pending 时重复注册不会轮换或失效链接；
仅无 pending/已过期时生成新 token。邮箱持有者在 `/verify` 输入最终姓名和严格密码，
`POST /auth/verify` 原子消费 token 并创建 verified User；并发消费最多创建一个用户。未验证与
不存在账户使用同一登录失败消息。生产必须完整配置
`SMTP_HOST/PORT/USER/PASSWORD/FROM`、`FRONTEND_URL`，且
`AUTH_AUTO_VERIFY_REGISTRATION=false`，且 `FRONTEND_URL` 必须为 HTTPS（邮件内链接只允许
HTTPS）；否则启动失败。dev/test 默认自动验证，Docker/E2E 显式启用，以免本地依赖邮件服务。

登录校验无论账户是否存在、历史哈希为何，都固定执行一次 PBKDF2 与一次 bcrypt 验证：
真实哈希走其算法，另一算法走预生成 dummy hash。成功验证旧 bcrypt 后自动迁移为 PBKDF2。

- 健康检查：http://localhost:8000/health
- 接口文档（Swagger）：http://localhost:8000/docs

> 注：`requirements.txt` 暂未锁定版本；首次安装成功后建议 `pip freeze > requirements.lock` 固定。

## 数据接入（Phase 0）

前置：Postgres 已启动（仓库根目录 `docker compose up -d postgres`），且本机可访问公网（AkShare/BaoStock/efinance 需联网）。

数据源经 `app/providers` 的 `DataProvider` 抽象接入，按能力路由（历史/分钟/复权/标的 → BaoStock；实时快照 → efinance，退 AkShare）；落库到 Postgres（`app/models/market.py`，含 PIT 审计字段 `source`/`fetched_at`）。

配置 `REDIS_URL` 后，行情/指数快照、AI 配额和手动刷新冷却在 API 副本间共享；
worker 的私有成交事件通过 Redis Pub/Sub 扇出到持有用户 WebSocket 的 API 进程。
APScheduler 由可续租 Redis lease 选主，失去续租会立即停止本地 scheduler，其他 worker
可接管。dev/test 未配置 Redis 时自动使用原进程内实现；生产建议
`REDIS_REQUIRED=true`，Redis 异常会反映到 `/ready`。

```bash
# 创建/升级 schema（也可直接执行 alembic upgrade head）
python -m app.cli migrate

# 开发/CI 检查 ORM metadata 与当前 schema 是否漂移
alembic check

# 标的列表
python -m app.cli ingest-instruments

# 日K线（不复权）/ 复权因子 / 分钟K线
python -m app.cli ingest-daily  --code 600000.SH --start 2024-01-01 --end 2024-12-31
python -m app.cli ingest-adjust --code 600000.SH --start 2020-01-01 --end 2024-12-31
python -m app.cli ingest-minute --code 600000.SH --period 5 --start 2024-12-01 --end 2024-12-31

# 历史 ST 生效区间（默认 BaoStock，免费且无需 Token）
python -m app.cli ingest-status-history --code 600848.SH
# 批量回填自选股（也可用 --codes 显式指定）
python -m app.cli backfill-status-history
# 可选更丰富的名称变更源（需在 .env 配 TUSHARE_TOKEN）
python -m app.cli ingest-status-history --code 600848.SH --provider tushare

# 实时快照（不落库，验证连通性）
python -m app.cli quotes --codes 600000.SH,000001.SZ

# 龙虎榜（全市场，按日期范围）
python -m app.cli ingest-dragon-tiger --start 2025-01-01 --end 2025-12-31
```

调度器每日 16:05（Asia/Shanghai）也会自动落库近 7 日龙虎榜；个股详情「刷新数据」会顺带回填同期龙虎榜。

数据说明：日/分钟K线落库为**不复权**原始价，复权由 `adjust_factors` 表按需计算，以保证回测的时点正确性（PIT）。

历史风险警示由 `instrument_status_history` 保存生效区间。默认从 BaoStock 日线
`isST` 压缩为连续区间；可选 Tushare `namechange` 的完整单标的结果，调用时刻意不传
日期过滤条件，避免早期 `ann_date` 为空的有效区间被上游静默过滤。回测按每根 bar 的交易日查询当时状态：
主板 ST/*ST 使用 5%，创业板/科创板/北交所仍优先采用各自板块制度。未回填区间会在
`ruleQuality.historicalST` 标记为 `partial`/`unavailable`，不会拿当前简称倒灌历史。

财务摘要使用追加式 PIT 版本模型。规范化指标的 SHA-256 为 `vintage`；同一报告期
同值重抓只更新最近抓取审计且保留最早 `available_at`，指标变化则新增版本。数据源有
精确公告时间时优先使用 `announced_at`；仅有日期时标记 date 精度并保守到上海 15:00
可见；否则系统首次观察时间即 `available_at`。指标从 Provider 到 ingest 保持 Decimal，
按 ORM Numeric scale 量化、统一正负零后生成 vintage，不经过 binary float。
`GET /api/v1/market/financials?code=600000.SH&asOf=...` 可复原任一时点可见版本：
RFC3339 按其偏移转 UTC，无偏移时间按 `Asia/Shanghai`，`YYYY-MM-DD` 表示上海当日日末。
响应显式返回 `announcedAt` / `availableAt` / `availabilityQuality` / `source`；
AI `get_financials` 工具接受并复用相同的可选 `asOf`。

数据库 schema 由 Alembic 管理。Baseline 同时支持全新数据库和本分支前的历史
`create_all` 持久库；接管前会严格校验全部 legacy 表的列、类型、主键、唯一约束、外键、
命名 CHECK 约束、显式 server default 和必要索引，再补建本批新增的 `ingestion_runs`。
校验签名冻结在 baseline revision 中，不随未来 ORM metadata 变化；任何不匹配都会回滚且
不登记 revision。离线 `--sql` 输出仅适用于空库，不能接管已有库。
`python -m app.cli init-db` 仅为临时开发兼容入口，不用于部署。Baseline downgrade
明确禁用，避免误删全部生产表；回退请使用备份或经过评审的前向迁移。
财务 PIT 由前向 revision `20260717_0002` 安全重建并逐行复制旧表（旧行
`available_at=fetched_at`）；该 revision 的 downgrade 同样禁用，因为压平多个版本会丢失历史。
认证限流由前向 revision `20260717_0003` 新增 `auth_throttles` 表，不修改既有用户数据。
邮箱激活由 `20260717_0004` 增加 `users.email_verified_at` 与 `email_verifications`；
迁移时所有旧用户以 `email_verified_at=created_at` 标记为已验证，避免中断既有登录。

## 训练数据闭环

普通问答会话默认不采集训练轨迹。用户必须在生成前逐会话开启“允许本会话用于改进模型”；
只有完整落库的回答才保存不可逆脱敏后的输入、输出与工具轨迹。用户可随时撤回授权，
撤回会清空未冻结内容；若样本已进入数据集，则对应版本作废并删除 artifact。
个性化早报、深研、回测/模拟复盘和投资行为数据不进入首期闭环。

```bash
# 首次管理员引导：先只读检查并复制不可变 UUID；提升默认 dry-run
python -m app.cli admin inspect --email owner@example.com
python -m app.cli admin promote-existing \
  --email owner@example.com \
  --expected-user-id <inspect 返回的 UUID> \
  --expect-environment production
# 人工核对脱敏输出后，再增加 --apply；操作与审计记录同事务提交
python -m app.cli admin promote-existing \
  --email owner@example.com \
  --expected-user-id <inspect 返回的 UUID> \
  --expect-environment production --apply
python -m app.cli admin list

# 审计已由管理员批准的候选（PII、重复、格式、工具契约）
python -m app.cli training audit

# 查看是否达到 500 条总量、每类 50 条、validation 100 条的微调门槛
python -m app.cli training readiness

# 构建不可覆盖的版本化 train/validation JSONL
python -m app.cli training build --version dataset-2026-09-01
python -m app.cli training export --version dataset-2026-09-01

# 黄金集：结构校验；live 模式可输出 JSON/JUnit 并与基线比较
python scripts/ai_eval.py --offline
AI_EVAL_INPUT_COST_PER_MILLION=1 \
AI_EVAL_OUTPUT_COST_PER_MILLION=2 \
python scripts/ai_eval.py --json-output var/eval/current.json \
  --junit-output var/eval/current.xml \
  --baseline tests/reports/ai_eval_baseline_20260902.json
```

评测默认使用 checksum 固定的 `tests/fixtures/ai_eval/seed-ci-market-v1.json`，
并对每题做精确规范化工具参数和字段锚定事实校验；只有显式传 `--live-tools`
才访问当前数据库工具。真实价格必须按供应商账单配置，缺 token usage 或价格会直接阻断门禁。
黄金集现含 150 题，覆盖代码规范化、交易制度、PIT/复权、缺失数据、多工具、
提示注入、隐性荐股合规和回测边界。当前 150 题 DeepSeek 基线已固化为 JSON/JUnit；
它用于量化后续改进，不代表门禁已通过。首轮结果的工具准确率为 14.8%，应优先收紧
路由和参数提取，再考虑训练权重。
CI 只校验该“现状参考基线”的题目、fixture、usage 与价格完整性；模型晋级时必须让
新报告自身通过全部硬门禁，并可用
`--offline --baseline <candidate.json> --require-passing-baseline`
验证候选报告不可被失败基线冒充。

`TRAINING_ARTIFACT_DIR` 必须是非公开、仅服务进程可读写的持久目录。生产 Compose 使用
私有 `trainingdata` volume。应用不会把训练 artifact 上传到 DeepSeek、LangSmith、Sentry
或 embedding 服务；实际 SFT/LoRA 必须在独立审批后执行。

## WebSocket 行情推送（`/ws/v1`）

调度器把数据源刷新进内存缓存；一个异步推送循环每 `WS_PUSH_SECONDS`（默认 3s）把订阅主题的最新缓存推给客户端（只读缓存、不发起网络请求，故不阻塞）。

- 连接：`ws://localhost:8000/ws/v1`（可选 `?token=<ws JWT>`；浏览器经 `GET /auth/ws-ticket` 领取最长 120 秒短时票，普通 access JWT 不接受）
- 客户端 → 服务端：`{"type":"subscribe","payload":{"topics":[...]}}` / `unsubscribe` / `{"type":"ping"}`
- 服务端 → 客户端：`{"type":"update","topic","payload","timestamp"}` / `pong` / `subscribed` / `welcome` / `error`
- 主题：`market.indices`（指数概览）、`market.quote.<code>`（如 `market.quote.600000.SH`）

浏览器控制台快速验证：

```js
const ws = new WebSocket('ws://localhost:8000/ws/v1');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.onopen = () => ws.send(JSON.stringify({ type: 'subscribe', payload: { topics: ['market.indices', 'market.quote.600000.SH'] } }));
```

前端已提供 `src/lib/ws/marketSocket.ts`（自动重连/心跳）与 `src/hooks/useMarketSocket.ts`，Phase 1 看盘页直接复用。

## AI 看盘问答（DeepSeek 工具层，`POST /api/v1/ai/chat`）

DeepSeek 通过 function calling 调用工具（`get_market_overview` / `get_quotes` / `get_kline` / `search_instruments`）取**真实落库/缓存数据**作答，流式 SSE 输出。内置合规守卫：不杜撰、缺数据明说、不输出确定性买卖指令、附免责声明。

- 前置：`.env` 配置 `DEEPSEEK_API_KEY`；浏览器经同源 Cookie 鉴权，脚本可用 Bearer access token。
- 响应：`text/event-stream`，每帧 `data: {"delta": "..."}`，结束 `data: [DONE]`。

```bash
# Cookie 会话（浏览器同源 /api/v1）或脚本 Bearer
curl -N -X POST localhost:8000/api/v1/ai/chat \
  -H "Authorization: Bearer <access-token>" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"上证指数现在多少？600000 今天表现如何？"}]}'
```

