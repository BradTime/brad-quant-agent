import type { ApiResponse } from '@/types';
import type {
  BehaviorAttribution,
  DecisionDetail,
  DecisionRoomMode,
  DecisionRoomState,
  DecisionSummary,
  RoomNotification,
} from '@/types/decision-room';
import { apiClient } from './client';

async function unwrap<T>(request: Promise<unknown>): Promise<T> {
  const envelope = (await request) as ApiResponse<T>;
  return envelope.data;
}

export const decisionRoomApi = {
  state: () => unwrap<DecisionRoomState>(apiClient.get('/decision-room')),
  history: () =>
    unwrap<{ items: DecisionSummary[] }>(apiClient.get('/decisions')),
  detail: (id: string) =>
    unwrap<DecisionDetail>(apiClient.get(`/decisions/${id}`)),
  create: (codes: string[], asOf: string) =>
    unwrap<DecisionDetail>(apiClient.post('/decisions', { codes, asOf })),
  notifications: () =>
    unwrap<{ items: RoomNotification[] }>(
      apiClient.get('/decision-room/notifications'),
    ),
  behavior: () =>
    unwrap<{ items: BehaviorAttribution[] }>(
      apiClient.get('/decision-room/behavior'),
    ),
  enrollTotp: (password: string) =>
    unwrap<{ secret: string; otpauthUri: string; recoveryCodes: string[] }>(
      apiClient.post('/decision-room/totp/enroll', { password }),
    ),
  confirmTotp: (code: string) =>
    unwrap<{ enabled: boolean }>(
      apiClient.post('/decision-room/totp/confirm', { code }),
    ),
  stepUp: (
    password: string,
    code: string,
    purpose:
      | 'change_decision_mode'
      | 'override_decision'
      | 'release_kill_switch'
      | 'reset_totp'
      | 'submit_broker_simulation',
  ) =>
    unwrap<{ token: string }>(
      apiClient.post('/decision-room/step-up', {
        password,
        ...(code.replaceAll('-', '').length === 6
          ? { code }
          : { recoveryCode: code }),
        purpose,
      }),
    ),
  resetTotp: (stepUpToken: string) =>
    unwrap<{ enabled: false; reset: true; tokensRevoked: true }>(
      apiClient.post('/decision-room/totp/reset', { stepUpToken }),
    ),
  changeMode: (
    mode: DecisionRoomMode,
    reason: string,
    stepUpToken: string,
  ) =>
    unwrap<{ mode: DecisionRoomMode; executionEnabled: false }>(
      apiClient.patch('/decision-room/mode', {
        mode,
        reason,
        stepUpToken,
      }),
    ),
  activateKill: (reason: string) =>
    unwrap<{ killSwitchActive: true }>(
      apiClient.post('/decision-room/kill-switch/activate', { reason }),
    ),
  releaseKill: (reason: string, stepUpToken: string) =>
    unwrap<{ killSwitchActive: false }>(
      apiClient.post('/decision-room/kill-switch/release', {
        reason,
        stepUpToken,
      }),
    ),
  override: (
    runId: string,
    action: 'accept' | 'reject',
    reason: string,
    stepUpToken: string,
  ) =>
    unwrap<{ id: string; executionApproved: false }>(
      apiClient.post(`/decision-room/decisions/${runId}/override`, {
        action,
        reason,
        stepUpToken,
      }),
    ),
};
