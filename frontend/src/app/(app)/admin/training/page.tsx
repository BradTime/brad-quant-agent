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
import { CandidateReviewCard } from '@/components/ai/candidate-review-card';

export default function TrainingAdminPage() {
  const user = useAuthStore((state) => state.user);
  const [status, setStatus] = useState('pending');
  const [taskType, setTaskType] = useState('');
  const [rating, setRating] = useState('');
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
        listTrainingCandidates({
          ...(status ? { status } : {}),
          ...(taskType ? { taskType } : {}),
          ...(rating ? { rating } : {}),
        }),
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
  }, [rating, status, taskType, user?.role]);

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
    payload: {
      status: 'approved' | 'rejected';
      taskType: TrainingCandidate['taskType'];
      idealAnswer?: string;
      qualityLabels: string[];
      reviewNote?: string;
    }
  ) => {
    setBusy(true);
    try {
      await reviewTrainingCandidate(candidate.id, payload);
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
        <select
          value={taskType}
          onChange={(event) => setTaskType(event.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
          aria-label="任务类型筛选"
        >
          <option value="">全部任务</option>
          <option value="tool-routing">工具路由</option>
          <option value="grounded-response">有依据回答</option>
          <option value="honesty-compliance">诚实性 / 合规</option>
        </select>
        <select
          value={rating}
          onChange={(event) => setRating(event.target.value)}
          className="rounded-lg border border-border bg-background px-3 py-2 text-sm"
          aria-label="反馈筛选"
        >
          <option value="">全部反馈</option>
          <option value="up">好评</option>
          <option value="down">差评</option>
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
          <CandidateReviewCard
            key={candidate.id}
            candidate={candidate}
            busy={busy}
            onReview={review}
          />
        ))}
      </div>
    </div>
  );
}
