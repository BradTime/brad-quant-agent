import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { StrategyForm } from './strategy-form';

describe('StrategyForm', () => {
  it('renders a catalog-backed form without a strategy code editor', () => {
    const html = renderToStaticMarkup(
      <StrategyForm
        submitLabel="保存策略"
        onSubmit={vi.fn(async () => undefined)}
      />,
    );

    expect(html).toContain('内置策略');
    expect(html).toContain('参数配置');
    expect(html).not.toContain('strategy-code');
    expect(html).not.toContain('Python 代码');
  });
});
