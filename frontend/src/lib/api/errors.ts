import type { ApiResponse } from '@/types';

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === 'object' && error !== null) {
    const maybeEnvelope = error as Partial<ApiResponse>;
    if (typeof maybeEnvelope.message === 'string' && maybeEnvelope.message) {
      return maybeEnvelope.message;
    }
  }
  return fallback;
}
