import { API_BASE_URL } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';

export interface ChatMessage {
  role: 'user';
  content: string;
}

interface StreamHandlers {
  onDelta: (text: string) => void;
  onError?: (message: string) => void;
  signal?: AbortSignal;
  /** 界面上下文（如当前个股）；后端会按不可信元数据处理。 */
  contextHint?: string;
}

/**
 * 调用 `/ai/chat`（SSE 流式）。逐帧解析 `data: {"delta": "..."}`，遇到
 * `data: [DONE]` 结束。需要登录态（Bearer token）。
 */
export async function streamChat(
  messages: ChatMessage[],
  { onDelta, onError, signal, contextHint }: StreamHandlers
): Promise<void> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`${API_BASE_URL}/ai/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      messages,
      ...(contextHint?.trim() ? { contextHint: contextHint.trim() } : {}),
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      detail = data?.message || data?.detail || detail;
    } catch {
      /* ignore parse error */
    }
    onError?.(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // SSE 帧以空行分隔；按 `data:` 前缀逐条解析，处理跨 chunk 的半帧。
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
      if (payload === '[DONE]') return;
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
}
