import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import type { ApiResponse } from '@/types';
import { API_BASE_URL, API_TIMEOUT, ERROR_CODES } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';
const createClient = (): AxiosInstance => {
  const client = axios.create({
    baseURL: API_BASE_URL,
    timeout: API_TIMEOUT,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // 请求拦截器
  client.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      const token = useAuthStore.getState().token;
      if (token && config.headers) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    },
    (error) => {
      return Promise.reject(error);
    }
  );

  // 响应拦截器
  client.interceptors.response.use(
    (response) => {
      // 直接返回 data，因为后端已经包装了 ApiResponse
      return response.data;
    },
    async (error: AxiosError<ApiResponse>) => {
      const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

      // 处理 401 未授权错误
      if (error.response?.status === ERROR_CODES.UNAUTHORIZED && !originalRequest._retry) {
        originalRequest._retry = true;

        // 尝试刷新 token
        const refreshToken = useAuthStore.getState().refreshToken;
        if (refreshToken) {
          try {
            const response = await axios.post<ApiResponse<{ token: string; refreshToken: string }>>(
              `${API_BASE_URL}/auth/refresh`,
              { refreshToken }
            );
            const payload = response.data.data;
            if (!payload?.token) {
              throw new Error('refresh failed');
            }
            const user = useAuthStore.getState().user;
            if (!user) {
              throw new Error('missing user');
            }
            useAuthStore.getState().setAuth(user, payload.token, payload.refreshToken);
            originalRequest.headers.Authorization = `Bearer ${payload.token}`;
            return client(originalRequest);
          } catch (refreshError) {
            // 刷新失败，清除认证信息并跳转到登录页
            useAuthStore.getState().clearAuth();
            if (typeof window !== 'undefined') {
              window.location.href = '/login';
            }
            return Promise.reject(refreshError);
          }
        } else {
          // 没有 refreshToken，清除认证信息
          useAuthStore.getState().clearAuth();
          if (typeof window !== 'undefined') {
            window.location.href = '/login';
          }
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

