import type { LoginRequest, RegisterRequest, AuthResponse } from '@/types';
import { apiClient } from './client';

/**
 * 认证相关 API
 */
export const authApi = {
  /**
   * 用户登录
   */
  login: async (data: LoginRequest): Promise<AuthResponse> => {
    const response = await apiClient.post<AuthResponse>('/auth/login', data);
    return response.data;
  },

  /**
   * 用户注册
   */
  register: async (data: RegisterRequest): Promise<AuthResponse> => {
    const response = await apiClient.post<AuthResponse>('/auth/register', data);
    return response.data;
  },

  /**
   * 用户登出
   */
  logout: async (): Promise<void> => {
    await apiClient.post('/auth/logout');
  },

  /**
   * 刷新 Token
   */
  refreshToken: async (refreshToken: string): Promise<{ token: string; refreshToken: string }> => {
    const response = await apiClient.post<{ token: string; refreshToken: string }>(
      '/auth/refresh',
      { refreshToken }
    );
    return response.data;
  },

  /**
   * 获取当前用户信息
   */
  getMe: async () => {
    const response = await apiClient.get('/auth/me');
    return response.data;
  },
};

