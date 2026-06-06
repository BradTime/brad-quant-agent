'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Send,
  Square,
  Sparkles,
  Check,
  Wrench,
  Telescope,
  MessageSquare,
  Loader2,
  History,
} from 'lucide-react';
import {
  streamChat,
  streamDeepResearch,
  listResearchReports,
  getResearchReport,
  type ChatMessage,
  type ResearchStep,
  type ResearchReportSummary,
} from '@/lib/api/ai';
import { cn } from '@/lib/utils';
import { Markdown } from './markdown';

function fmtTime(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

interface ChatPanelProps {
  /** 注入给模型的上下文（作为 system 消息，不在界面显示），如"当前正在查看 600000.SH 浦发银行" */
  contextHint?: string;
  /** 建议提问（点击直接发送） */
  suggestions?: string[];
  placeholder?: string;
  className?: string;
  /** 紧凑模式（嵌入个股详情侧栏时使用更小的留白） */
  compact?: boolean;
  /** 开启「深度研究」模式切换（自主多轮规划编排）。默认关闭（嵌入式侧栏不显示）。 */
  enableDeepResearch?: boolean;
}

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  /** 深度研究：规划者拆出的子问题列表 */
  plan?: string[];
  /** 深度研究：逐步进度 */
  steps?: ResearchStep[];
  mode?: 'chat' | 'research';
}

export function ChatPanel({
  contextHint,
  suggestions = [],
  placeholder = '问问行情、指数、个股、板块…',
  className,
  compact = false,
  enableDeepResearch = false,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [deepMode, setDeepMode] = useState(false);
  const [history, setHistory] = useState<ResearchReportSummary[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const refreshHistory = useCallback(async () => {
    if (!enableDeepResearch) return;
    try {
      setHistory(await listResearchReports(20));
    } catch {
      /* ignore */
    }
  }, [enableDeepResearch]);

  useEffect(() => {
    void (async () => {
      await refreshHistory();
    })();
  }, [refreshHistory]);

  const loadReport = async (id: string) => {
    setShowHistory(false);
    try {
      const r = await getResearchReport(id);
      if (!r) return;
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: r.question },
        {
          role: 'assistant',
          content: r.content,
          mode: 'research',
          plan: r.plan,
          steps: r.steps,
        },
      ]);
    } catch {
      /* ignore */
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || streaming) return;
    setInput('');

    const research = deepMode && enableDeepResearch;
    const nextDisplay: DisplayMessage[] = [...messages, { role: 'user', content }];
    setMessages([
      ...nextDisplay,
      { role: 'assistant', content: '', mode: research ? 'research' : 'chat', plan: [], steps: [] },
    ]);
    setStreaming(true);

    // 后端只接受真实用户输入；历史 assistant 文本不回传，避免客户端伪造模型事实。
    const payload: ChatMessage[] = nextDisplay
      .filter((m) => m.role === 'user')
      .map((m) => ({
        role: 'user',
        content: m.content,
      }));

    const controller = new AbortController();
    abortRef.current = controller;

    const patchLast = (patch: Partial<DisplayMessage>) =>
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
        return copy;
      });

    let acc = '';
    try {
      if (research) {
        await streamDeepResearch(content, {
          signal: controller.signal,
          contextHint,
          onPlan: (steps) => patchLast({ plan: steps }),
          onStep: (s) =>
            setMessages((prev) => {
              const copy = [...prev];
              const last = { ...copy[copy.length - 1] };
              last.steps = [...(last.steps ?? []), s];
              copy[copy.length - 1] = last;
              return copy;
            }),
          onDelta: (piece) => {
            acc += piece;
            patchLast({ content: acc });
          },
          onError: (msg) => {
            acc = acc || `⚠️ ${msg}`;
            patchLast({ content: acc });
          },
        });
        return;
      }
      await streamChat(payload, {
        signal: controller.signal,
        contextHint,
        onDelta: (piece) => {
          acc += piece;
          patchLast({ content: acc });
        },
        onError: (msg) => {
          acc = acc || `⚠️ ${msg}`;
          patchLast({ content: acc });
        },
      });
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        patchLast({ content: acc || '⚠️ 连接出错，请稍后重试。' });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      if (research) refreshHistory();
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div
        ref={scrollRef}
        className={cn('flex-1 space-y-4 overflow-y-auto', compact ? 'p-3' : 'p-4')}
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-soft text-brand">
              <Sparkles className="h-5 w-5" />
            </span>
            <p className="max-w-xs text-sm text-muted-foreground">
              用一句话提问，AI 会调用行情 / K线 / 财务 / 选股工具，基于真实落库数据作答。
            </p>
            {suggestions.length > 0 && (
              <div className="mt-1 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-brand/40 hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
            >
              <div
                className={cn(
                  'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed',
                  m.role === 'user'
                    ? 'whitespace-pre-wrap bg-brand text-brand-foreground'
                    : 'border border-border bg-card text-foreground'
                )}
              >
                {m.role === 'assistant' &&
                  m.mode === 'research' &&
                  ((m.plan?.length ?? 0) > 0 || (m.steps?.length ?? 0) > 0) && (
                    <div className="mb-2.5 space-y-2 border-b border-border pb-2.5">
                      {(m.plan?.length ?? 0) > 0 && (
                        <div>
                          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                            <Telescope className="h-3 w-3" /> 研究计划
                          </div>
                          <ol className="list-decimal space-y-0.5 pl-4 text-[11px] text-muted-foreground">
                            {m.plan!.map((p, idx) => (
                              <li key={idx}>{p}</li>
                            ))}
                          </ol>
                        </div>
                      )}
                      {(m.steps?.length ?? 0) > 0 && (
                        <ul className="space-y-1">
                          {m.steps!.map((s, idx) => (
                            <li
                              key={idx}
                              className="flex items-start gap-1.5 text-[11px] text-muted-foreground"
                            >
                              <Check className="mt-0.5 h-3 w-3 shrink-0 text-down" />
                              <span className="flex-1">{s.label}</span>
                              {s.tools && s.tools.length > 0 && (
                                <span className="inline-flex shrink-0 items-center gap-0.5 text-brand">
                                  <Wrench className="h-2.5 w-2.5" />
                                  {s.tools.join(', ')}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                      {streaming && i === messages.length - 1 && (
                        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                          <Loader2 className="h-3 w-3 animate-spin" /> 研究进行中…
                        </div>
                      )}
                    </div>
                  )}
                {m.role === 'assistant' && m.content ? (
                  <Markdown content={m.content} />
                ) : (
                  m.content ||
                  (streaming && i === messages.length - 1
                    ? m.mode === 'research'
                      ? '规划中…'
                      : '思考中…'
                    : '')
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="border-t border-border p-3">
        {enableDeepResearch && (
          <div className="mb-2 flex items-center gap-2">
            <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setDeepMode(false)}
                disabled={streaming}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors disabled:opacity-50',
                  !deepMode ? 'bg-brand text-brand-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <MessageSquare className="h-3 w-3" /> 问答
              </button>
              <button
                type="button"
                onClick={() => setDeepMode(true)}
                disabled={streaming}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors disabled:opacity-50',
                  deepMode ? 'bg-brand text-brand-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Telescope className="h-3 w-3" /> 深度研究
              </button>
            </div>

            {history.length > 0 && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowHistory((v) => !v)}
                  className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                >
                  <History className="h-3 w-3" /> 研究历史
                </button>
                {showHistory && (
                  <div className="absolute bottom-full left-0 z-20 mb-1 max-h-64 w-72 overflow-auto rounded-xl border border-border bg-card p-1 shadow-lg">
                    {history.map((h) => (
                      <button
                        key={h.id}
                        type="button"
                        onClick={() => loadReport(h.id)}
                        className="block w-full rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-muted"
                      >
                        <div className="truncate text-xs">{h.question}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {fmtTime(h.createdAt)}
                          {h.status !== 'ready' ? ` · ${h.status}` : ''}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder={
              enableDeepResearch && deepMode
                ? '输入研究问题，AI 自主规划并分步调研后成稿…'
                : placeholder
            }
            className="max-h-32 flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-brand/50"
          />
          {streaming ? (
            <button
              onClick={stop}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border text-muted-foreground transition-colors hover:text-foreground"
              aria-label="停止"
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={() => send(input)}
              disabled={!input.trim()}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground transition-opacity disabled:opacity-40"
              aria-label="发送"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">
          AI 基于公开免费数据，可能延迟或缺失；仅供研究，不构成投资建议。
        </p>
      </div>
    </div>
  );
}
