import { API_BASE_URL } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiClient } from './client';
import { createSSEParser, StreamInterruptedError } from './sse';

export interface ChatMessage {
  role: 'user';
  content: string;
}

export const SESSION_NOT_FOUND_CODE = 'SESSION_NOT_FOUND';

export class ChatStreamHttpError extends Error {
  readonly status: number;
  readonly code?: string | number;

  constructor(message: string, status: number, code?: string | number) {
    super(message);
    this.name = 'ChatStreamHttpError';
    this.status = status;
    this.code = code;
  }
}

interface StreamHandlers {
  onDelta: (text: string) => void;
  onError?: (message: string) => void;
  onSession?: (sessionId: string) => void;
  onSessionInvalid?: () => void;
  signal?: AbortSignal;
  sessionId?: string;
  /** 界面上下文（如当前个股）；后端会按不可信元数据处理。 */
  contextHint?: string;
}

/**
 * 调用 `/ai/chat`（SSE 流式）。先解析 `sessionId` 帧，再处理 `delta`，
 * 遇到 `data: [DONE]` 结束。需要登录态（Bearer token）。
 */
export async function streamChat(
  messages: ChatMessage[],
  {
    onDelta,
    onError,
    onSession,
    onSessionInvalid,
    signal,
    sessionId,
    contextHint,
  }: StreamHandlers
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
      ...(sessionId ? { sessionId } : {}),
      ...(contextHint?.trim() ? { contextHint: contextHint.trim() } : {}),
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `请求失败（${res.status}）`;
    let code: string | number | undefined;
    try {
      const data = (await res.json()) as {
        message?: string;
        detail?: string;
        code?: string | number;
      };
      detail = data?.message || data?.detail || detail;
      code = data?.code;
    } catch {
      /* ignore parse error */
    }
    if (code === SESSION_NOT_FOUND_CODE) onSessionInvalid?.();
    onError?.(detail);
    throw new ChatStreamHttpError(detail, res.status, code);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser();

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const payload of parser.push(
      decoder.decode(value, { stream: true })
    )) {
      if (payload === '[DONE]') return;
      let obj: {
        sessionId?: string;
        delta?: string;
        error?: string;
        code?: string | number;
      };
      try {
        obj = JSON.parse(payload);
      } catch {
        /* 跳过无法解析的帧 */
        continue;
      }
      if (obj.sessionId) onSession?.(obj.sessionId);
      if (obj.error) {
        if (obj.code === SESSION_NOT_FOUND_CODE) onSessionInvalid?.();
        onError?.(obj.error);
        throw new ChatStreamHttpError(obj.error, res.status, obj.code);
      }
      if (obj.delta) onDelta(obj.delta);
    }
  }
  const interrupted = '连接中断：未收到完整结束标记';
  onError?.(interrupted);
  throw new StreamInterruptedError(interrupted);
}

export interface StoredChatMessage {
  id: string;
  sessionId: string;
  userId: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string | null;
}

export interface ChatSessionSummary {
  id: string;
  userId: string;
  title: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface ChatSessionDetail extends ChatSessionSummary {
  messages: StoredChatMessage[];
}

export interface UserMemory {
  id: string;
  userId: string;
  key: string;
  value: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export const listChatSessions = async (
  limit = 50
): Promise<ChatSessionSummary[]> => {
  const res = await apiClient.get<ChatSessionSummary[]>('/ai/sessions', {
    params: { limit },
  });
  return res.data ?? [];
};

export const getChatSession = async (
  id: string,
  signal?: AbortSignal
): Promise<ChatSessionDetail | null> => {
  const res = await apiClient.get<ChatSessionDetail | null>(
    `/ai/sessions/${id}`,
    { signal }
  );
  return res.data;
};

export const deleteChatSession = async (id: string): Promise<void> => {
  await apiClient.delete(`/ai/sessions/${id}`);
};

export const listUserMemories = async (): Promise<UserMemory[]> => {
  const res = await apiClient.get<UserMemory[]>('/ai/memories');
  return res.data ?? [];
};

export const saveUserMemory = async (
  key: string,
  value: string
): Promise<UserMemory> => {
  const res = await apiClient.post<UserMemory>('/ai/memories', { key, value });
  return res.data;
};

export const deleteUserMemory = async (id: string): Promise<void> => {
  await apiClient.delete(`/ai/memories/${id}`);
};

/** 深度研究的进度步骤（子问题调研完成 + 用到的工具） */
export interface ResearchStep {
  label: string;
  node?: string;
  tools?: string[];
}

export interface ResearchReportSummary {
  id: string;
  userId: string | null;
  question: string;
  status: string;
  model: string;
  createdAt: string | null;
}

export interface ResearchReportDetail extends ResearchReportSummary {
  content: string;
  plan: string[];
  steps: ResearchStep[];
}

/** 历史深度研究列表（不含正文） */
export const listResearchReports = async (
  limit = 20
): Promise<ResearchReportSummary[]> => {
  const res = await apiClient.get<ResearchReportSummary[]>('/ai/research', {
    params: { limit },
  });
  return res.data ?? [];
};

/** 某份深度研究报告详情（含计划/分步/正文），供回看 */
export const getResearchReport = async (
  id: string
): Promise<ResearchReportDetail | null> => {
  const res = await apiClient.get<ResearchReportDetail | null>(
    `/ai/research/${id}`
  );
  return res.data;
};

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
    for (const payload of parser.push(
      decoder.decode(value, { stream: true })
    )) {
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
        if (obj.step)
          onStep?.({ label: obj.step, node: obj.node, tools: obj.tools });
        if (obj.delta) onDelta(obj.delta);
      } catch {
        /* 跳过无法解析的帧 */
      }
    }
  }
  if (signal?.aborted) return;
  const interrupted = '连接中断：未收到完整结束标记';
  onError?.(interrupted);
  throw new StreamInterruptedError(interrupted);
}
