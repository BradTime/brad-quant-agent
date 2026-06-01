'use client';

import Link from 'next/link';
import { Layers } from 'lucide-react';

/**
 * 策略 新建/详情/编辑 的 Phase 4 占位页（共享）。后端策略写操作为 501、详情 404，
 * 这里统一展示「未开放」，避免暴露看似可用、实则必失败的策略表单。
 * 鉴权由 (app) 布局的 AppShell 统一守卫，无需再包 RequireAuth。
 */
export function StrategyComingSoon() {
  return (
    <div className="container mx-auto flex min-h-[70vh] items-center justify-center p-6">
      <div className="max-w-md text-center">
        <span className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-brand-soft text-brand">
          <Layers className="h-7 w-7" />
        </span>
        <h1 className="font-display text-2xl tracking-tight">策略管理开发中</h1>
        <p className="mt-1 text-xs uppercase tracking-[0.18em] text-muted-foreground">
          Phase 4 · Quant Research
        </p>
        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
          策略的创建 / 编辑 / 运行与回测集成属于 Phase 4 量化研究范围，尚未开放。
          当前可先使用「看盘」「盘前早报」「AI 问答」。
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Link
            href="/strategies"
            className="rounded-xl border border-border px-4 py-2.5 text-sm text-foreground transition-colors hover:border-brand/50"
          >
            返回策略列表
          </Link>
          <Link
            href="/market"
            className="rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground"
          >
            去看盘
          </Link>
        </div>
      </div>
    </div>
  );
}
