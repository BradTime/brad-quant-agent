import { Router } from 'express';
import { db } from '../utils/db';
import { successResponse, errorResponse } from '../utils/response';
import { authMiddleware, type AuthRequest } from '../middleware/auth';

const router = Router();

router.use(authMiddleware);

// 获取仪表盘统计数据
router.get('/stats', async (req: AuthRequest, res) => {
  try {
    const strategies = db.strategies.findByUserId(req.userId!);
    const activeStrategies = strategies.filter((s) => s.status === 'active');

    // 模拟数据
    const stats = {
      totalAssets: 1000000,
      todayReturn: Math.random() * 10000 - 5000,
      todayReturnPercent: Math.random() * 5 - 2.5,
      cumulativeReturn: Math.random() * 50000 - 25000,
      cumulativeReturnPercent: Math.random() * 25 - 12.5,
      runningStrategies: activeStrategies.length,
      totalStrategies: strategies.length,
    };

    successResponse(res, stats);
  } catch (error) {
    errorResponse(res, '获取统计数据失败', 500, 500);
  }
});

// 获取市场概览（从东方财富获取实时数据）
router.get('/market-overview', async (req: AuthRequest, res) => {
  try {
    const { getIndexData } = await import('../services/eastmoney');
    const indexData = await getIndexData();

    const overview = indexData.map((item) => ({
      index: item.code,
      name: item.name,
      value: item.price,
      change: item.change,
      changePercent: item.changePercent,
    }));

    successResponse(res, overview);
  } catch (error) {
    console.error('获取市场概览失败:', error);
    errorResponse(res, '获取市场概览失败', 500, 500);
  }
});

// 获取最近交易记录
router.get('/recent-trades', async (req: AuthRequest, res) => {
  try {
    const limit = parseInt(req.query.limit as string, 10) || 10;

    // 模拟交易数据
    const trades = Array.from({ length: limit }, (_, i) => ({
      id: `trade-${i + 1}`,
      symbol: `00000${i + 1}`,
      name: `股票${i + 1}`,
      side: Math.random() > 0.5 ? 'buy' : 'sell',
      quantity: Math.floor(Math.random() * 1000) + 100,
      price: Math.random() * 100 + 10,
      timestamp: new Date(Date.now() - i * 3600000).toISOString(),
    }));

    successResponse(res, trades);
  } catch (error) {
    errorResponse(res, '获取交易记录失败', 500, 500);
  }
});

// 获取持仓分布
router.get('/position-distribution', async (req: AuthRequest, res) => {
  try {
    // 模拟持仓数据
    const positions = [
      {
        symbol: '000001',
        name: '平安银行',
        value: 150000,
        percent: 15,
        cost: 10.5,
        currentPrice: 11.2,
        return: 7000,
        returnPercent: 4.67,
      },
      {
        symbol: '000002',
        name: '万科A',
        value: 200000,
        percent: 20,
        cost: 8.5,
        currentPrice: 9.1,
        return: 14000,
        returnPercent: 7.06,
      },
      {
        symbol: '600000',
        name: '浦发银行',
        value: 250000,
        percent: 25,
        cost: 7.8,
        currentPrice: 8.2,
        return: 12800,
        returnPercent: 5.13,
      },
      {
        symbol: '600036',
        name: '招商银行',
        value: 400000,
        percent: 40,
        cost: 45.2,
        currentPrice: 48.5,
        return: 29100,
        returnPercent: 7.28,
      },
    ];

    successResponse(res, positions);
  } catch (error) {
    errorResponse(res, '获取持仓分布失败', 500, 500);
  }
});

// 获取收益曲线
router.get('/return-curve', async (req: AuthRequest, res) => {
  try {
    const days = parseInt(req.query.days as string, 10) || 30;
    const curve = [];

    let baseValue = 1000000;
    for (let i = days; i >= 0; i--) {
      const date = new Date();
      date.setDate(date.getDate() - i);
      const change = (Math.random() - 0.5) * 20000;
      baseValue += change;
      const returnPercent = ((baseValue - 1000000) / 1000000) * 100;

      curve.push({
        date: date.toISOString().split('T')[0],
        value: returnPercent,
        benchmark: returnPercent * (0.8 + Math.random() * 0.4), // 模拟基准收益
      });
    }

    successResponse(res, curve);
  } catch (error) {
    errorResponse(res, '获取收益曲线失败', 500, 500);
  }
});

export default router;

