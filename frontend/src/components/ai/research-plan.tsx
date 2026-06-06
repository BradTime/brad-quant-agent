'use client';

import { Check, Loader2, Telescope, Wrench } from 'lucide-react';
import type { ResearchStep } from '@/lib/api/ai';
import { cn } from '@/lib/utils';

/** 把工具调用列表去重并标注次数：["a","a","b"] -> ["a×2","b"] */
function dedupeTools(tools: string[]): string[] {
  const counts = new Map<string, number>();
  for (const t of tools) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [...counts.entries()].map(([t, n]) => (n > 1 ? `${t}×${n}` : t));
}

/**
 * 自主深度研究的「研究计划」清单卡：把规划的子问题与分步调研进度合并成一张
 * 带状态徽标（编号/进行中/✓）、工具小药丸（去重计数）、进度计数与阶段提示的卡片，
 * 取代原先「裸 ol + 重复 li + 逗号工具串」的拥挤样式。
 */
export function ResearchPlanCard({
  plan,
  steps,
  active,
}: {
  plan: string[];
  steps: ResearchStep[];
  active: boolean;
}) {
  // 研究子步骤（"完成 i/n：..."）按到达顺序与 plan 对齐；规划/成稿等阶段步骤不计入
  const doneSteps = steps.filter((s) => (s.label ?? '').startsWith('完成'));
  const items = plan.length ? plan : doneSteps.map((s) => s.label ?? '');
  if (items.length === 0) {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-xl border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-brand" /> 规划研究路径中…
      </div>
    );
  }
  const synthesizing = steps.some((s) => (s.label ?? '').includes('综合'));

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-border bg-muted/30">
      <div className="flex items-center gap-1.5 border-b border-border/60 bg-muted/50 px-3 py-1.5 text-[11px] font-medium">
        <Telescope className="h-3.5 w-3.5 text-brand" />
        自主研究计划
        <span className="ml-auto font-normal text-muted-foreground">
          {doneSteps.length}/{items.length} 已调研
        </span>
      </div>
      <ol className="divide-y divide-border/40">
        {items.map((q, idx) => {
          const step = doneSteps[idx];
          const done = !!step;
          const running = active && !done && idx === doneSteps.length;
          return (
            <li key={idx} className="flex items-start gap-2 px-3 py-2">
              <span
                className={cn(
                  'mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full text-[9px] font-semibold',
                  done
                    ? 'bg-down/15 text-down'
                    : running
                      ? 'bg-brand/15 text-brand'
                      : 'bg-muted text-muted-foreground'
                )}
              >
                {done ? (
                  <Check className="h-2.5 w-2.5" />
                ) : running ? (
                  <Loader2 className="h-2.5 w-2.5 animate-spin" />
                ) : (
                  idx + 1
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[11.5px] leading-relaxed text-foreground/90">{q}</div>
                {step?.tools && step.tools.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {dedupeTools(step.tools).map((t) => (
                      <span
                        key={t}
                        className="inline-flex items-center gap-0.5 rounded border border-border bg-card px-1.5 py-0.5 text-[9px] text-muted-foreground"
                      >
                        <Wrench className="h-2 w-2" /> {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {active && (
        <div className="flex items-center gap-1.5 border-t border-border/60 px-3 py-1.5 text-[10px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          {synthesizing ? '综合成稿中…' : '分步调研中…'}
        </div>
      )}
    </div>
  );
}
