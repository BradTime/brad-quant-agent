'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  backtestApi,
  type StrategyCatalogItem,
} from '@/lib/api/backtest';
import type {
  BuiltinStrategyType,
  Strategy,
  StrategyCreateRequest,
} from '@/types/strategy';

interface StrategyFormProps {
  initial?: Strategy;
  submitLabel: string;
  submitting?: boolean;
  onSubmit: (data: StrategyCreateRequest) => Promise<void>;
}

function defaultsFor(item: StrategyCatalogItem): Record<string, number> {
  return Object.fromEntries(item.params.map((param) => [param.key, param.default]));
}

function messageFrom(error: unknown): string {
  if (typeof error === 'object' && error && 'message' in error) {
    return String(error.message);
  }
  return '保存失败，请稍后重试';
}

export function StrategyForm({
  initial,
  submitLabel,
  submitting = false,
  onSubmit,
}: StrategyFormProps) {
  const [catalog, setCatalog] = useState<StrategyCatalogItem[]>([]);
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [builtinType, setBuiltinType] = useState<BuiltinStrategyType>(
    initial?.builtinType ?? 'dual_ma',
  );
  const [params, setParams] = useState<Record<string, number>>(initial?.params ?? {});
  const [catalogError, setCatalogError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const initialBuiltinType = initial?.builtinType;

  useEffect(() => {
    void backtestApi.strategyCatalog()
      .then(({ items }) => {
        setCatalog(items);
        const selected = items.find(
          (item) => item.type === (initialBuiltinType ?? 'dual_ma'),
        );
        if (selected) {
          setParams((current) =>
            Object.keys(current).length > 0 ? current : defaultsFor(selected),
          );
        }
      })
      .catch(() => setCatalogError('内置策略目录加载失败，请刷新后重试'));
  }, [initialBuiltinType]);

  const current = useMemo(
    () => catalog.find((item) => item.type === builtinType),
    [catalog, builtinType],
  );

  const selectBuiltin = (value: BuiltinStrategyType) => {
    setBuiltinType(value);
    const selected = catalog.find((item) => item.type === value);
    if (selected) setParams(defaultsFor(selected));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitError('');
    if (!name.trim()) {
      setSubmitError('请输入策略名称');
      return;
    }
    if (!current) {
      setSubmitError('请选择有效的内置策略');
      return;
    }
    try {
      await onSubmit({
        name: name.trim(),
        description: description.trim(),
        builtinType,
        params,
      });
    } catch (error) {
      setSubmitError(messageFrom(error));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-6">
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="strategy-name">策略名称</Label>
          <Input
            id="strategy-name"
            value={name}
            maxLength={128}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：低波动双均线"
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="builtin-type">内置策略</Label>
          <select
            id="builtin-type"
            value={builtinType}
            onChange={(event) =>
              selectBuiltin(event.target.value as BuiltinStrategyType)
            }
            disabled={catalog.length === 0}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          >
            {catalog.length === 0 && <option value="dual_ma">加载中…</option>}
            {catalog.map((item) => (
              <option key={item.type} value={item.type}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="strategy-description">策略说明</Label>
        <Textarea
          id="strategy-description"
          value={description}
          maxLength={4000}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="记录策略逻辑、适用市场环境和风险边界"
          rows={4}
        />
      </div>

      <section className="rounded-2xl border border-border bg-muted/20 p-5">
        <div className="mb-4">
          <h2 className="font-medium">参数配置</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {current?.description ?? '参数范围由后端内置策略目录统一约束。'}
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {current?.params.map((param) => (
            <div key={param.key} className="space-y-2">
              <Label htmlFor={`param-${param.key}`}>{param.label}</Label>
              <Input
                id={`param-${param.key}`}
                type="number"
                value={params[param.key] ?? param.default}
                min={param.min}
                max={param.max}
                step={param.type === 'int' ? 1 : 0.01}
                onChange={(event) =>
                  setParams((currentParams) => ({
                    ...currentParams,
                    [param.key]: Number(event.target.value),
                  }))
                }
                required
              />
              <p className="text-xs text-muted-foreground">
                键名 {param.key}
                {param.min != null && param.max != null
                  ? ` · 范围 ${param.min}–${param.max}`
                  : ''}
              </p>
            </div>
          ))}
        </div>
      </section>

      {(catalogError || submitError) && (
        <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {catalogError || submitError}
        </p>
      )}

      <div className="flex justify-end">
        <Button type="submit" disabled={submitting || !current || Boolean(catalogError)}>
          {submitting && <Loader2 className="animate-spin" />}
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
