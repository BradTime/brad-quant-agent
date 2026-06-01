import { describe, it, expect } from 'vitest';
import { formatPercent, formatAmount, formatVolume } from './format';

describe('formatPercent', () => {
  it('adds + for non-negative and fixes 2 decimals', () => {
    expect(formatPercent(1.234)).toBe('+1.23%');
    expect(formatPercent(-1.234)).toBe('-1.23%');
    expect(formatPercent(0)).toBe('+0.00%');
    expect(formatPercent(1.2, false)).toBe('1.20%');
  });
});

describe('formatAmount', () => {
  it('auto-selects 亿/万/元 and handles nullish/NaN', () => {
    expect(formatAmount(1.5e8)).toBe('1.50亿');
    expect(formatAmount(2e4)).toBe('2.00万');
    expect(formatAmount(500)).toBe('500');
    expect(formatAmount(null)).toBe('—');
    expect(formatAmount(undefined)).toBe('—');
    expect(formatAmount(Number.NaN)).toBe('—');
  });
});

describe('formatVolume', () => {
  it('converts shares to hands and uses 万手 above 1e4', () => {
    expect(formatVolume(1_000_000, '股')).toBe('1.00万手');
    expect(formatVolume(50, '手')).toBe('50手');
    expect(formatVolume(null)).toBe('—');
  });
});
