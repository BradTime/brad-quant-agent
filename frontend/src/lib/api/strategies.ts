import type {
  Strategy,
  StrategyListParams,
  StrategyCreateRequest,
  StrategyUpdateRequest,
} from '@/types/strategy';
import type { ApiResponse } from '@/types';
import { apiClient } from './client';

async function unwrap<T>(request: Promise<unknown>): Promise<T> {
  const envelope = (await request) as ApiResponse<T>;
  return envelope.data;
}

/**
 * 策略管理相关 API
 */
export const strategiesApi = {
  /**
   * 获取策略列表
   */
  getList: (params?: StrategyListParams) =>
    unwrap<{ items: Strategy[]; total: number }>(apiClient.get('/strategies', { params })),

  /**
   * 获取策略详情
   */
  getDetail: (id: string) =>
    unwrap<Strategy>(apiClient.get(`/strategies/${id}`)),

  /**
   * 创建策略
   */
  create: (data: StrategyCreateRequest) =>
    unwrap<Strategy>(apiClient.post('/strategies', data)),

  /**
   * 更新策略
   */
  update: async (data: StrategyUpdateRequest): Promise<Strategy> => {
    const { id, ...rest } = data;
    return unwrap<Strategy>(apiClient.put(`/strategies/${id}`, rest));
  },

  /**
   * 删除策略
   */
  delete: (id: string) =>
    unwrap<{ deleted: boolean }>(apiClient.delete(`/strategies/${id}`)),

  /**
   * 启用策略
   */
  enable: (id: string) =>
    unwrap<Strategy>(apiClient.post(`/strategies/${id}/enable`)),

  /**
   * 停用策略
   */
  disable: (id: string) =>
    unwrap<Strategy>(apiClient.post(`/strategies/${id}/disable`)),

  /**
   * 复制策略
   */
  duplicate: (id: string) =>
    unwrap<Strategy>(apiClient.post(`/strategies/${id}/duplicate`)),
};
