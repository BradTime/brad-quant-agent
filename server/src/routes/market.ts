import { Router } from 'express';
import { successResponse, errorResponse } from '../utils/response';
import { authMiddleware, type AuthRequest } from '../middleware/auth';
import { getIndexData, getPopularStocks, getAllStocks } from '../services/eastmoney';

const router = Router();

router.use(authMiddleware);

// 获取市场行情（所有股票，支持分页和排序）
router.get('/quotes', async (req: AuthRequest, res) => {
  try {
    const page = parseInt(req.query.page as string, 10) || 1;
    const pageSize = parseInt(req.query.pageSize as string, 10) || 20;
    const sortBy = (req.query.sortBy as 'price' | 'changePercent' | 'volume') || 'price';
    const sortOrder = (req.query.sortOrder as 'asc' | 'desc') || 'desc';

    // 如果请求的是所有股票（分页），使用新的API
    const result = await getAllStocks(page, pageSize, sortBy, sortOrder);

    successResponse(res, result);
  } catch (error) {
    console.error('获取市场行情失败:', error);
    errorResponse(res, '获取市场行情失败', 500, 500);
  }
});

// 获取热门股票（保留用于向后兼容，最多20只）
router.get('/quotes/popular', async (req: AuthRequest, res) => {
  try {
    const limit = parseInt(req.query.limit as string, 10) || 20;
    const stocks = await getPopularStocks(limit);

    successResponse(res, stocks);
  } catch (error) {
    console.error('获取热门股票失败:', error);
    errorResponse(res, '获取热门股票失败', 500, 500);
  }
});

// 获取指数数据
router.get('/indexes', async (req: AuthRequest, res) => {
  try {
    const indexes = await getIndexData();
    successResponse(res, indexes);
  } catch (error) {
    console.error('获取指数数据失败:', error);
    errorResponse(res, '获取指数数据失败', 500, 500);
  }
});

// 获取K线数据
router.get('/kline', async (req: AuthRequest, res) => {
  try {
    const { symbol, period = 'day', count = 100 } = req.query;

    if (!symbol) {
      errorResponse(res, '股票代码不能为空', 400, 400);
      return;
    }

    // 简化处理：返回模拟K线数据
    // 实际应该从东方财富API获取K线数据
    const klineData = Array.from({ length: parseInt(count as string, 10) }, (_, i) => {
      const date = new Date();
      date.setDate(date.getDate() - (parseInt(count as string, 10) - i));
      const basePrice = 10 + Math.random() * 20;
      const change = (Math.random() - 0.5) * 2;
      
      return {
        time: date.toISOString().split('T')[0],
        open: basePrice,
        high: basePrice + Math.abs(change) + Math.random(),
        low: basePrice - Math.abs(change) - Math.random(),
        close: basePrice + change,
        volume: Math.floor(Math.random() * 1000000),
      };
    });

    successResponse(res, klineData);
  } catch (error) {
    console.error('获取K线数据失败:', error);
    errorResponse(res, '获取K线数据失败', 500, 500);
  }
});

export default router;

