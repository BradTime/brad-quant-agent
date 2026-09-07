function getDsn(): string | undefined {
  return process.env.NEXT_PUBLIC_SENTRY_DSN?.trim() || undefined;
}

function parseDsn(dsn: string): { ingest: string; publicKey: string } | null {
  try {
    const url = new URL(dsn);
    const publicKey = url.username;
    const projectId = url.pathname.replace(/^\//, '');
    if (!publicKey || !projectId) return null;
    return {
      ingest: `https://${url.host}/api/${projectId}/envelope/`,
      publicKey,
    };
  } catch {
    return null;
  }
}

function reportViaEnvelope(error: Error, extra?: Record<string, unknown>): void {
  const dsn = getDsn();
  if (!dsn) return;
  const target = parseDsn(dsn);
  if (!target) return;

  const eventId =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '')
      : `${Date.now()}${Math.random().toString(16).slice(2)}`;

  const event = {
    event_id: eventId,
    timestamp: Date.now() / 1000,
    platform: 'javascript',
    level: 'error',
    exception: {
      values: [
        {
          type: error.name,
          value: error.message,
          stacktrace: error.stack ? { frames: [{ filename: error.stack.slice(0, 512) }] } : undefined,
        },
      ],
    },
    extra,
  };
  const item = `${JSON.stringify({ type: 'event' })}\n${JSON.stringify(event)}`;
  const envelope = `${JSON.stringify({
    event_id: eventId,
    sent_at: new Date().toISOString(),
  })}\n${item}`;

  void fetch(target.ingest, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-sentry-envelope',
      'X-Sentry-Auth': `Sentry sentry_version=7, sentry_client=quant-agent/1.0, sentry_key=${target.publicKey}`,
    },
    body: envelope,
    keepalive: true,
  }).catch(() => {
    /* best-effort */
  });
}

/** Report a client error when NEXT_PUBLIC_SENTRY_DSN is configured. */
export function captureException(
  error: Error,
  extra?: Record<string, unknown>,
): void {
  if (!getDsn()) {
    return;
  }
  if (process.env.NODE_ENV === 'development') {
    console.error('[Sentry envelope]', error, extra);
  }
  reportViaEnvelope(error, extra);
}
