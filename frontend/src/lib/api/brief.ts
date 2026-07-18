import { API_BASE_URL } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiClient } from './client';
import { createSSEParser, StreamInterruptedError } from './sse';

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

/** 海外宏观快照条目（LLMQuant·FRED） */
export interface MacroItem {
  indicator?: string;
  title?: string;
  value?: number | null;
  date?: string | null;
  deltaPct?: number | null;
  units?: string | null;
}

/** 量化知识背景条目（LLMQuant wiki 语义检索） */
export interface KnowledgeItem {
  title?: string;
  summary?: string;
  slug?: string;
  wikiItemId?: string;
}

/** 多智能体逐节点轨迹（含质量评审官的自评打分） */
export interface AgentTraceEntry {
  node?: string;
  label?: string;
  ms?: number;
  /** 节点起止时刻（epoch 毫秒），用于时序甘特图（展示并行重叠） */
  start?: number;
  end?: number;
  chars?: number;
  tools?: string[];
  note?: string;
  pass?: boolean;
  total?: number | null;
  scores?: Record<string, number>;
  issues?: string[];
  /** 节点输入/输出原文（后端持久化时各截断至 1500 字），用于观测下钻。 */
  input?: string;
  output?: string;
}

/** 早报新闻时效元数据（H19） */
export interface BriefNewsMeta {
  fallbackUsed?: boolean;
  newestAt?: string | null;
  recentMissing?: boolean;
  windowHours?: number;
  maxFallbackAgeHours?: number;
}

/** 早报落库的依据数据快照（前端只用部分字段做可视化卡片） */
export interface BriefDataPack {
  usMacro?: MacroItem[];
  quantKnowledge?: KnowledgeItem[];
  newsMeta?: BriefNewsMeta;
  coverage?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface Brief extends BriefSummary {
  content: string;
  engine?: string;
  dataPack?: BriefDataPack | null;
  agentTrace?: AgentTraceEntry[];
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

export interface BriefStep {
  label: string;
  node?: string;
  ms?: number;
}

interface GenerateHandlers {
  onDelta: (text: string) => void;
  /** 多智能体逐步进度（规划/各分析师/主编/合规审查） */
  onStep?: (step: BriefStep) => void;
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
  onStep,
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
  const parser = createSSEParser();

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const payload of parser.push(decoder.decode(value, { stream: true }))) {
      if (payload === '[DONE]') {
        onDone?.();
        return;
      }
      try {
        const obj = JSON.parse(payload) as {
          delta?: string;
          step?: string;
          node?: string;
          ms?: number;
          error?: string;
        };
        if (obj.error) {
          onError?.(obj.error);
          return;
        }
        if (obj.step) onStep?.({ label: obj.step, node: obj.node, ms: obj.ms });
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
