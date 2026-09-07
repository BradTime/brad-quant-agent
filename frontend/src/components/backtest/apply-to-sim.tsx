'use client';

import { useState } from 'react';
import { placeSimOrder } from '@/lib/api/sim';
import { getApiErrorMessage } from '@/lib/api/errors';
import { Button } from '@/components/ui/button';

export interface ApplyToSimDraft {
  code: string;
  side: 'buy' | 'sell';
  qty?: number;
}

/**
 * 回测结果 → 模拟下单确认（play-money，须用户确认，非投资建议）。
 */
export function ApplyToSimButton({ draft }: { draft: ApplyToSimDraft | null }) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (!draft?.code) return null;

  const qty = draft.qty && draft.qty >= 100 ? Math.floor(draft.qty / 100) * 100 : 100;
  const sideLabel = draft.side === 'buy' ? '买入' : '卖出';

  const submit = async () => {
    setSubmitting(true);
    setMessage(null);
    try {
      const order = await placeSimOrder({
        code: draft.code,
        side: draft.side,
        type: 'market',
        qty,
      });
      setMessage(`已提交模拟市价单：${order.code} ${sideLabel} ${order.qty} 股（${order.status}）`);
      setOpen(false);
    } catch (err) {
      setMessage(getApiErrorMessage(err, '模拟下单失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-2" data-testid="apply-to-sim">
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>
        应用到模拟
      </Button>
      {open && (
        <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm space-y-2">
          <p>
            将以<strong>市价</strong>模拟{sideLabel}{' '}
            <span className="font-mono">{draft.code}</span> × {qty} 股。
          </p>
          <p className="text-xs text-muted-foreground">
            仅 play-money 模拟盘，不构成投资建议；请确认后再提交。
          </p>
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={submitting} onClick={() => void submit()}>
              {submitting ? '提交中…' : '确认下单'}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
              取消
            </Button>
          </div>
        </div>
      )}
      {message && <p className="text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}

/** 从回测配置/成交推断模拟下单草稿；默认买入首码或最近回合标的。 */
export function draftFromBacktest(result: {
  config?: Record<string, unknown> | null;
  trades?: Array<{ symbol?: string }> | null;
}): ApplyToSimDraft | null {
  const rawCodes = result.config?.codes;
  const codes = Array.isArray(rawCodes)
    ? rawCodes.filter((code): code is string => typeof code === 'string')
    : [];
  const trades = result.trades ?? [];
  const last = trades.length > 0 ? trades[trades.length - 1] : null;
  const code = last?.symbol || codes[0];
  if (!code) return null;
  // 回测回合为买卖闭环；一键模拟默认开仓买入（用户可在模拟页改方向）
  return { code, side: 'buy', qty: 100 };
}
