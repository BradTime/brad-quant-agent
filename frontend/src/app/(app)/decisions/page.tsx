'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, LockKeyhole, Shield, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { decisionRoomApi } from '@/lib/api/decision-room';
import { useDecisionRoomSocket } from '@/hooks/useDecisionRoomSocket';
import type { DecisionRoomMode } from '@/types/decision-room';

function errorMessage(error: unknown): string {
  if (
    error &&
    typeof error === 'object' &&
    'message' in error &&
    typeof error.message === 'string'
  ) {
    return error.message;
  }
  return '操作失败，请检查输入后重试';
}

export default function DecisionRoomPage() {
  useDecisionRoomSocket();
  const queryClient = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [codes, setCodes] = useState('600000.SH');
  const [asOf, setAsOf] = useState(today);
  const [selectedId, setSelectedId] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [reason, setReason] = useState('基于当前完整证据进行人工审慎复核');
  const [mode, setMode] = useState<DecisionRoomMode>('research_only');
  const [enrollment, setEnrollment] = useState<{
    secret: string;
    recoveryCodes: string[];
  } | null>(null);

  const state = useQuery({
    queryKey: ['decision-room', 'state'],
    queryFn: decisionRoomApi.state,
  });
  const history = useQuery({
    queryKey: ['decision-room', 'history'],
    queryFn: decisionRoomApi.history,
  });
  const notifications = useQuery({
    queryKey: ['decision-room', 'notifications'],
    queryFn: decisionRoomApi.notifications,
  });
  const behavior = useQuery({
    queryKey: ['decision-room', 'behavior'],
    queryFn: decisionRoomApi.behavior,
  });
  const detail = useQuery({
    queryKey: ['decision-room', 'detail', selectedId],
    queryFn: () => decisionRoomApi.detail(selectedId),
    enabled: Boolean(selectedId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['decision-room'] });
  };

  const create = useMutation({
    mutationFn: () =>
      decisionRoomApi.create(
        codes
          .split(',')
          .map((code) => code.trim())
          .filter(Boolean),
        asOf,
      ),
    onSuccess: async (result) => {
      setSelectedId(result.id);
      await refresh();
    },
  });
  const enroll = useMutation({
    mutationFn: () => decisionRoomApi.enrollTotp(password),
    onSuccess: (result) =>
      setEnrollment({
        secret: result.secret,
        recoveryCodes: result.recoveryCodes,
      }),
  });
  const confirm = useMutation({
    mutationFn: () => decisionRoomApi.confirmTotp(totpCode),
    onSuccess: refresh,
  });
  const resetTotp = useMutation({
    mutationFn: async () => {
      const grant = await decisionRoomApi.stepUp(
        password,
        totpCode,
        'reset_totp',
      );
      return decisionRoomApi.resetTotp(grant.token);
    },
  });
  const changeMode = useMutation({
    mutationFn: async () => {
      const grant = await decisionRoomApi.stepUp(
        password,
        totpCode,
        'change_decision_mode',
      );
      return decisionRoomApi.changeMode(mode, reason, grant.token);
    },
    onSuccess: refresh,
  });
  const killSwitch = useMutation({
    mutationFn: async () => {
      if (!state.data?.killSwitchActive) {
        return decisionRoomApi.activateKill(reason);
      }
      const grant = await decisionRoomApi.stepUp(
        password,
        totpCode,
        'release_kill_switch',
      );
      return decisionRoomApi.releaseKill(reason, grant.token);
    },
    onSuccess: refresh,
  });
  const override = useMutation({
    mutationFn: async (action: 'accept' | 'reject') => {
      if (!selectedId) throw new Error('请先选择一条决策');
      const grant = await decisionRoomApi.stepUp(
        password,
        totpCode,
        'override_decision',
      );
      return decisionRoomApi.override(selectedId, action, reason, grant.token);
    },
    onSuccess: refresh,
  });

  const activeError =
    create.error ??
    enroll.error ??
    confirm.error ??
    resetTotp.error ??
    changeMode.error ??
    killSwitch.error ??
    override.error;

  return (
    <div className="space-y-6 p-5 sm:p-8 lg:p-10">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-brand" />
            私人策略决策室
          </CardTitle>
          <CardDescription>
            M4 六阶段证据复核与 M5 控制面。所有输出均不批准、不提交订单。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">模式</p>
            <p className="font-medium">{state.data?.mode ?? '加载中'}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Kill Switch</p>
            <p className="font-medium">
              {state.data?.killSwitchActive ? '已触发' : '未触发'}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">执行权限</p>
            <p className="font-medium text-amber-600">始终关闭</p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>发起四层决策</CardTitle>
            <CardDescription>仅提交代码与最新已物化交易日。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Label htmlFor="decision-codes">代码（逗号分隔，最多 20 个）</Label>
            <Input
              id="decision-codes"
              value={codes}
              onChange={(event) => setCodes(event.target.value)}
            />
            <Label htmlFor="decision-date">交易日</Label>
            <Input
              id="decision-date"
              type="date"
              value={asOf}
              onChange={(event) => setAsOf(event.target.value)}
            />
            <Button onClick={() => create.mutate()} disabled={create.isPending}>
              {create.isPending ? '生成中…' : '生成决策链'}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LockKeyhole className="h-5 w-5" />
              二次验证与控制
            </CardTitle>
            <CardDescription>
              模式切换、人工覆盖和解除 Kill Switch 均需密码 + TOTP。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              type="password"
              placeholder="账户密码"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <Input
              inputMode="text"
              placeholder="6 位动态验证码（重置时可填恢复码）"
              value={totpCode}
              onChange={(event) => setTotpCode(event.target.value)}
            />
            {!state.data?.totp.enabled && (
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => enroll.mutate()}>
                  生成 TOTP 密钥
                </Button>
                <Button variant="outline" onClick={() => confirm.mutate()}>
                  确认启用
                </Button>
              </div>
            )}
            {state.data?.totp.enabled && (
              <Button
                variant="outline"
                onClick={() => resetTotp.mutate()}
                disabled={resetTotp.isPending}
              >
                使用恢复码重置 TOTP（会退出登录）
              </Button>
            )}
            {enrollment && (
              <div className="rounded-md border border-amber-500/40 p-3 text-xs">
                <p>密钥：{enrollment.secret}</p>
                <p className="mt-2 font-medium">恢复码仅显示一次：</p>
                <p className="break-all">
                  {enrollment.recoveryCodes.join(' · ')}
                </p>
              </div>
            )}
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="必填原因（至少 10 字）"
            />
            <div className="flex flex-wrap gap-2">
              <select
                className="rounded-md border border-border bg-background px-3 text-sm"
                value={mode}
                onChange={(event) =>
                  setMode(event.target.value as DecisionRoomMode)
                }
              >
                <option value="research_only">研究模式</option>
                <option value="manual_review">人工复核</option>
                <option value="simulation_ready">模拟准备</option>
              </select>
              <Button variant="outline" onClick={() => changeMode.mutate()}>
                切换模式
              </Button>
              <Button
                variant={state.data?.killSwitchActive ? 'outline' : 'destructive'}
                onClick={() => killSwitch.mutate()}
              >
                <ShieldAlert className="mr-2 h-4 w-4" />
                {state.data?.killSwitchActive ? '解除 Kill Switch' : '立即停止'}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {activeError && (
        <div className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">
          {errorMessage(activeError)}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>决策历史</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {history.data?.items.map((item) => (
              <button
                key={item.id}
                className="w-full rounded-md border border-border p-3 text-left hover:bg-muted"
                onClick={() => setSelectedId(item.id)}
              >
                <div className="flex items-center justify-between text-sm">
                  <span>{item.asOf}</span>
                  <span>{item.status}</span>
                </div>
                {item.severeDisagreement && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-amber-600">
                    <AlertTriangle className="h-3 w-3" /> 严重分歧
                  </p>
                )}
              </button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>六阶段证据</CardTitle>
            <CardDescription>
              事件 Hash 与前序 Hash 可用于审计链回放。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {detail.data?.events.map((event) => (
              <details
                key={event.sequence}
                className="rounded-md border border-border p-3"
              >
                <summary className="cursor-pointer text-sm font-medium">
                  {event.sequence}. {event.stage} · {event.actor}
                </summary>
                <p className="mt-2 break-all text-[11px] text-muted-foreground">
                  {event.eventSha256}
                </p>
                <pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs">
                  {JSON.stringify(event.output, null, 2)}
                </pre>
              </details>
            ))}
            {detail.data && (
              <div className="flex gap-2 pt-2">
                <Button
                  variant="outline"
                  onClick={() => override.mutate('reject')}
                >
                  人工拒绝
                </Button>
                <Button onClick={() => override.mutate('accept')}>
                  接受研究候选
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>风险与分歧通知</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {notifications.data?.items.map((item) => (
            <div key={item.id} className="rounded-md border border-border p-3">
              <p className="text-sm font-medium">{item.message}</p>
              <p className="text-xs text-muted-foreground">
                {item.severity} · {new Date(item.createdAt).toLocaleString()}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>人工覆盖行为归因</CardTitle>
          <CardDescription>
            使用相同持仓、容量、涨跌停、滑点与费税，对比策略内结果和人工覆盖结果。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {behavior.data?.items.map((item) => (
            <div
              key={item.id}
              className="grid gap-1 rounded-md border border-border p-3 text-sm md:grid-cols-4"
            >
              <span>{item.signalDate} → {item.labelDate}</span>
              <span>策略 {(item.strategyReturn * 100).toFixed(2)}%</span>
              <span>人工 {(item.humanReturn * 100).toFixed(2)}%</span>
              <span
                className={
                  item.returnDelta >= 0 ? 'text-emerald-600' : 'text-destructive'
                }
              >
                差值 {(item.returnDelta * 100).toFixed(2)}%
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
