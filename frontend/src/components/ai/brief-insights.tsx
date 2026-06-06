'use client';

import {
  Activity,
  BookOpen,
  Globe,
  Wrench,
  ShieldCheck,
  ShieldAlert,
  PencilLine,
} from 'lucide-react';
import type { AgentTraceEntry, BriefDataPack } from '@/lib/api/brief';
import { cn } from '@/lib/utils';

const SCORE_LABELS: Record<string, string> = {
  grounding: '数据可靠',
  honesty: '缺口诚实',
  conditional: '条件式',
  structure: '结构完整',
  actionable: '可执行',
};

const NODE_COLOR: Record<string, string> = {
  planner: 'bg-brand',
  market: 'bg-sky-500',
  capital: 'bg-violet-500',
  news: 'bg-amber-500',
  macro: 'bg-teal-500',
  editor: 'bg-brand',
  editor_revise: 'bg-brand/60',
  evaluator: 'bg-rose-500',
  reviewer: 'bg-muted-foreground',
};

/** 时序甘特图：按 start/end 绘制各节点条带，直观展示分析师并行重叠与各段耗时 */
function Gantt({ trace }: { trace: AgentTraceEntry[] }) {
  const timed = trace.filter((t) => typeof t.start === 'number' && typeof t.end === 'number');
  if (timed.length < 2) return null;
  const t0 = Math.min(...timed.map((t) => t.start as number));
  const tEnd = Math.max(...timed.map((t) => t.end as number));
  const total = Math.max(tEnd - t0, 1);
  return (
    <div className="mb-3 space-y-1 border-b border-border pb-3">
      <div className="mb-1 text-[10px] text-muted-foreground">
        耗时时序 · 并行重叠（总 {(total / 1000).toFixed(1)}s）
      </div>
      {timed.map((t, i) => {
        const left = (((t.start as number) - t0) / total) * 100;
        const width = Math.max((((t.end as number) - (t.start as number)) / total) * 100, 1.5);
        return (
          <div key={`${t.node}-${i}`} className="flex items-center gap-1.5">
            <span className="w-14 shrink-0 truncate text-[10px] text-muted-foreground" title={t.label}>
              {t.label}
            </span>
            <div className="relative h-2 flex-1 rounded bg-muted/40">
              <div
                className={cn('absolute top-0 h-2 rounded', NODE_COLOR[t.node ?? ''] ?? 'bg-brand')}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={`${t.ms}ms`}
              />
            </div>
            <span className="w-9 shrink-0 text-right tnum text-[10px] text-muted-foreground">
              {t.ms}ms
            </span>
          </div>
        );
      })}
    </div>
  );
}

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return typeof v === 'number' ? v.toLocaleString('en-US', { maximumFractionDigits: 4 }) : String(v);
}

/** 质量评审官节点：展示自评分数与问题 */
function EvalRow({ entry }: { entry: AgentTraceEntry }) {
  const passed = entry.pass !== false;
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-xs">
        {passed ? (
          <ShieldCheck className="h-3.5 w-3.5 text-down" />
        ) : (
          <ShieldAlert className="h-3.5 w-3.5 text-up" />
        )}
        <span className="font-medium">{entry.label ?? '质量自评'}</span>
        <span
          className={cn(
            'rounded-full px-1.5 py-0.5 text-[10px]',
            passed ? 'bg-down/15 text-down' : 'bg-up/15 text-up'
          )}
        >
          {passed ? '通过' : '需修订'}
        </span>
        {typeof entry.total === 'number' && (
          <span className="ml-auto text-[10px] text-muted-foreground">{entry.total}/25</span>
        )}
      </div>
      {entry.scores && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(entry.scores).map(([k, v]) => (
            <span
              key={k}
              className="inline-flex items-center gap-1 rounded border border-border bg-card px-1.5 py-0.5 text-[10px] text-muted-foreground"
              title={`${SCORE_LABELS[k] ?? k}: ${v}/5`}
            >
              {SCORE_LABELS[k] ?? k}
              <b className={cn('tnum', v >= 4 ? 'text-down' : 'text-up')}>{v}</b>
            </span>
          ))}
        </div>
      )}
      {entry.issues && entry.issues.length > 0 && entry.issues[0] !== '暂无显著问题' && (
        <ul className="mt-1.5 list-disc pl-4 text-[10px] leading-relaxed text-muted-foreground">
          {entry.issues.slice(0, 3).map((it, i) => (
            <li key={i}>{it}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 普通节点行：标签 + 耗时 + 工具调用 */
function NodeRow({ entry }: { entry: AgentTraceEntry }) {
  const revise = entry.node === 'editor_revise';
  return (
    <div className="flex items-center gap-2 px-0.5 py-1 text-xs">
      {revise ? (
        <PencilLine className="h-3.5 w-3.5 shrink-0 text-brand" />
      ) : (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-down" />
      )}
      <span className={cn(revise && 'text-brand')}>{entry.label ?? entry.node}</span>
      {entry.tools && entry.tools.length > 0 && (
        <span className="inline-flex items-center gap-1 rounded border border-brand/30 bg-brand-soft px-1.5 py-0.5 text-[10px] text-brand">
          <Wrench className="h-2.5 w-2.5" /> {entry.tools.join(', ')}
        </span>
      )}
      <span className="ml-auto tnum text-[10px] text-muted-foreground">
        {typeof entry.ms === 'number' ? `${entry.ms}ms` : ''}
      </span>
    </div>
  );
}

export function BriefInsights({
  dataPack,
  agentTrace,
  engine,
}: {
  dataPack?: BriefDataPack | null;
  agentTrace?: AgentTraceEntry[];
  engine?: string;
}) {
  const macro = dataPack?.usMacro ?? [];
  const knowledge = dataPack?.quantKnowledge ?? [];
  const trace = agentTrace ?? [];
  if (!macro.length && !knowledge.length && !trace.length) return null;

  return (
    <div className="space-y-4">
      {/* 多智能体观测面板 */}
      {trace.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-4">
          <div className="mb-2.5 flex items-center gap-2 text-sm font-medium">
            <Activity className="h-4 w-4 text-brand" /> 智能体观测
            <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
              {engine === 'graph' ? 'LangGraph 多智能体' : '单轮合成'}
            </span>
          </div>
          <Gantt trace={trace} />
          <div className="space-y-1">
            {trace.map((entry, i) =>
              entry.scores || entry.node === 'evaluator' ? (
                <EvalRow key={`${entry.node}-${i}`} entry={entry} />
              ) : (
                <NodeRow key={`${entry.node}-${i}`} entry={entry} />
              )
            )}
          </div>
        </section>
      )}

      {/* 海外宏观快照 */}
      {macro.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-4">
          <div className="mb-2.5 flex items-center gap-2 text-sm font-medium">
            <Globe className="h-4 w-4 text-brand" /> 海外宏观
            <span className="ml-auto text-[10px] text-muted-foreground">LLMQuant·FRED</span>
          </div>
          <ul className="space-y-2">
            {macro.map((m, i) => (
              <li key={m.indicator ?? i} className="flex items-baseline gap-2 text-xs">
                <span className="truncate text-muted-foreground" title={m.title ?? m.indicator}>
                  {m.title ?? m.indicator}
                </span>
                <span className="ml-auto tnum font-medium">
                  {fmtNum(m.value)}
                  {m.units ? <span className="text-[10px] text-muted-foreground"> {m.units}</span> : null}
                </span>
                {typeof m.deltaPct === 'number' && (
                  <span className={cn('tnum w-14 text-right text-[10px]', m.deltaPct >= 0 ? 'text-up' : 'text-down')}>
                    {m.deltaPct >= 0 ? '+' : ''}
                    {m.deltaPct.toFixed(2)}%
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 量化知识背景 */}
      {knowledge.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-4">
          <div className="mb-2.5 flex items-center gap-2 text-sm font-medium">
            <BookOpen className="h-4 w-4 text-brand" /> 量化知识背景
            <span className="ml-auto text-[10px] text-muted-foreground">概念释义·非行情</span>
          </div>
          <ul className="space-y-2.5">
            {knowledge.map((k, i) => (
              <li key={k.wikiItemId ?? i} className="text-xs">
                <div className="font-medium">{k.title}</div>
                {k.summary && (
                  <p className="mt-0.5 line-clamp-2 leading-relaxed text-muted-foreground">{k.summary}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
