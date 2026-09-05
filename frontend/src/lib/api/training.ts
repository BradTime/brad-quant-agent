import { z } from 'zod';
import { apiClient } from './client';

const consentSchema = z.object({
  sessionId: z.string(),
  enabled: z.boolean(),
  policyVersion: z.string(),
  grantedAt: z.string().nullable(),
  revokedAt: z.string().nullable(),
});

export type TrainingConsent = z.infer<typeof consentSchema>;

export async function getTrainingConsent(
  sessionId: string
): Promise<TrainingConsent> {
  const response = await apiClient.get<TrainingConsent>(
    `/training/consent/${sessionId}`
  );
  return consentSchema.parse(response.data);
}

export async function setTrainingConsent(
  sessionId: string,
  enabled: boolean
): Promise<TrainingConsent> {
  const response = await apiClient.put<TrainingConsent>(
    `/training/consent/${sessionId}`,
    { enabled }
  );
  return consentSchema.parse(response.data);
}

export async function submitTrainingFeedback(
  assistantMessageId: string,
  payload: {
    rating: 'up' | 'down';
    issueLabels?: string[];
    comment?: string;
  }
): Promise<void> {
  await apiClient.put(`/training/feedback/${assistantMessageId}`, payload);
}

export interface TrainingCandidate {
  id: string;
  status: 'pending' | 'approved' | 'rejected' | 'deprecated';
  taskType: 'tool-routing' | 'grounded-response' | 'honesty-compliance';
  sourceType: string;
  input: string;
  output: string;
  toolTrace: Array<Record<string, unknown>>;
  rating: 'up' | 'down';
  issueLabels: string[];
  comment: string | null;
  idealAnswer: string | null;
  qualityLabels: string[];
  reviewNote: string | null;
  createdAt: string;
}

const candidateSchema: z.ZodType<TrainingCandidate> = z.object({
  id: z.string(),
  status: z.enum(['pending', 'approved', 'rejected', 'deprecated']),
  taskType: z.enum([
    'tool-routing',
    'grounded-response',
    'honesty-compliance',
  ]),
  sourceType: z.string(),
  input: z.string(),
  output: z.string(),
  toolTrace: z.array(z.record(z.string(), z.unknown())),
  rating: z.enum(['up', 'down']),
  issueLabels: z.array(z.string()),
  comment: z.string().nullable(),
  idealAnswer: z.string().nullable(),
  qualityLabels: z.array(z.string()),
  reviewNote: z.string().nullable(),
  createdAt: z.string(),
});

export async function listTrainingCandidates(
  filters: { status?: string; taskType?: string; rating?: string } = {}
): Promise<TrainingCandidate[]> {
  const response = await apiClient.get<TrainingCandidate[]>(
    '/training/admin/candidates',
    { params: filters }
  );
  return z.array(candidateSchema).parse(response.data ?? []);
}

export async function reviewTrainingCandidate(
  id: string,
  payload: {
    status: 'approved' | 'rejected' | 'deprecated';
    taskType: TrainingCandidate['taskType'];
    idealAnswer?: string;
    qualityLabels?: string[];
    reviewNote?: string;
  }
): Promise<void> {
  await apiClient.put(`/training/admin/candidates/${id}`, payload);
}

export async function buildTrainingDataset(version: string): Promise<void> {
  await apiClient.post('/training/admin/datasets', { version });
}

export async function getTrainingReadiness(): Promise<{
  ready: boolean;
  approved: number;
  taskCounts: Record<string, number>;
  estimatedValidation: number;
  reasons: string[];
}> {
  const schema = z.object({
    ready: z.boolean(),
    approved: z.number(),
    taskCounts: z.record(z.string(), z.number()),
    estimatedValidation: z.number(),
    reasons: z.array(z.string()),
  });
  const response = await apiClient.get<z.infer<typeof schema>>(
    '/training/admin/readiness'
  );
  return schema.parse(response.data);
}
