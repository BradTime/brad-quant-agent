import { Router } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../utils/db';
import { successResponse, errorResponse } from '../utils/response';
import { authMiddleware, type AuthRequest } from '../middleware/auth';

const router = Router();

// 所有策略路由都需要认证
router.use(authMiddleware);

// 获取策略列表
router.get('/', async (req: AuthRequest, res) => {
  try {
    const {
      page = '1',
      pageSize = '10',
      status,
      type,
      search,
      sortBy = 'updatedAt',
      sortOrder = 'desc',
    } = req.query;

    let strategies = db.strategies.findByUserId(req.userId!);

    // 筛选
    if (status) {
      strategies = strategies.filter((s) => s.status === status);
    }
    if (type) {
      strategies = strategies.filter((s) => s.type === type);
    }
    if (search) {
      const searchLower = (search as string).toLowerCase();
      strategies = strategies.filter(
        (s) =>
          s.name.toLowerCase().includes(searchLower) ||
          s.description?.toLowerCase().includes(searchLower)
      );
    }

    // 排序
    strategies.sort((a, b) => {
      let aVal: number;
      let bVal: number;

      if (sortBy === 'createdAt' || sortBy === 'updatedAt') {
        aVal = new Date(a[sortBy] as string).getTime();
        bVal = new Date(b[sortBy] as string).getTime();
      } else if (sortBy === 'totalReturn') {
        aVal = (a.performance?.totalReturnPercent || 0);
        bVal = (b.performance?.totalReturnPercent || 0);
      } else {
        aVal = 0;
        bVal = 0;
      }

      return sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
    });

    // 分页
    const pageNum = parseInt(page as string, 10);
    const size = parseInt(pageSize as string, 10);
    const start = (pageNum - 1) * size;
    const end = start + size;

    successResponse(res, {
      items: strategies.slice(start, end),
      total: strategies.length,
    });
  } catch (error) {
    errorResponse(res, '获取策略列表失败', 10101, 500);
  }
});

// 获取策略详情
router.get('/:id', async (req: AuthRequest, res) => {
  try {
    const strategy = db.strategies.findById(req.params.id);

    if (!strategy) {
      errorResponse(res, '策略不存在', 404, 404);
      return;
    }

    // 检查权限：只能查看自己的策略
    if (strategy.userId !== req.userId) {
      errorResponse(res, '无权限访问', 403, 403);
      return;
    }

    successResponse(res, strategy);
  } catch (error) {
    errorResponse(res, '获取策略详情失败', 10102, 500);
  }
});

// 创建策略
router.post('/', async (req: AuthRequest, res) => {
  try {
    const { name, description, type, params, code } = req.body;

    if (!name || !type) {
      errorResponse(res, '策略名称和类型不能为空', 10103, 400);
      return;
    }

    const strategy = db.strategies.create({
      id: uuidv4(),
      name,
      description,
      type,
      status: 'draft',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      userId: req.userId!,
      params: params || {},
      code: code || '',
    });

    successResponse(res, strategy, '策略创建成功', 201);
  } catch (error) {
    errorResponse(res, '创建策略失败', 10104, 500);
  }
});

// 更新策略
router.put('/:id', async (req: AuthRequest, res) => {
  try {
    const strategy = db.strategies.findById(req.params.id);

    if (!strategy) {
      errorResponse(res, '策略不存在', 404, 404);
      return;
    }

    if (strategy.userId !== req.userId) {
      errorResponse(res, '无权限修改', 403, 403);
      return;
    }

    const { name, description, type, params, code } = req.body;
    const updated = db.strategies.update(req.params.id, {
      name,
      description,
      type,
      params,
      code,
    });

    if (!updated) {
      errorResponse(res, '更新失败', 10105, 500);
      return;
    }

    successResponse(res, updated, '策略更新成功');
  } catch (error) {
    errorResponse(res, '更新策略失败', 10106, 500);
  }
});

// 删除策略
router.delete('/:id', async (req: AuthRequest, res) => {
  try {
    const strategy = db.strategies.findById(req.params.id);

    if (!strategy) {
      errorResponse(res, '策略不存在', 404, 404);
      return;
    }

    if (strategy.userId !== req.userId) {
      errorResponse(res, '无权限删除', 403, 403);
      return;
    }

    db.strategies.delete(req.params.id);
    successResponse(res, null, '策略删除成功');
  } catch (error) {
    errorResponse(res, '删除策略失败', 10107, 500);
  }
});

// 启用策略
router.post('/:id/enable', async (req: AuthRequest, res) => {
  try {
    const strategy = db.strategies.findById(req.params.id);

    if (!strategy) {
      errorResponse(res, '策略不存在', 404, 404);
      return;
    }

    if (strategy.userId !== req.userId) {
      errorResponse(res, '无权限操作', 403, 403);
      return;
    }

    const updated = db.strategies.update(req.params.id, { status: 'active' });
    successResponse(res, updated, '策略已启用');
  } catch (error) {
    errorResponse(res, '启用策略失败', 10108, 500);
  }
});

// 停用策略
router.post('/:id/disable', async (req: AuthRequest, res) => {
  try {
    const strategy = db.strategies.findById(req.params.id);

    if (!strategy) {
      errorResponse(res, '策略不存在', 404, 404);
      return;
    }

    if (strategy.userId !== req.userId) {
      errorResponse(res, '无权限操作', 403, 403);
      return;
    }

    const updated = db.strategies.update(req.params.id, { status: 'paused' });
    successResponse(res, updated, '策略已停用');
  } catch (error) {
    errorResponse(res, '停用策略失败', 10109, 500);
  }
});

// 复制策略
router.post('/:id/duplicate', async (req: AuthRequest, res) => {
  try {
    const strategy = db.strategies.findById(req.params.id);

    if (!strategy) {
      errorResponse(res, '策略不存在', 404, 404);
      return;
    }

    const newStrategy = db.strategies.create({
      ...strategy,
      id: uuidv4(),
      name: `${strategy.name} (副本)`,
      status: 'draft',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      userId: req.userId!,
    });

    successResponse(res, newStrategy, '策略复制成功', 201);
  } catch (error) {
    errorResponse(res, '复制策略失败', 10110, 500);
  }
});

export default router;

