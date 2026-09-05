'use client';

import { useState } from 'react';
import type { TrainingCandidate } from '@/lib/api/training';

const TASK_OPTIONS: Array<[TrainingCandidate['taskType'], string]> = [
  ['tool-routing', '工具路由'],
  ['grounded-response', '有依据回答'],
  ['honesty-compliance', '诚实性 / 合规'],
];

const QUALITY_OPTIONS = [
  ['human-corrected', '人工修订'],
  ['grounded', '依据完整'],
  ['clear', '表达清晰'],
  ['hard-negative', '高价值负例'],
] as const;

export function CandidateReviewCard({
  candidate,
  busy,
  onReview,
}: {
  candidate: TrainingCandidate;
  busy: boolean;
  onReview: (
    candidate: TrainingCandidate,
    payload: {
      status: 'approved' | 'rejected';
      taskType: TrainingCandidate['taskType'];
      idealAnswer?: string;
      qualityLabels: string[];
      reviewNote?: string;
    }
  ) => Promise<void>;
}) {
  const [taskType, setTaskType] = useState(candidate.taskType);
  const [idealAnswer, setIdealAnswer] = useState(candidate.idealAnswer ?? '');
  const [qualityLabels, setQualityLabels] = useState<string[]>(
    candidate.qualityLabels
  );
  const [reviewNote, setReviewNote] = useState(candidate.reviewNote ?? '');
  const needsCorrection = candidate.rating === 'down';
  const canApprove = !needsCorrection || idealAnswer.trim().length > 0;

  const payload = (status: 'approved' | 'rejected') => ({
    status,
    taskType,
    ...(idealAnswer.trim() ? { idealAnswer: idealAnswer.trim() } : {}),
    qualityLabels,
    ...(reviewNote.trim() ? { reviewNote: reviewNote.trim() } : {}),
  });

  return (
    <article className="space-y-4 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-muted px-2 py-1">
          {candidate.rating === 'up' ? '好评' : '差评'}
        </span>
        <span className="text-muted-foreground">{candidate.status}</span>
        {candidate.issueLabels.map((label) => (
          <span key={label} className="rounded border border-border px-2 py-1">
            {label}
          </span>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <div className="text-xs text-muted-foreground">用户问题</div>
          <p className="mt-1 whitespace-pre-wrap text-sm">{candidate.input}</p>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">模型回答</div>
          <p className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap text-sm">
            {candidate.output}
          </p>
        </div>
      </div>

      {candidate.comment && (
        <p className="rounded-lg bg-muted/50 p-2 text-xs">
          用户说明：{candidate.comment}
        </p>
      )}

      {candidate.status === 'pending' && (
        <div className="grid gap-3 border-t border-border pt-3 lg:grid-cols-2">
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">训练任务类型</span>
            <select
              value={taskType}
              onChange={(event) =>
                setTaskType(event.target.value as TrainingCandidate['taskType'])
              }
              className="w-full rounded-lg border border-border bg-background px-3 py-2"
            >
              {TASK_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="space-y-1">
            <legend className="text-xs text-muted-foreground">质量标签</legend>
            <div className="flex flex-wrap gap-2">
              {QUALITY_OPTIONS.map(([value, label]) => (
                <label key={value} className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={qualityLabels.includes(value)}
                    onChange={(event) =>
                      setQualityLabels((current) =>
                        event.target.checked
                          ? [...current, value]
                          : current.filter((item) => item !== value)
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>

          <label className="space-y-1 text-xs lg:col-span-2">
            <span className="text-muted-foreground">
              理想答案{needsCorrection ? '（差评样本必填）' : '（可选）'}
            </span>
            <textarea
              value={idealAnswer}
              onChange={(event) => setIdealAnswer(event.target.value)}
              rows={5}
              maxLength={16000}
              className="w-full rounded-lg border border-border bg-background px-3 py-2"
            />
          </label>

          <label className="space-y-1 text-xs lg:col-span-2">
            <span className="text-muted-foreground">审核备注</span>
            <textarea
              value={reviewNote}
              onChange={(event) => setReviewNote(event.target.value)}
              rows={2}
              maxLength={1000}
              className="w-full rounded-lg border border-border bg-background px-3 py-2"
            />
          </label>

          <div className="flex gap-2 lg:col-span-2">
            <button
              type="button"
              disabled={busy || !canApprove}
              onClick={() => void onReview(candidate, payload('approved'))}
              className="rounded-lg bg-brand px-3 py-1.5 text-xs text-brand-foreground disabled:opacity-50"
            >
              批准
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onReview(candidate, payload('rejected'))}
              className="rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-50"
            >
              拒绝
            </button>
          </div>
        </div>
      )}
    </article>
  );
}
