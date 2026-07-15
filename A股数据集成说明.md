# A股实时数据集成说明

## ✅ 已实现功能

### 1. 后端服务集成东方财富API

**服务位置**: `server/src/services/eastmoney.ts`

**功能**:
- ✅ 获取A股指数数据（上证指数、深证成指、创业板指）
- ✅ 获取热门股票实时行情
- ✅ 支持自定义股票代码查询
- ✅ API失败时自动降级到模拟数据

**API端点**:
- `GET /api/v1/market/indexes` - 获取指数数据
- `GET /api/v1/market/quotes?limit=20` - 获取热门股票行情

### 2. 前端仪表盘实时显示

**页面位置**: `src/app/dashboard/page.tsx`

**显示内容**:
1. **A股指数卡片** - 显示上证指数、深证成指、创业板指
   - 实时价格
   - 涨跌幅（颜色区分：上涨绿色，下跌红色）
   - 每10秒自动刷新

2. **A股实时行情表格** - 显示热门股票列表
   - 股票代码和名称
   - 实时价格
   - 涨跌金额和涨跌幅
   - 成交量（万手）
   - 成交额（亿元）
   - 每5秒自动刷新
   - 支持手动刷新按钮

### 3. 实时刷新机制

使用 React Query 的 `refetchInterval` 实现自动刷新：

- **指数数据**: 每10秒刷新一次
- **股票行情**: 每5秒刷新一次
- **统计数据**: 每30秒刷新一次

## 📊 数据来源

**东方财富API**:
- 基础URL: `https://push2.eastmoney.com/api/qt/ulist.np/get`
- 数据字段:
  - `f2`: 最新价
  - `f3`: 涨跌幅百分比
  - `f4`: 涨跌金额
  - `f5`: 成交量
  - `f6`: 成交额
  - `f12`: 股票代码
  - `f14`: 股票名称
  - `f15-f18`: 最高、最低、开盘、昨收

## 🚀 使用方法

### 1. 启动后端服务

```bash
cd server
npm run dev
```

后端服务将在 `http://localhost:8000` 启动

### 2. 启动前端服务

```bash
npm run dev
```

前端服务将在 `http://localhost:3000` 启动

### 3. 访问仪表盘

1. 登录系统（如未登录会自动跳转）
2. 登录后自动进入仪表盘页面
3. 可以看到：
   - **A股指数**卡片（顶部）
   - **A股实时行情**表格（显示热门股票）
   - 数据会自动刷新

## ⚠️ 注意事项

1. **API限流**: 
   - 东方财富API有请求频率限制
   - 当前设置为每5-10秒刷新一次，避免过于频繁
   - 如遇到限制，会自动降级到模拟数据

2. **网络问题**:
   - 如果无法访问东方财富API，会显示模拟数据
   - 可在浏览器控制台查看错误日志

3. **数据准确性**:
   - 实时数据来自东方财富官方API
   - 仅供参考，不构成投资建议

4. **缓存机制**:
   - 使用 React Query 进行数据缓存
   - 减少不必要的API请求

## 🔧 自定义配置

### 修改刷新频率

在 `src/app/dashboard/page.tsx` 中修改 `refetchInterval`:

```typescript
// 股票行情：改为每3秒刷新
refetchInterval: 3000,

// 指数数据：改为每5秒刷新
refetchInterval: 5000,
```

### 修改显示股票数量

在仪表盘页面中调用 API 时修改 limit 参数：

```typescript
const { data: stockQuotes } = useQuery({
  queryKey: ['market', 'quotes'],
  queryFn: () => marketApi.getQuotes(30), // 改为显示30只股票
});
```

### 添加更多股票

在 `server/src/services/eastmoney.ts` 的 `getPopularStocks` 函数中添加股票代码：

```typescript
const popularCodes = [
  '1.600000', // 添加更多股票代码
  // ...
];
```

## 📝 后续优化建议

1. **WebSocket实时推送**: 
   - 替换轮询机制为WebSocket
   - 实现真正的实时数据推送

2. **数据缓存**:
   - 在后端添加Redis缓存
   - 减少对东方财富API的请求频率

3. **更多股票信息**:
   - 添加K线图显示
   - 添加技术指标计算
   - 添加个股详情页面

4. **数据持久化**:
   - 将历史行情数据存储到数据库
   - 支持历史数据查询和分析

