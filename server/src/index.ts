import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import authRoutes from './routes/auth';
import strategiesRoutes from './routes/strategies';
import dashboardRoutes from './routes/dashboard';
import backtestRoutes from './routes/backtest';
import marketRoutes from './routes/market';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 3001;

// 中间件
app.use(cors({
  origin: process.env.CORS_ORIGIN || 'http://localhost:3000',
  credentials: true,
}));
app.use(express.json());

// 健康检查
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// API 路由
app.use('/api/v1/auth', authRoutes);
app.use('/api/v1/strategies', strategiesRoutes);
app.use('/api/v1/dashboard', dashboardRoutes);
app.use('/api/v1/backtest', backtestRoutes);
app.use('/api/v1/market', marketRoutes);

// 404 处理
app.use((req, res) => {
  res.status(404).json({
    code: 404,
    message: '接口不存在',
    data: null,
    timestamp: Date.now(),
  });
});

// 错误处理
app.use((err: Error, req: express.Request, res: express.Response, next: express.NextFunction) => {
  console.error('Server error:', err);
  res.status(500).json({
    code: 500,
    message: '服务器内部错误',
    data: null,
    timestamp: Date.now(),
  });
});

app.listen(PORT, () => {
  console.log(`🚀 后端服务已启动`);
  console.log(`📍 服务地址: http://localhost:${PORT}`);
  console.log(`📚 API 文档: http://localhost:${PORT}/api/v1`);
  console.log(`💚 健康检查: http://localhost:${PORT}/health`);
});

