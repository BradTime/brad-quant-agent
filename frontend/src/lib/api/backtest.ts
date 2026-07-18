import { API_BASE_URL } from '@/lib/constants';
import type { ApiResponse } from '@/types';
import type {
  BacktestEngine,
  BacktestFrequency,
  BacktestJob,
  BacktestJobStatus,
  BacktestMetrics,
  BacktestStrategyType,
  EquityPoint,
  GridSortMetric,
  TradeRecord,
} from '@/types/backtest';
import { z } from 'zod';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiClient } from './client';
import { createSSEParser, StreamInterruptedError } from './sse';

/** 内置策略目录项（后端 /backtest/strategies 返回，驱动前端参数表单）。 */
export interface StrategyParamSpec {
  key: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min?: number;
  max?: number;
}

export interface StrategyCatalogItem {
  type: BacktestStrategyType;
  name: string;
  description: string;
  params: StrategyParamSpec[];
}

export interface BacktestRunRequest {
  strategyType: BacktestStrategyType;
  params: Record<string, number>;
  codes: string[];
  start: string;
  end: string;
  initialCapital: number;
  slippage: number;
  engine: BacktestEngine;
  frequency: BacktestFrequency;
}

export interface EquityPointWithBenchmark extends EquityPoint {
  benchmark?: number;
}

export interface BacktestMetricsExt extends Partial<BacktestMetrics> {
  benchmarkLabel?: string;
  benchmarkReturnPercent?: number;
  excessReturnPercent?: number;
}

export interface BacktestRunResult {
  id: string;
  strategyType: BacktestStrategyType;
  status: 'completed' | 'failed';
  engine: string;
  error?: string | null;
  createdAt: string;
  config: Record<string, unknown> & {
    engine?: BacktestEngine;
    frequency?: BacktestFrequency;
  };
  metrics: BacktestMetricsExt;
  equityCurve?: EquityPointWithBenchmark[];
  trades?: TradeRecord[];
  dataQuality?: Record<string, string>;
  actualRange?: { start: string; end: string } | null;
  ruleQuality?: Record<string, string> | null;
}

export interface GridResultRow {
  params: Record<string, number>;
  metrics: BacktestMetricsExt;
}

export interface GridSearchResult {
  results: GridResultRow[];
  best: GridResultRow | null;
  engine: BacktestEngine;
  sortBy: GridSortMetric;
  truncated: boolean;
  dataQuality?: Record<string, string>;
  actualRange?: { start: string; end: string } | null;
  ruleQuality?: Record<string, string> | null;
  error?: string;
  cancelled?: boolean;
}

export type { BacktestJob, BacktestJobStatus } from '@/types/backtest';

export interface GridSearchRequestBody {
  strategyType: BacktestStrategyType;
  paramGrid: Record<string, number[]>;
  codes: string[];
  start: string;
  end: string;
  initialCapital: number;
  slippage: number;
  engine: BacktestEngine;
  sortBy: GridSortMetric;
  frequency: BacktestFrequency;
}

// apiClient 的响应拦截器返回整个信封 { code, message, data }，业务数据在 .data
async function unwrap<T>(p: Promise<unknown>): Promise<T> {
  const env = (await p) as ApiResponse<T>;
  return env.data as T;
}

const backtestJobSchema = z.object({
  id: z.string(),
  userId: z.string(),
  kind: z.string(),
  status: z.enum(['queued', 'running', 'completed', 'failed', 'cancelled']),
  cancelRequested: z.boolean(),
  progressDone: z.number(),
  progressTotal: z.number(),
  error: z.string().nullable().optional(),
  request: z.record(z.unknown()).optional(),
  result: z.record(z.unknown()).nullable().optional(),
  createdAt: z.string().nullable().optional(),
  updatedAt: z.string().nullable().optional(),
  startedAt: z.string().nullable().optional(),
  finishedAt: z.string().nullable().optional(),
});

function parseBacktestJob(data: unknown): BacktestJob {
  return backtestJobSchema.parse(data) as BacktestJob;
}

async function unwrapJob(p: Promise<unknown>): Promise<BacktestJob> {
  return parseBacktestJob(await unwrap<unknown>(p));
}

const TERMINAL_JOB: ReadonlySet<BacktestJobStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
]);

async function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  await new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        reject(new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

export const backtestApi = {
  strategyCatalog: () =>
    unwrap<{ items: StrategyCatalogItem[] }>(apiClient.get('/backtest/strategies')),
  run: (req: BacktestRunRequest) =>
    unwrap<BacktestRunResult>(apiClient.post('/backtest/run', req)),
  list: () =>
    unwrap<{ items: BacktestRunResult[]; total: number }>(apiClient.get('/backtest')),
  get: (id: string) => unwrap<BacktestRunResult>(apiClient.get(`/backtest/${id}`)),
  /** 默认异步入队；返回 job。同步结果请用 gridSearchSync。 */
  gridSearchEnqueue: (req: GridSearchRequestBody) =>
    unwrapJob(apiClient.post('/backtest/grid', req)),
  gridSearchSync: (req: GridSearchRequestBody) =>
    unwrap<GridSearchResult>(apiClient.post('/backtest/grid?sync=true', req)),
  getJob: (jobId: string) => unwrapJob(apiClient.get(`/backtest/jobs/${jobId}`)),
  cancelJob: (jobId: string) =>
    unwrapJob(apiClient.post(`/backtest/jobs/${jobId}/cancel`)),
  /**
   * 入队网格并轮询至终态。可用 signal 中止轮询；中止时会请求 cancel。
   */
  gridSearch: async (
    req: GridSearchRequestBody,
    opts?: { signal?: AbortSignal; onProgress?: (job: BacktestJob) => void },
  ): Promise<GridSearchResult> => {
    const job = await unwrapJob(apiClient.post('/backtest/grid', req));
    opts?.onProgress?.(job);
    let current = job;
    try {
      while (!TERMINAL_JOB.has(current.status)) {
        await sleep(800, opts?.signal);
        current = await unwrapJob(apiClient.get(`/backtest/jobs/${job.id}`));
        opts?.onProgress?.(current);
      }
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') {
        try {
          await unwrapJob(apiClient.post(`/backtest/jobs/${job.id}/cancel`));
        } catch {
          /* ignore */
        }
      }
      throw err;
    }
    if (current.status === 'cancelled') {
      return (
        (current.result as GridSearchResult | undefined) ?? {
          results: [],
          best: null,
          engine: req.engine,
          sortBy: req.sortBy,
          truncated: true,
          cancelled: true,
          error: '已取消',
        }
      );
    }
    if (current.status === 'failed') {
      const result = current.result as GridSearchResult | undefined;
      throw new Error(current.error || result?.error || '网格寻优失败');
    }
    const result = current.result as GridSearchResult | undefined;
    if (!result) {
      throw new Error('任务完成但无结果');
    }
    return result;
  },
};

interface ReviewHandlers {
  onDelta: (text: string) => void;
  onError?: (message: string) => void;
  signal?: AbortSignal;
}

/** AI 回测点评（SSE 流式，delta/[DONE]）。 */
export async function streamBacktestReview(
  id: string,
  { onDelta, onError, signal }: ReviewHandlers,
): Promise<void> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`${API_BASE_URL}/backtest/${id}/review`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal,
  });
  if (!res.ok || !res.body) {
    onError?.(`请求失败（${res.status}）`);
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
        /* skip */
      }
    }
  }
  if (signal?.aborted) return;
  const interrupted = '连接中断：未收到完整结束标记';
  onError?.(interrupted);
  throw new StreamInterruptedError(interrupted);
}
