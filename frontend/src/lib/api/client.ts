import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@/types';
import { API_BASE_URL, API_TIMEOUT, ERROR_CODES } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';

const createClient = (): AxiosInstance => {
  const client = axios.create({
    baseURL: API_BASE_URL,
    timeout: API_TIMEOUT,
    withCredentials: true,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // 响应拦截器
  client.interceptors.response.use(
    (response) => {
      // 直接返回 data，因为后端已经包装了 ApiResponse
      return response.data;
    },
    async (error: AxiosError<ApiResponse>) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

      // 处理 401：凭 Cookie 刷新会话后重试（M20，不再依赖 localStorage JWT）
      if (error.response?.status === ERROR_CODES.UNAUTHORIZED && !originalRequest._retry) {
        originalRequest._retry = true;
        const url = originalRequest.url || '';
        if (url.includes('/auth/login') || url.includes('/auth/refresh')) {
          useAuthStore.getState().clearAuth();
          if (typeof window !== 'undefined' && !url.includes('/auth/login')) {
            window.location.href = '/login';
          }
          return Promise.reject(error.response?.data || error);
        }

        try {
          const response = await axios.post<ApiResponse<{ user: unknown }>>(
            `${API_BASE_URL}/auth/refresh`,
            {},
            { withCredentials: true }
          );
          const user = response.data.data?.user as
            | Parameters<ReturnType<typeof useAuthStore.getState>['setAuth']>[0]
            | undefined;
          if (user) {
            useAuthStore.getState().setAuth(user);
          }
          return client(originalRequest);
        } catch (refreshError) {
          useAuthStore.getState().clearAuth();
          if (typeof window !== 'undefined') {
            window.location.href = '/login';
          }
          return Promise.reject(refreshError);
        }
      }

      // 统一错误处理
      const errorResponse: ApiResponse = error.response?.data || {
        code: error.response?.status || ERROR_CODES.INTERNAL_SERVER_ERROR,
        message: error.message || '请求失败，请稍后重试',
        data: null,
        timestamp: Date.now(),
      };

      return Promise.reject(errorResponse);
    }
  );

  return client;
};

export const apiClient = createClient();
