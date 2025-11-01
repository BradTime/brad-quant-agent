import { Router } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { db } from '../utils/db';
import { hashPassword, comparePassword, generateToken } from '../utils/auth';
import { successResponse, errorResponse } from '../utils/response';
import type { AuthRequest } from '../middleware/auth';

const router = Router();

// 注册
router.post('/register', async (req, res) => {
  try {
    const { email, password, name } = req.body;

    if (!email || !password || !name) {
      errorResponse(res, '邮箱、密码和姓名不能为空', 10001, 400);
      return;
    }

    // 检查用户是否已存在
    if (db.users.findByEmail(email)) {
      errorResponse(res, '该邮箱已被注册', 10002, 409);
      return;
    }

    // 创建用户
    const user = db.users.create({
      id: uuidv4(),
      email,
      password: hashPassword(password),
      name,
      role: 'user',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    // 生成 Token
    const token = generateToken({ userId: user.id, email: user.email });
    const refreshToken = generateToken({ userId: user.id, email: user.email });

    // 返回用户信息（不包含密码）
    const { password: _, ...userWithoutPassword } = user;

    successResponse(
      res,
      {
        user: userWithoutPassword,
        token,
        refreshToken,
      },
      '注册成功'
    );
  } catch (error) {
    errorResponse(res, '注册失败', 10003, 500);
  }
});

// 登录
router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      errorResponse(res, '邮箱和密码不能为空', 10001, 400);
      return;
    }

    const user = db.users.findByEmail(email);
    if (!user || !comparePassword(password, user.password)) {
      errorResponse(res, '邮箱或密码错误', 10004, 401);
      return;
    }

    // 生成 Token
    const token = generateToken({ userId: user.id, email: user.email });
    const refreshToken = generateToken({ userId: user.id, email: user.email });

    // 返回用户信息（不包含密码）
    const { password: _, ...userWithoutPassword } = user;

    successResponse(
      res,
      {
        user: userWithoutPassword,
        token,
        refreshToken,
      },
      '登录成功'
    );
  } catch (error) {
    errorResponse(res, '登录失败', 10005, 500);
  }
});

// 获取当前用户信息
router.get('/me', async (req: AuthRequest, res) => {
  try {
    if (!req.userId) {
      errorResponse(res, '未授权', 401, 401);
      return;
    }

    const user = db.users.findById(req.userId);
    if (!user) {
      errorResponse(res, '用户不存在', 404, 404);
      return;
    }

    const { password: _, ...userWithoutPassword } = user;
    successResponse(res, userWithoutPassword);
  } catch (error) {
    errorResponse(res, '获取用户信息失败', 10006, 500);
  }
});

// 登出
router.post('/logout', async (req, res) => {
  // 由于使用 JWT，登出主要在客户端删除 Token
  successResponse(res, null, '登出成功');
});

// 刷新 Token
router.post('/refresh', async (req, res) => {
  try {
    const { refreshToken } = req.body;
    if (!refreshToken) {
      errorResponse(res, 'refreshToken 不能为空', 10001, 400);
      return;
    }

    // 验证 refreshToken（这里简化处理，实际应该单独存储 refreshToken）
    const { verifyToken } = await import('../utils/auth');
    const decoded = verifyToken(refreshToken);

    if (!decoded) {
      errorResponse(res, 'refreshToken 无效', 10007, 401);
      return;
    }

    const newToken = generateToken({ userId: decoded.userId, email: decoded.email });
    const newRefreshToken = generateToken({ userId: decoded.userId, email: decoded.email });

    successResponse(res, {
      token: newToken,
      refreshToken: newRefreshToken,
    });
  } catch (error) {
    errorResponse(res, '刷新 Token 失败', 10008, 500);
  }
});

export default router;

