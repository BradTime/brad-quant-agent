import type { Response } from 'express';
import type { ApiResponse } from '../types';

export function successResponse<T>(res: Response, data: T, message = 'success', code = 200): void {
  const response: ApiResponse<T> = {
    code,
    message,
    data,
    timestamp: Date.now(),
  };
  res.status(code).json(response);
}

export function errorResponse(
  res: Response,
  message: string,
  code = 400,
  httpStatus = 400
): void {
  const response: ApiResponse<null> = {
    code,
    message,
    data: null,
    timestamp: Date.now(),
  };
  res.status(httpStatus).json(response);
}

