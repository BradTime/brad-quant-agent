'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  buildTrainingDataset,
  getTrainingReadiness,
  listTrainingCandidates,
  reviewTrainingCandidate,
  type TrainingCandidate,
} from '@/lib/api/training';
import { useAuthStore } from '@/stores/useAuthStore';

export default function TrainingAdminPage() {
  const user = useAuthStore((state) => state.user);
  const [status, setStatus] = useState('pending');
  const [rows, setRows] = useState<TrainingCandidate[]>([]);
  const [readiness, setReadiness] = useState<Awaited<
    ReturnType<typeof getTrainingReadiness>
  > | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(
    `dataset-${new Date().toISOString().slice(0, 10)}`
  );

  const refresh = useCallback(async () => {
    if (user?.role !== 'admin') return;
    try {
      const [candidates, state] = await Promise.all([
        listTrainingCandidates(status || undefined),
        getTrainingReadiness(),
      ]);
      setRows(candidates);
      setReadiness(state);
      setError('');
    } catch (reason) {
      setError(
        typeof reason === 'object' && reason && 'message' in reason
          ? String(reason.message)
          : '加载训练候选失败'
      );
    }
  }, [status, user?.role]);

  useEffect(() => {
    const task = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(task);
  }, [refresh]);

  if (user?.role !== 'admin') {
    return (
      <div className="rounded-xl border border-border bg-card p-6">
        <h1 className="text-xl font-semibold">训练数据审核</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          此页面仅对管理员开放。
        </p>
      </div>
    );
  }

  const review = async (
    candidate: TrainingCandidate,
    decision: 'approved' | 'rejected'
  ) => {
    let idealAnswer = candidate.idealAnswer ?? '';
    if (decision === 'approved' && candidate.rating === 'down') {
      idealAnswer =
        window.prompt('差评样本必须填写理想答案', idealAnswer) ?? '';
      if (!idealAnswer.trim()) return;
    }
    const note = window.prompt('可选：审核备注', candidate.reviewNote ?? '') ?? '';
    setBusy(true);
    try {
      await reviewTrainingCandidate(candidate.id, {
        status: decision,
        taskType: candidate.taskType,
        ...(idealAnswer.trim() ? { idealAnswer: idealAnswer.trim() } : {}),
        ...(note.trim() ? { reviewNote: note.trim() } : {}),
      });
      await refresh();
    } catch (reason) {
      setError(
        typeof reason === 'object' && reason && 'message' in reason
          ? String(reason.message)
          : '审核失败'
      );
    } finally {
      setBusy(false);
    }
  };

  const build = async () => {
    if (!version.trim() || !window.confirm(`冻结数据集 ${version}？冻结后不可覆盖。`)) {
      return;
    }
    setBusy(true);
    try {
      await buildTrainingDataset(version.trim());
      setError('');
      window.alert('数据集已完成审计并冻结。');
    } catch (reason) {
      setError(
        typeof reason === 'object' && reason && 'message' in reason
          ? String(reason.message)
          : '构建数据集失败'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-brand">
          Model Improvement
        </p>
        <h1 className="mt-1 text-2xl font-semibold">训练数据审核</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          仅展示用户明确授权且已经不可逆脱敏的问答。
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">已批准</div>
          <div className="mt-1 text-2xl font-semibold">
            {readiness?.approved ?? 0}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">预计验证集</div>
          <div className="mt-1 text-2xl font-semibold">
            {readiness?.estimatedValidation ?? 0}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">微调就绪</div>
          <div className="mt-1 text-2xl font-semibold">
            {readiness?.ready ? '是' : '否'}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-xl border border-border bg-card p-3">
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
        >
          <option value="pending">待审核</option>
          <option value="approved">已批准</option>
          <option value="rejected">已拒绝</option>
          <option value="">全部</option>
        </select>
        <input
          value={version}
          onChange={(event) => setVersion(event.target.value)}
          className="min-w-56 rounded-lg border border-border bg-background px-3 py-2 text-sm"
          aria-label="数据集版本"
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => void build()}
          className="rounded-lg bg-brand px-3 py-2 text-sm text-brand-foreground disabled:opacity-50"
        >
          审计并冻结数据集
        </button>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="space-y-3">
        {rows.length === 0 && (
          <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            当前筛选条件下没有候选。
          </div>
        )}
        {rows.map((candidate) => (
          <article
            key={candidate.id}
            className="space-y-3 rounded-xl border border-border bg-card p-4"
          >
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded bg-muted px-2 py-1">
                {candidate.taskType}
              </span>
              <span className="rounded bg-muted px-2 py-1">
                {candidate.rating === 'up' ? '好评' : '差评'}
              </span>
              <span className="text-muted-foreground">{candidate.status}</span>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">用户问题</div>
              <p className="mt-1 whitespace-pre-wrap text-sm">{candidate.input}</p>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">模型回答</div>
              <p className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap text-sm">
                {candidate.output}
              </p>
            </div>
            {candidate.comment && (
              <p className="text-xs text-muted-foreground">
                用户说明：{candidate.comment}
              </p>
            )}
            {candidate.status === 'pending' && (
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void review(candidate, 'approved')}
                  className="rounded-lg bg-brand px-3 py-1.5 text-xs text-brand-foreground"
                >
                  批准
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void review(candidate, 'rejected')}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs"
                >
                  拒绝
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
