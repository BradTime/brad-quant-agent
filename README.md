# 量化投资 Agent 平台

基于人工智能的量化投资决策支持系统。

## 技术栈

- **框架**: Next.js 15.x (App Router)
- **UI 库**: React 19.x
- **组件库**: shadcn/ui
- **语言**: TypeScript 5.x
- **样式**: Tailwind CSS 4.x
- **状态管理**: 
  - Zustand 4.x+ (全局状态)
  - @tanstack/react-query 5.x (服务器状态)
- **数据可视化**: ECharts 5.x+ (待实现)

## 项目结构

```
src/
├── app/                    # Next.js App Router 页面
│   ├── (auth)/             # 认证相关页面（路由组）
│   │   ├── login/          # 登录页面
│   │   └── register/       # 注册页面
│   ├── dashboard/          # 仪表盘
│   ├── error.tsx          # 错误页面
│   ├── not-found.tsx      # 404 页面
│   └── layout.tsx          # 根布局
├── components/             # 通用组件
│   ├── ui/                 # 基础 UI 组件 (shadcn/ui)
│   ├── auth/               # 认证相关组件
│   └── layout/              # 布局组件
├── lib/                    # 工具函数
│   ├── api/                # API 调用
│   ├── utils/              # 工具函数
│   ├── constants/          # 常量定义
│   └── react-query/         # React Query 配置
├── stores/                 # 状态管理（Zustand）
├── hooks/                  # 自定义 Hooks
└── types/                  # TypeScript 类型定义
```

## 开发指南

### 环境设置

1. 复制环境变量文件：
```bash
cp .env.example .env.local
```

2. 安装依赖：
```bash
npm install
```

3. 启动开发服务器：
```bash
npm run dev
```

### 主要功能

#### Phase 1: 基础架构搭建 ✅

- [x] 项目初始化与配置
- [x] shadcn/ui 组件库搭建
- [x] 路由配置
- [x] 状态管理搭建（Zustand + React Query）
- [x] API 封装
- [x] 认证系统实现
- [x] 错误边界和错误页面

#### Phase 2: 核心功能开发（进行中）

- [ ] 仪表盘开发
- [ ] 策略管理模块
- [ ] 回测分析模块
- [ ] 基础数据可视化

## 开发规范

### 代码规范

- 使用 ESLint 和 Prettier 进行代码格式化
- 遵循 TypeScript 严格模式
- 组件使用 PascalCase 命名
- 函数/变量使用 camelCase 命名

### Git 提交规范

遵循 Conventional Commits 规范：
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具链相关

## 环境变量

- `NEXT_PUBLIC_API_BASE_URL`: API 基础路径
- `NEXT_PUBLIC_WS_BASE_URL`: WebSocket 基础路径

## 许可证

MIT
