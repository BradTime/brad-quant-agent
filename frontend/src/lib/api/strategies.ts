import type {
  Strategy,
  StrategyListParams,
  StrategyCreateRequest,
  StrategyUpdateRequest,
} from '@/types/strategy';
import type { ApiResponse } from '@/types';
import { apiClient } from './client';

/**
 * 策略管理相关 API
 */
export const strategiesApi = {
  /**
   * 获取策略列表
   */
  getList: async (params?: StrategyListParams): Promise<ApiResponse<{ items: Strategy[]; total: number }>> => {
    const response = await apiClient.get<ApiResponse<{ items: Strategy[]; total: number }>>('/strategies', {
      params,
    });
    // 响应拦截器已将 body 解包为 ApiResponse 信封；axios 静态类型仍标注为 AxiosResponse，故在此桥接。
    return response as unknown as ApiResponse<{ items: Strategy[]; total: number }>;
  },

  /**
   * 获取策略详情
   */
  getDetail: async (id: string): Promise<Strategy> => {
    const response = await apiClient.get<Strategy>(`/strategies/${id}`);
    return response.data;
  },

  /**
   * 创建策略
   */
  create: async (data: StrategyCreateRequest): Promise<Strategy> => {
    const response = await apiClient.post<Strategy>('/strategies', data);
    return response.data;
  },

  /**
   * 更新策略
   */
  update: async (data: StrategyUpdateRequest): Promise<Strategy> => {
    const { id, ...rest } = data;
    const response = await apiClient.put<Strategy>(`/strategies/${id}`, rest);
    return response.data;
  },

  /**
   * 删除策略
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/strategies/${id}`);
  },

  /**
   * 启用策略
   */
  enable: async (id: string): Promise<void> => {
    await apiClient.post(`/strategies/${id}/enable`);
  },

  /**
   * 停用策略
   */
  disable: async (id: string): Promise<void> => {
    await apiClient.post(`/strategies/${id}/disable`);
  },

  /**
   * 复制策略
   */
  duplicate: async (id: string): Promise<Strategy> => {
    const response = await apiClient.post<Strategy>(`/strategies/${id}/duplicate`);
    return response.data;
  },
};


