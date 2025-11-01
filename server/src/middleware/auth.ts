import type { Request, Response, NextFunction } from 'express';
import { verifyToken } from '../utils/auth';
import { errorResponse } from '../utils/response';

export interface AuthRequest extends Request {
  userId?: string;
  userEmail?: string;
}

export function authMiddleware(req: AuthRequest, res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;

  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    errorResponse(res, '未授权，请先登录', 401, 401);
    return;
  }

  const token = authHeader.substring(7);
  const decoded = verifyToken(token);

  if (!decoded) {
    errorResponse(res, 'Token 无效或已过期', 401, 401);
    return;
  }

  req.userId = decoded.userId;
  req.userEmail = decoded.email;
  next();
}

