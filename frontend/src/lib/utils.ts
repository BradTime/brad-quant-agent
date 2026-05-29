import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * 合并 Tailwind CSS 类名
 * 使用 twMerge 解决类名冲突问题
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

