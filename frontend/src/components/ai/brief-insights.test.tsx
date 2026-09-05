import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { TraceDetails } from './brief-insights';

describe('TraceDetails', () => {
  it('renders persisted agent input and output for drill-down', () => {
    const html = renderToStaticMarkup(
      <TraceDetails
        entry={{ input: '输入数据包', output: '节点分析结论' }}
        defaultOpen
      />,
    );

    expect(html).toContain('节点输入');
    expect(html).toContain('输入数据包');
    expect(html).toContain('节点输出');
    expect(html).toContain('节点分析结论');
  });

  it('renders nothing when a legacy trace has no persisted details', () => {
    expect(renderToStaticMarkup(<TraceDetails entry={{ node: 'planner' }} />)).toBe('');
  });
});
