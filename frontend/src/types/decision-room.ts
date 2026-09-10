export type DecisionRoomMode =
  | 'research_only'
  | 'manual_review'
  | 'simulation_ready';

export interface DecisionRoomState {
  mode: DecisionRoomMode;
  killSwitchActive: boolean;
  capitalLimit: number;
  leverageLimit: number;
  highWaterMark: number;
  executionEnabled: false;
  totp: { enabled: boolean; pending: boolean };
}

export interface DecisionSummary {
  id: string;
  asOf: string;
  status: string;
  currentStage: string;
  severeDisagreement: boolean;
  createdAt: string;
}

export interface DecisionEvent {
  sequence: number;
  stage: string;
  actor: string;
  eventSha256: string;
  previousEventSha256: string | null;
  output: Record<string, unknown>;
}

export interface DecisionDetail extends DecisionSummary {
  protocolVersion: string;
  allocationDecisionId: string;
  events: DecisionEvent[];
}

export interface RoomNotification {
  id: string;
  notificationId: string;
  eventType: string;
  severity: string;
  resourceId: string;
  message: string;
  roomPath: string;
  createdAt: string;
}
