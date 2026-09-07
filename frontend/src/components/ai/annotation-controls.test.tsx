import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { CandidateReviewCard } from './candidate-review-card';
import { MessageFeedback } from './message-feedback';

describe('structured training annotation controls', () => {
  it('renders accessible answer rating controls without prompt dialogs', () => {
    const html = renderToStaticMarkup(
      <MessageFeedback
        messageId="message-1"
        onSaved={() => undefined}
        onError={() => undefined}
      />
    );
    expect(html).toContain('回答有帮助');
    expect(html).toContain('回答需改进');
    expect(html).not.toContain('window.prompt');
  });

  it('renders task, correction, quality and review fields', () => {
    const html = renderToStaticMarkup(
      <CandidateReviewCard
        candidate={{
          id: 'candidate-1',
          status: 'pending',
          taskType: 'grounded-response',
          sourceType: 'chat',
          input: '问题',
          output: '错误回答',
          toolTrace: [],
          rating: 'down',
          issueLabels: ['incorrect'],
          comment: '数值错误',
          idealAnswer: null,
          qualityLabels: [],
          reviewNote: null,
          createdAt: '2026-09-02T00:00:00Z',
        }}
        busy={false}
        onReview={async () => undefined}
      />
    );
    expect(html).toContain('训练任务类型');
    expect(html).toContain('理想答案（差评样本必填）');
    expect(html).toContain('质量标签');
    expect(html).toContain('审核备注');
  });
});
