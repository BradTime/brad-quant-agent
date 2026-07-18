/**
 * API 响应类型
 */
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
  timestamp: number;
}

/**
 * 用户信息类型
 */
export interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
  role: 'user' | 'vip' | 'admin';
  createdAt: string;
  updatedAt: string;
}

/**
 * 认证相关类型
 */
export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
}

export interface AuthResponse {
  user: User;
  token: string;
  refreshToken: string;
}

export interface RegistrationAccepted {
  accepted: true;
  message: string;
}

export interface EmailVerificationResult {
  verified: true;
}

export interface EmailVerificationRequest {
  token: string;
  password: string;
  name: string;
}

/**
 * 主题类型
 */
export type Theme = 'light' | 'dark' | 'system';

