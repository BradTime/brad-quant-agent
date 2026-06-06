/**
 * API 配置常量
 */
// 后端为 FastAPI（默认 :8000）。可用 NEXT_PUBLIC_API_BASE_URL 覆盖（见 .env.example）。
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1';

export const API_TIMEOUT = 30000; // 30秒

/**
 * WebSocket 配置
 */
export const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_BASE_URL || 'ws://localhost:8000/ws/v1';

/**
 * Token 存储键名
 */
export const TOKEN_KEY = 'quant-agent-token';
export const REFRESH_TOKEN_KEY = 'quant-agent-refresh-token';

/**
 * 错误码定义
 */
export const ERROR_CODES = {
  // HTTP 错误码
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  CONFLICT: 409,
  UNPROCESSABLE_ENTITY: 422,
  TOO_MANY_REQUESTS: 429,
  INTERNAL_SERVER_ERROR: 500,
  SERVICE_UNAVAILABLE: 503,

  // 业务错误码范围
  AUTH_ERROR_START: 10001,
  AUTH_ERROR_END: 10099,
  STRATEGY_ERROR_START: 10101,
  STRATEGY_ERROR_END: 10199,
  BACKTEST_ERROR_START: 10201,
  BACKTEST_ERROR_END: 10299,
  TRADING_ERROR_START: 10301,
  TRADING_ERROR_END: 10399,
  RISK_ERROR_START: 10401,
  RISK_ERROR_END: 10499,
} as const;

