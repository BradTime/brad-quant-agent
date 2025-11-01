# 量化投资 Agent 平台 - 后端服务

基于 Express + TypeScript 的后端 API 服务，集成东方财富API获取A股实时数据。

## 技术栈

- **框架**: Express.js
- **语言**: TypeScript
- **数据存储**: JSON 文件（开发环境，可替换为数据库）
- **认证**: JWT (JSON Web Token)
- **密码加密**: bcryptjs
- **数据源**: 东方财富API（A股实时行情）

## 快速开始

### 1. 安装依赖

```bash
cd server
npm install
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`（如果不存在会自动使用默认值）：

```bash
PORT=3001
JWT_SECRET=your-secret-key-change-in-production
JWT_EXPIRES_IN=7d
CORS_ORIGIN=http://localhost:3000
```

### 3. 启动服务

**开发模式**（自动重启）:
```bash
npm run dev
```

**生产模式**:
```bash
npm run build
npm start
```

## API 端点

### 认证相关
- `POST /api/v1/auth/register` - 用户注册
- `POST /api/v1/auth/login` - 用户登录
- `GET /api/v1/auth/me` - 获取当前用户信息
- `POST /api/v1/auth/logout` - 用户登出
- `POST /api/v1/auth/refresh` - 刷新 Token

### 策略管理
- `GET /api/v1/strategies` - 获取策略列表
- `POST /api/v1/strategies` - 创建策略
- `GET /api/v1/strategies/:id` - 获取策略详情
- `PUT /api/v1/strategies/:id` - 更新策略
- `DELETE /api/v1/strategies/:id` - 删除策略
- `POST /api/v1/strategies/:id/enable` - 启用策略
- `POST /api/v1/strategies/:id/disable` - 停用策略
- `POST /api/v1/strategies/:id/duplicate` - 复制策略

### 仪表盘
- `GET /api/v1/dashboard/stats` - 获取统计数据
- `GET /api/v1/dashboard/market-overview` - 获取市场概览（**实时从东方财富获取**）
- `GET /api/v1/dashboard/recent-trades` - 获取最近交易
- `GET /api/v1/dashboard/position-distribution` - 获取持仓分布
- `GET /api/v1/dashboard/return-curve` - 获取收益曲线

### 市场行情（新增 - 东方财富API）
- `GET /api/v1/market/quotes` - 获取A股实时行情（热门股票）
- `GET /api/v1/market/indexes` - 获取A股指数数据（上证、深证、创业板）
- `GET /api/v1/market/kline` - 获取K线数据

### 回测分析
- `POST /api/v1/backtest/run` - 执行回测
- `GET /api/v1/backtest/:id` - 获取回测结果
- `GET /api/v1/backtest/:id/metrics` - 获取回测指标
- `GET /api/v1/backtest/:id/report` - 获取回测报告
- `POST /api/v1/backtest/:id/export` - 导出回测报告

## 东方财富API集成

后端已集成东方财富API，用于获取A股实时行情数据：

- **数据源**: `https://push2.eastmoney.com/api/qt/ulist.np/get`
- **支持功能**:
  - A股指数实时数据（上证指数、深证成指、创业板指）
  - 热门股票实时行情
  - 股票价格、涨跌幅、成交量、成交额等

**注意**: 
- API请求频率应控制在合理范围内，避免被封禁
- 如果API调用失败，会自动降级到模拟数据
- 建议在生产环境中添加请求限流和缓存机制

## 数据存储

当前使用 JSON 文件存储数据（`server/data/` 目录）：
- `users.json` - 用户数据
- `strategies.json` - 策略数据

**注意**: 生产环境建议使用数据库（PostgreSQL、MySQL 等）。

## 健康检查

访问 `http://localhost:3001/health` 检查服务状态。

## 开发说明

- 使用 `tsx` 在开发模式下运行 TypeScript 文件
- 数据存储在 `server/data/` 目录（JSON 文件）
- 所有需要认证的接口都需要在请求头中携带 `Authorization: Bearer <token>`
- 市场数据每5-10秒自动刷新（通过前端React Query轮询）
