import type {
  AuthResponse,
  EmailVerificationRequest,
  EmailVerificationResult,
  LoginRequest,
  RegisterRequest,
  RegistrationAccepted,
  User,
} from '@/types';
import { apiClient } from './client';

/**
 * 认证相关 API（M20: Cookie 会话，JSON 仅含 user）
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
  register: async (data: RegisterRequest): Promise<RegistrationAccepted> => {
    const response = await apiClient.post<RegistrationAccepted>('/auth/register', data);
    return response.data;
  },

  verifyEmail: async (data: EmailVerificationRequest): Promise<EmailVerificationResult> => {
    const response = await apiClient.post<EmailVerificationResult>('/auth/verify', data);
    return response.data;
  },

  /**
   * 用户登出
   */
  logout: async (): Promise<void> => {
    await apiClient.post('/auth/logout');
  },

  /**
   * 凭 Cookie 刷新会话（body 可空）
   */
  refreshSession: async (): Promise<AuthResponse> => {
    const response = await apiClient.post<AuthResponse>('/auth/refresh', {});
    return response.data;
  },

  /**
   * 获取当前用户信息
   */
  getMe: async (): Promise<User> => {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },

  /**
   * 短时 WS 握手 JWT（仅内存使用，勿持久化）
   */
  getWsTicket: async (): Promise<string> => {
    const response = await apiClient.get<{ token: string }>('/auth/ws-ticket');
    return response.data.token;
  },
};
