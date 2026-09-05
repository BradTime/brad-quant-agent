'use client';

import { useState } from 'react';
import { ThumbsDown, ThumbsUp, X } from 'lucide-react';
import { submitTrainingFeedback } from '@/lib/api/training';
import { cn } from '@/lib/utils';

const ISSUE_OPTIONS = [
  ['incorrect', '事实或数值错误'],
  ['unsupported', '缺少工具依据'],
  ['missing_data', '未诚实说明缺失数据'],
  ['wrong_tool', '工具选择错误'],
  ['unsafe_advice', '出现不当投资建议'],
  ['unclear', '表达不清晰'],
  ['other', '其他'],
] as const;

export function MessageFeedback({
  messageId,
  current,
  disabled = false,
  onSaved,
  onError,
}: {
  messageId: string;
  current?: 'up' | 'down';
  disabled?: boolean;
  onSaved: (rating: 'up' | 'down') => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState<'up' | 'down'>(current ?? 'up');
  const [labels, setLabels] = useState<string[]>([]);
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);

  const choose = (value: 'up' | 'down') => {
    setRating(value);
    setOpen(true);
    if (value === 'up') setLabels([]);
  };

  const submit = async () => {
    if (rating === 'down' && labels.length === 0) {
      onError('差评至少需要选择一个问题标签');
      return;
    }
    setSaving(true);
    try {
      await submitTrainingFeedback(messageId, {
        rating,
        issueLabels: labels,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      });
      onSaved(rating);
      setOpen(false);
    } catch (error) {
      onError(
        typeof error === 'object' && error && 'message' in error
          ? String(error.message)
          : '提交反馈失败'
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-2 border-t border-border/60 pt-2">
      <div className="flex items-center gap-1">
        <span className="mr-1 text-[10px] text-muted-foreground">
          评价并贡献此回答
        </span>
        <button
          type="button"
          aria-label="回答有帮助"
          disabled={disabled}
          onClick={() => choose('up')}
          className={cn(
            'rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-50',
            current === 'up' && 'text-brand'
          )}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="回答需改进"
          disabled={disabled}
          onClick={() => choose('down')}
          className={cn(
            'rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-50',
            current === 'down' && 'text-destructive'
          )}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
      </div>

      {open && (
        <div className="mt-2 space-y-2 rounded-lg bg-muted/50 p-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">
              {rating === 'up' ? '这条回答有帮助' : '请选择需要改进的地方'}
            </span>
            <button
              type="button"
              aria-label="关闭反馈表单"
              onClick={() => setOpen(false)}
              className="text-muted-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {rating === 'down' && (
            <div className="grid gap-1 sm:grid-cols-2">
              {ISSUE_OPTIONS.map(([value, label]) => (
                <label key={value} className="flex items-center gap-1.5 text-[11px]">
                  <input
                    type="checkbox"
                    checked={labels.includes(value)}
                    onChange={(event) =>
                      setLabels((currentLabels) =>
                        event.target.checked
                          ? [...currentLabels, value]
                          : currentLabels.filter((item) => item !== value)
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          )}
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            rows={2}
            placeholder="可选：补充说明或建议的改法"
            className="w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-xs"
          />
          <button
            type="button"
            disabled={saving}
            onClick={() => void submit()}
            className="rounded-md bg-brand px-2.5 py-1.5 text-xs text-brand-foreground disabled:opacity-50"
          >
            {saving ? '提交中…' : '提交反馈'}
          </button>
        </div>
      )}
    </div>
  );
}
