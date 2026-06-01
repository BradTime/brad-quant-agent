'use client';

import Link from 'next/link';
import { FlaskConical } from 'lucide-react';
import { RequireAuth } from '@/components/auth/require-auth';

/**
 * 回测 Phase 4 占位页（共享）。真回测引擎未实现前，/backtest 各路由统一展示此页，
 * 避免「可填写但提交必失败」的表单与 404 死链。
 */
export function BacktestComingSoon() {
  return (
    <RequireAuth>
      <div className="container mx-auto flex min-h-[70vh] items-center justify-center p-6">
        <div className="max-w-md text-center">
          <span className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-brand-soft text-brand">
            <FlaskConical className="h-7 w-7" />
          </span>
          <h1 className="font-display text-2xl tracking-tight">回测引擎开发中</h1>
          <p className="mt-1 text-xs uppercase tracking-[0.18em] text-muted-foreground">
            Phase 4 · Quant Research
          </p>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            严肃的量化回测（backtrader / qlib 引擎、T+1 撮合、复权 / 滑点 / 印花税，策略 API
            向 RQAlpha / JoinQuant 对齐）将在 Phase 4 开放。当前可先使用「看盘」「盘前早报」「AI 问答」。
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link
              href="/market"
              className="rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground"
            >
              去看盘
            </Link>
            <Link
              href="/brief"
              className="rounded-xl border border-border px-4 py-2.5 text-sm text-foreground transition-colors hover:border-brand/50"
            >
              盘前早报
            </Link>
          </div>
        </div>
      </div>
    </RequireAuth>
  );
}
