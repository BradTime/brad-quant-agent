export const MAX_BACKTEST_CAPITAL = 1_000_000_000_000;
export const MAX_GRID_COMBINATIONS = 64;

export interface BacktestFormValues {
  codes: string;
  start: string;
  end: string;
  initialCapital: number;
  slippage: number;
}

export function parseGridCandidates(raw: string): number[] {
  const parts = raw.split(',').map((value) => value.trim());
  if (parts.length === 0 || parts.some((value) => value === '')) {
    throw new Error('每个参数都必须提供候选值');
  }
  const values = parts.map(Number);
  if (values.some((value) => !Number.isFinite(value))) {
    throw new Error('候选值必须是有限数字');
  }
  return values;
}

export function validateBacktestForm(
  values: BacktestFormValues,
  paramGrid?: Record<string, number[]>,
): string {
  if (!values.codes.split(',').some((code) => code.trim())) {
    return '请至少选择一个标的';
  }
  if (!values.start || !values.end || values.start > values.end) {
    return '开始日期不能晚于结束日期';
  }
  if (
    !Number.isFinite(values.initialCapital) ||
    values.initialCapital <= 0 ||
    values.initialCapital > MAX_BACKTEST_CAPITAL
  ) {
    return `初始资金必须大于 0 且不超过 ${MAX_BACKTEST_CAPITAL}`;
  }
  if (!Number.isFinite(values.slippage) || values.slippage < 0 || values.slippage > 0.1) {
    return '滑点必须在 0 到 0.1 之间';
  }
  if (paramGrid) {
    const combinations = Object.values(paramGrid).reduce(
      (count, candidates) => count * candidates.length,
      1,
    );
    if (combinations > MAX_GRID_COMBINATIONS) {
      return `参数组合不能超过 ${MAX_GRID_COMBINATIONS} 组`;
    }
  }
  return '';
}
