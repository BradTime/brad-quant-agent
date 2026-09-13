import type { ApiResponse } from '@/types';
import type {
  PredictionOpsDashboard,
  PredictionOpsJob,
} from '@/types/prediction-ops';
import { apiClient } from './client';

async function unwrap<T>(request: Promise<unknown>): Promise<T> {
  const envelope = (await request) as ApiResponse<T>;
  return envelope.data;
}

export const predictionOpsApi = {
  dashboard: () =>
    unwrap<PredictionOpsDashboard>(apiClient.get('/prediction-ops')),
  enqueue: (payload: {
    jobType: 'weekly_train' | 'daily_infer';
    scheduledFor: string;
    codes: string[];
    provider: 'lightgbm' | 'xgboost';
  }) =>
    unwrap<PredictionOpsJob>(
      apiClient.post('/prediction-ops/jobs', payload),
    ),
};
