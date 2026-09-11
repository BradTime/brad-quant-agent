'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, BrainCircuit, DatabaseZap, Play } from 'lucide-react';
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
import { predictionOpsApi } from '@/lib/api/prediction-ops';

const percent = (value?: number) =>
  value === undefined ? '—' : `${(value * 100).toFixed(1)}%`;

export default function ModelOperationsPage() {
  const queryClient = useQueryClient();
  const [jobType, setJobType] = useState<'weekly_train' | 'daily_infer'>(
    'daily_infer',
  );
  const [provider, setProvider] = useState<'lightgbm' | 'xgboost'>(
    'lightgbm',
  );
  const [scheduledFor, setScheduledFor] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [codes, setCodes] = useState('600000.SH');
  const dashboard = useQuery({
    queryKey: ['prediction-ops'],
    queryFn: predictionOpsApi.dashboard,
    refetchInterval: 60_000,
  });
  const enqueue = useMutation({
    mutationFn: () =>
      predictionOpsApi.enqueue({
        jobType,
        provider,
        scheduledFor,
        codes: codes
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['prediction-ops'] }),
  });
  const completeness = dashboard.data?.dataCompleteness;

  return (
    <div className="space-y-6 p-5 sm:p-8 lg:p-10">
      <div>
        <h1 className="font-display text-2xl">模型运营</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          每周训练、每日推理、M6 观察期和 PIT 数据完整率。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>最新 PIT 日期</CardDescription>
            <CardTitle>{completeness?.latestDate ?? '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>股票池快照</CardDescription>
            <CardTitle>{percent(completeness?.snapshotCoverage)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>日线覆盖</CardDescription>
            <CardTitle>{percent(completeness?.barCoverage)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>自动任务</CardDescription>
            <CardTitle>
              {dashboard.data?.automationEnabled ? '已启用' : '默认关闭'}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            手动入队
          </CardTitle>
          <CardDescription>
            只创建幂等作业；后台 worker 获取租约后执行。
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-5">
          <select
            className="rounded-md border border-border bg-background px-3 text-sm"
            value={jobType}
            onChange={(event) =>
              setJobType(
                event.target.value as 'weekly_train' | 'daily_infer',
              )
            }
          >
            <option value="daily_infer">每日推理</option>
            <option value="weekly_train">每周训练</option>
          </select>
          <select
            className="rounded-md border border-border bg-background px-3 text-sm"
            value={provider}
            onChange={(event) =>
              setProvider(event.target.value as 'lightgbm' | 'xgboost')
            }
          >
            <option value="lightgbm">LightGBM</option>
            <option value="xgboost">XGBoost</option>
          </select>
          <div>
            <Label htmlFor="ops-date" className="sr-only">日期</Label>
            <Input
              id="ops-date"
              type="date"
              value={scheduledFor}
              onChange={(event) => setScheduledFor(event.target.value)}
            />
          </div>
          <Input
            value={codes}
            onChange={(event) => setCodes(event.target.value)}
            placeholder="代码，逗号分隔"
          />
          <Button
            onClick={() => enqueue.mutate()}
            disabled={enqueue.isPending}
          >
            入队
          </Button>
          {enqueue.error && (
            <p className="text-sm text-destructive md:col-span-5">
              作业入队失败，请检查日期、代码和管理员权限。
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BrainCircuit className="h-5 w-5" /> 模型注册表
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {dashboard.data?.models.map((model) => (
              <div key={model.id} className="rounded-md border p-3 text-sm">
                <div className="flex justify-between gap-3">
                  <span className="font-medium">{model.version}</span>
                  <span>
                    {model.status}{model.isChampion ? ' · Champion' : ''}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {model.provider} · {model.trainingStart} → {model.trainingEnd}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" /> Challenger 观察期
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {dashboard.data?.programs.map((program) => (
              <div key={program.id} className="rounded-md border p-3 text-sm">
                <div className="flex justify-between">
                  <span>{program.stage}</span>
                  <span>
                    {program.simulationSessions}/60 · {program.shadowSessions}/20
                  </span>
                </div>
                {program.failureReason && (
                  <p className="mt-1 text-xs text-destructive">
                    {program.failureReason}
                  </p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DatabaseZap className="h-5 w-5" /> 作业历史
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {dashboard.data?.jobs.map((job) => (
            <div
              key={job.id}
              className="grid gap-1 rounded-md border p-3 text-sm md:grid-cols-4"
            >
              <span>{job.jobType}</span>
              <span>{job.scheduledFor}</span>
              <span>{job.status} · 第 {job.attempts} 次</span>
              <span className="text-muted-foreground">
                {job.errorCode ?? '—'}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
