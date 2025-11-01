import { Router } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../utils/db';
import { successResponse, errorResponse } from '../utils/response';
import { authMiddleware, type AuthRequest } from '../middleware/auth';

const router = Router();

router.use(authMiddleware);

// 执行回测
router.post('/run', async (req: AuthRequest, res) => {
  try {
    const { strategyId, startDate, endDate, initialCapital, commission, slippage, dataSource } =
      req.body;

    if (!strategyId || !startDate || !endDate || !initialCapital) {
      errorResponse(res, '回测配置不完整', 10201, 400);
      return;
    }

    // 检查策略是否存在
    const strategy = db.strategies.findById(strategyId);
    if (!strategy || strategy.userId !== req.userId) {
      errorResponse(res, '策略不存在或无权限', 404, 404);
      return;
    }

    // 创建回测结果（模拟）
    const backtestId = uuidv4();
    const result = {
      id: backtestId,
      strategyId,
      config: {
        strategyId,
        startDate,
        endDate,
        initialCapital,
        commission: commission || 0.001,
        slippage: slippage || 0.001,
        dataSource,
      },
      status: 'running' as const,
      createdAt: new Date().toISOString(),
      // 模拟回测结果（实际应该异步计算）
      metrics: {
        totalReturn: Math.random() * 50000 - 25000,
        totalReturnPercent: Math.random() * 25 - 12.5,
        annualReturn: Math.random() * 20000 - 10000,
        annualReturnPercent: Math.random() * 20 - 10,
        sharpeRatio: Math.random() * 2,
        sortinoRatio: Math.random() * 2.5,
        maxDrawdown: Math.random() * 10000,
        maxDrawdownPercent: Math.random() * 10,
        winRate: Math.random() * 0.3 + 0.5,
        profitFactor: Math.random() * 2,
        averageWin: Math.random() * 5000,
        averageLoss: Math.random() * 3000,
        totalTrades: Math.floor(Math.random() * 100) + 50,
        winningTrades: Math.floor(Math.random() * 50) + 25,
        losingTrades: Math.floor(Math.random() * 50) + 10,
      },
      equityCurve: [] as Array<{ date: string; equity: number; return: number; returnPercent: number }>,
      trades: [] as Array<{
        id: string;
        symbol: string;
        side: 'buy' | 'sell';
        quantity: number;
        entryPrice: number;
        exitPrice: number;
        entryTime: string;
        exitTime: string;
        return: number;
        returnPercent: number;
        commission: number;
      }>,
    };

    // 生成模拟资产曲线
    const start = new Date(startDate);
    const end = new Date(endDate);
    const days = Math.floor((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
    let equity = initialCapital;

    for (let i = 0; i <= days; i++) {
      const date = new Date(start);
      date.setDate(date.getDate() + i);
      equity += (Math.random() - 0.5) * initialCapital * 0.02;
      result.equityCurve.push({
        date: date.toISOString().split('T')[0],
        equity,
        return: equity - initialCapital,
        returnPercent: ((equity - initialCapital) / initialCapital) * 100,
      });
    }

    // 模拟：延迟后标记为完成
    setTimeout(() => {
      result.status = 'completed';
      result.completedAt = new Date().toISOString();
      // 这里应该保存到数据库，但为了简化，我们只是返回
    }, 2000);

    successResponse(res, result, '回测已启动', 202);
  } catch (error) {
    errorResponse(res, '执行回测失败', 10202, 500);
  }
});

// 获取回测结果
router.get('/:id', async (req: AuthRequest, res) => {
  try {
    // 模拟回测结果（实际应该从数据库读取）
    const backtestId = req.params.id;

    // 这里简化处理，实际应该从数据库读取
    // 为了演示，我们返回一个模拟结果
    const result = {
      id: backtestId,
      strategyId: 'strategy-1',
      config: {
        strategyId: 'strategy-1',
        startDate: '2024-01-01',
        endDate: '2024-12-01',
        initialCapital: 100000,
        commission: 0.001,
        slippage: 0.001,
      },
      status: 'completed' as const,
      createdAt: new Date().toISOString(),
      completedAt: new Date().toISOString(),
      metrics: {
        totalReturn: 25000,
        totalReturnPercent: 25,
        annualReturn: 30000,
        annualReturnPercent: 30,
        sharpeRatio: 1.5,
        sortinoRatio: 2.0,
        maxDrawdown: 5000,
        maxDrawdownPercent: 5,
        winRate: 0.6,
        profitFactor: 1.8,
        averageWin: 3000,
        averageLoss: 2000,
        totalTrades: 100,
        winningTrades: 60,
        losingTrades: 40,
      },
      equityCurve: [] as Array<{ date: string; equity: number; return: number; returnPercent: number }>,
      trades: [],
    };

    // 生成模拟资产曲线
    const days = 365;
    const initialCapital = result.config.initialCapital;
    let equity = initialCapital;

    for (let i = 0; i <= days; i++) {
      const date = new Date(result.config.startDate);
      date.setDate(date.getDate() + i);
      equity += (Math.random() - 0.45) * initialCapital * 0.015; // 略微正收益
      result.equityCurve.push({
        date: date.toISOString().split('T')[0],
        equity,
        return: equity - initialCapital,
        returnPercent: ((equity - initialCapital) / initialCapital) * 100,
      });
    }

    successResponse(res, result);
  } catch (error) {
    errorResponse(res, '获取回测结果失败', 10203, 500);
  }
});

// 获取回测指标
router.get('/:id/metrics', async (req: AuthRequest, res) => {
  try {
    // 简化处理，返回模拟数据
    const metrics = {
      totalReturn: 25000,
      totalReturnPercent: 25,
      annualReturn: 30000,
      annualReturnPercent: 30,
      sharpeRatio: 1.5,
      sortinoRatio: 2.0,
      maxDrawdown: 5000,
      maxDrawdownPercent: 5,
      winRate: 0.6,
      profitFactor: 1.8,
      averageWin: 3000,
      averageLoss: 2000,
      totalTrades: 100,
      winningTrades: 60,
      losingTrades: 40,
    };

    successResponse(res, metrics);
  } catch (error) {
    errorResponse(res, '获取回测指标失败', 10204, 500);
  }
});

// 获取回测报告
router.get('/:id/report', async (req: AuthRequest, res) => {
  try {
    // 简化处理，返回模拟报告
    const report = {
      id: req.params.id,
      summary: '回测报告摘要',
      details: '详细的回测分析报告...',
    };

    successResponse(res, report);
  } catch (error) {
    errorResponse(res, '获取回测报告失败', 10205, 500);
  }
});

// 导出回测报告
router.post('/:id/export', async (req: AuthRequest, res) => {
  try {
    const { format } = req.body;
    // 简化处理
    successResponse(res, { message: `报告已导出为 ${format} 格式` });
  } catch (error) {
    errorResponse(res, '导出报告失败', 10206, 500);
  }
});

export default router;

