'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Newspaper, Sparkles, Loader2, Clock, RefreshCw, AlertTriangle } from 'lucide-react';
import { RequireAuth } from '@/components/auth/require-auth';
import { Markdown } from '@/components/ai/markdown';
import {
  getLatestBrief,
  listBriefs,
  getBrief,
  streamGenerateBrief,
  type Brief,
  type BriefSummary,
} from '@/lib/api/brief';
import { cn } from '@/lib/utils';

function fmtTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function BriefView() {
  const [content, setContent] = useState('');
  const [meta, setMeta] = useState<BriefSummary | null>(null);
  const [history, setHistory] = useState<BriefSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await listBriefs(20));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [latest] = await Promise.all([getLatestBrief(), refreshHistory()]);
        if (latest) {
          setContent(latest.content);
          setMeta(latest);
        }
      } catch {
        /* 首次无早报属正常 */
      } finally {
        setLoading(false);
      }
    })();
    return () => abortRef.current?.abort();
  }, [refreshHistory]);

  const generate = async () => {
    if (generating) return;
    setError('');
    setContent('');
    setMeta(null);
    setGenerating(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let acc = '';
    await streamGenerateBrief({
      signal: controller.signal,
      onDelta: (piece) => {
        acc += piece;
        setContent(acc);
      },
      onError: (msg) => setError(msg),
      onDone: async () => {
        const latest = await getLatestBrief();
        if (latest) setMeta(latest);
        await refreshHistory();
      },
    }).catch((err) => {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        setError('生成连接出错，请稍后重试。');
      }
    });
    setGenerating(false);
    abortRef.current = null;
  };

  const openBrief = async (id: string) => {
    if (generating) return;
    try {
      const b: Brief | null = await getBrief(id);
      if (b) {
        setContent(b.content);
        setMeta(b);
      }
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="container mx-auto p-4 lg:p-6">
      {/* 头部 */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand">
          <Newspaper className="h-5 w-5" />
        </span>
        <div className="mr-auto">
          <h1 className="font-display text-2xl tracking-tight">AI 盘前早报</h1>
          <p className="text-sm text-muted-foreground">
            基于已落库公开数据（指数 / 自选股 / 资金流 / 龙虎榜 / 新闻）由 AI 合成的条件式研究计划
          </p>
        </div>
        <button
          onClick={generate}
          disabled={generating}
          className={cn(
            'inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground transition-opacity',
            generating && 'opacity-60'
          )}
        >
          {generating ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> 生成中…
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" /> 生成今日早报
            </>
          )}
        </button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
        {/* 正文 */}
        <div className="order-2 min-h-[60vh] rounded-2xl border border-border bg-card p-5 lg:order-1 lg:p-7">
          {meta && (
            <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border pb-3">
              <h2 className="font-display text-lg tracking-tight">{meta.title}</h2>
              <span className="text-xs text-muted-foreground">
                生成于 {fmtTime(meta.generatedAt)} · {meta.model}
              </span>
            </div>
          )}

          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <AlertTriangle className="h-4 w-4" /> {error}
            </div>
          )}

          {loading ? (
            <div className="flex h-[50vh] items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" /> 加载中…
            </div>
          ) : content ? (
            <>
              <Markdown content={content} />
              {generating && (
                <span className="ml-1 inline-block h-4 w-2 animate-pulse bg-brand align-middle" />
              )}
            </>
          ) : (
            <div className="flex h-[50vh] flex-col items-center justify-center gap-3 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-brand-soft text-brand">
                <Newspaper className="h-6 w-6" />
              </span>
              <p className="max-w-sm text-sm text-muted-foreground">
                还没有今日早报。点击右上角「生成今日早报」，AI 将基于你的自选股与已落库市场数据，
                生成一份条件式盘前研究计划。
              </p>
            </div>
          )}

          {meta?.sourceNote && (
            <p className="mt-6 border-t border-border pt-3 text-[11px] leading-relaxed text-muted-foreground">
              {meta.sourceNote}
            </p>
          )}
        </div>

        {/* 历史 */}
        <aside className="order-1 lg:order-2">
          <div className="rounded-2xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Clock className="h-4 w-4 text-muted-foreground" /> 历史早报
              <button
                onClick={refreshHistory}
                className="ml-auto text-muted-foreground transition-colors hover:text-foreground"
                aria-label="刷新"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
            {history.length === 0 ? (
              <p className="py-6 text-center text-xs text-muted-foreground">暂无历史</p>
            ) : (
              <ul className="space-y-1">
                {history.map((h) => (
                  <li key={h.id}>
                    <button
                      onClick={() => openBrief(h.id)}
                      className={cn(
                        'w-full rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted',
                        meta?.id === h.id && 'bg-muted'
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate">{h.tradeDate}</span>
                        {h.status !== 'ready' && (
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {h.status}
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        {fmtTime(h.generatedAt)}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="mt-3 px-1 text-[11px] leading-relaxed text-muted-foreground">
            免费数据存在延迟与覆盖缺口（隔夜外盘 / 宏观政策暂未接入）。早报为条件式研究计划，不构成投资建议。
          </p>
        </aside>
      </div>
    </div>
  );
}

export default function BriefPage() {
  return (
    <RequireAuth>
      <BriefView />
    </RequireAuth>
  );
}
