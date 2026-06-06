import { API_BASE_URL } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';
import { createSSEParser } from './sse';

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
  const parser = createSSEParser();

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const payload of parser.push(decoder.decode(value, { stream: true }))) {
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

/** 深度研究的进度步骤（子问题调研完成 + 用到的工具） */
export interface ResearchStep {
  label: string;
  node?: string;
  tools?: string[];
}

interface ResearchHandlers {
  /** 研究计划（规划者拆出的子问题列表） */
  onPlan?: (steps: string[]) => void;
  /** 逐步进度（规划/各子问题完成/综合成稿） */
  onStep?: (step: ResearchStep) => void;
  onDelta: (text: string) => void;
  onError?: (message: string) => void;
  signal?: AbortSignal;
  contextHint?: string;
}

/**
 * 调用 `/ai/research`（SSE 流式，自主深度研究：规划→逐子问题工具调研→综合成稿）。
 * 逐帧解析 `data: {"plan":[..]} | {"step":..,"tools":[..]} | {"delta":..}`，遇 `[DONE]` 结束。
 */
export async function streamDeepResearch(
  question: string,
  { onPlan, onStep, onDelta, onError, signal, contextHint }: ResearchHandlers
): Promise<void> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`${API_BASE_URL}/ai/research`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      question,
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
  const parser = createSSEParser();

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const payload of parser.push(decoder.decode(value, { stream: true }))) {
      if (payload === '[DONE]') return;
      try {
        const obj = JSON.parse(payload) as {
          plan?: string[];
          step?: string;
          node?: string;
          tools?: string[];
          delta?: string;
          error?: string;
        };
        if (obj.error) {
          onError?.(obj.error);
          return;
        }
        if (obj.plan) onPlan?.(obj.plan);
        if (obj.step) onStep?.({ label: obj.step, node: obj.node, tools: obj.tools });
        if (obj.delta) onDelta(obj.delta);
      } catch {
        /* 跳过无法解析的帧 */
      }
    }
  }
}
