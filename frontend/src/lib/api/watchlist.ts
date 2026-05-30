import { apiClient } from './client';

export interface WatchlistItemView {
  code: string;
  name: string;
  group: string;
  sortOrder: number;
  price: number | null;
  change: number | null;
  changePercent: number | null;
  createdAt: string | null;
}

/**
 * 自选股 API（均需登录，按 user_id 隔离）。
 */
export const watchlistApi = {
  getList: async (): Promise<WatchlistItemView[]> => {
    const res = await apiClient.get<WatchlistItemView[]>('/watchlist');
    return res.data;
  },

  getGroups: async (): Promise<string[]> => {
    const res = await apiClient.get<string[]>('/watchlist/groups');
    return res.data;
  },

  add: async (
    code: string,
    options?: { name?: string; group?: string }
  ): Promise<{ code: string; added: boolean }> => {
    const res = await apiClient.post<{ code: string; added: boolean }>('/watchlist', {
      code,
      name: options?.name ?? '',
      group: options?.group ?? '默认分组',
    });
    return res.data;
  },

  update: async (
    code: string,
    body: { group?: string; sortOrder?: number }
  ): Promise<{ updated: boolean }> => {
    const res = await apiClient.patch<{ updated: boolean }>(
      `/watchlist/${encodeURIComponent(code)}`,
      body
    );
    return res.data;
  },

  remove: async (code: string): Promise<{ removed: boolean }> => {
    const res = await apiClient.delete<{ removed: boolean }>(
      `/watchlist/${encodeURIComponent(code)}`
    );
    return res.data;
  },
};
