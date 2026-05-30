/**
 * 格式化工具函数
 */

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number, showSign = true): string {
  const sign = showSign && value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

export function formatNumber(value: number, decimals = 2): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** 金额（元）→ 亿 / 万 / 元，自动选单位 */
export function formatAmount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return value.toFixed(0);
}

/** 成交量（股）→ 万手 / 手（A 股快照成交量单位为手时直接传手数） */
export function formatVolume(value: number | null | undefined, unit: '股' | '手' = '股'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const hands = unit === '股' ? value / 100 : value;
  if (Math.abs(hands) >= 1e4) return `${(hands / 1e4).toFixed(2)}万手`;
  return `${hands.toFixed(0)}手`;
}

export function formatDate(date: string | Date, format: 'short' | 'long' | 'date' = 'short'): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  
  if (format === 'date') {
    return d.toLocaleDateString('zh-CN');
  }
  
  if (format === 'long') {
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
  
  return d.toLocaleString('zh-CN');
}


