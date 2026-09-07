import { describe, expect, it } from 'vitest';
import {
  parseGridCandidates,
  validateBacktestForm,
  type BacktestFormValues,
} from './backtest-validation';

const valid: BacktestFormValues = {
  codes: '600000.SH',
  start: '2024-01-01',
  end: '2024-12-31',
  initialCapital: 1_000_000,
  slippage: 0.001,
};

describe('validateBacktestForm', () => {
  it.each([
    [{ ...valid, codes: '  ' }, '至少选择一个标的'],
    [{ ...valid, start: '2025-01-01' }, '开始日期不能晚于结束日期'],
    [{ ...valid, initialCapital: 0 }, '初始资金'],
    [{ ...valid, initialCapital: Number.POSITIVE_INFINITY }, '初始资金'],
    [{ ...valid, slippage: -1 }, '滑点'],
    [{ ...valid, slippage: 0.11 }, '滑点'],
  ])('rejects invalid base values', (values, message) => {
    expect(validateBacktestForm(values)).toContain(message);
  });

  it('accepts valid base values', () => {
    expect(validateBacktestForm(valid)).toBe('');
  });

  it('rejects grids above 64 combinations', () => {
    expect(
      validateBacktestForm(valid, {
        fast: [1, 2, 3, 4, 5, 6, 7, 8],
        slow: [10, 20, 30, 40, 50, 60, 70, 80, 90],
      }),
    ).toContain('64');
  });
});

describe('parseGridCandidates', () => {
  it('rejects non-finite and empty candidates', () => {
    expect(() => parseGridCandidates('1,Infinity')).toThrow('有限数字');
    expect(() => parseGridCandidates(' , ')).toThrow('候选值');
  });

  it('returns finite numeric candidates', () => {
    expect(parseGridCandidates('5, 10')).toEqual([5, 10]);
  });
});
