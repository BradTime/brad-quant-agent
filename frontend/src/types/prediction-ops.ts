export interface PredictionOpsJob {
  id: string;
  jobType: 'weekly_train' | 'daily_infer';
  scheduledFor: string;
  status: string;
  attempts: number;
  errorCode: string | null;
  createdAt: string;
}

export interface PredictionModelOps {
  id: string;
  version: string;
  provider: string;
  status: string;
  isChampion: boolean;
  trainingStart: string;
  trainingEnd: string;
  metrics: Record<string, unknown>;
}

export interface EvolutionProgramOps {
  id: string;
  modelRunId: string;
  stage: string;
  simulationSessions: number;
  shadowSessions: number;
  metrics: Record<string, unknown>;
  failureReason: string | null;
}

export interface DataCompleteness {
  latestDate: string | null;
  codes: string[];
  snapshotCoverage?: number;
  membershipCoverage?: number;
  barCoverage?: number;
  adjustFactorCodeCoverage?: number;
  ready: boolean;
}

export interface PredictionOpsDashboard {
  automationEnabled: boolean;
  provider: string;
  models: PredictionModelOps[];
  programs: EvolutionProgramOps[];
  jobs: PredictionOpsJob[];
  dataCompleteness: DataCompleteness;
}
