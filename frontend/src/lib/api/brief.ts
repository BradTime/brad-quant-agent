import { API_BASE_URL } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiClient } from './client';

export interface BriefSummary {
  id: string;
  userId: string | null;
  tradeDate: string | null;
  status: string;
  title: string;
  sourceNote: string;
  model: string;
  generatedAt: string | null;
}

export interface Brief extends BriefSummary {
  content: string;
}

/** 当前用户最新一份个性化早报（无则 null） */
export const getLatestBrief = async (): Promise<Brief | null> => {
  const res = await apiClient.get<Brief | null>('/brief/latest');
  return res.data;
};

/** 系统级全局早报（调度器每日生成） */
export const getGlobalLatestBrief = async (): Promise<Brief | null> => {
  const res = await apiClient.get<Brief | null>('/brief/global/latest');
  return res.data;
};

/** 历史早报列表（不含正文） */
export const listBriefs = async (limit = 20): Promise<BriefSummary[]> => {
  const res = await apiClient.get<BriefSummary[]>('/brief', { params: { limit } });
  return res.data ?? [];
};

/** 某份早报详情 */
export const getBrief = async (id: string): Promise<Brief | null> => {
  const res = await apiClient.get<Brief | null>(`/brief/${id}`);
  return res.data;
};

interface GenerateHandlers {
  onDelta: (text: string) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
  signal?: AbortSignal;
}

/**
 * 触发生成今日早报（SSE 流式）。逐帧解析 `data: {"delta": "..."}`，遇到
 * `data: [DONE]` 结束；服务端在生成结束时落库。需要登录态。
 */
export async function streamGenerateBrief({
  onDelta,
  onError,
  onDone,
  signal,
}: GenerateHandlers): Promise<void> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`${API_BASE_URL}/brief/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      detail = data?.message || data?.detail || detail;
    } catch {
      /* ignore */
    }
    onError?.(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (payload === '[DONE]') {
        onDone?.();
        return;
      }
      try {
        const obj = JSON.parse(payload) as { delta?: string; error?: string };
        if (obj.error) {
          onError?.(obj.error);
          return;
        }
        if (obj.delta) onDelta(obj.delta);
      } catch {
        /* 跳过无法解析的帧 */
      }
    }
  }
  onDone?.();
}
