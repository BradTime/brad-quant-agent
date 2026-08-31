# Production deployment baseline

This deployment targets one Linux VM with Docker Compose. Caddy owns ports
80/443, obtains TLS certificates automatically, and keeps the browser on one
origin:

- `/api/*` and `/ws/*` → FastAPI
- everything else → Next.js
- PostgreSQL/pgvector is private to the Compose network

The frontend derives `ws://`/`wss://` from the browser's current origin unless
an explicit development override is configured, so one image works across
domains without embedding a production hostname.

One backend replica intentionally runs HTTP, WebSocket, schedulers, and the job
consumer together. Quote caches, WebSocket user maps, cost gates, and scheduler
leadership are currently process-local; do not scale the backend horizontally
until those coordination points move to Redis/shared infrastructure.

## Host requirements

- Linux VM with Docker Engine and the Compose plugin
- DNS `A`/`AAAA` record for `APP_DOMAIN` pointing to the VM
- inbound TCP 80/443 and UDP 443; PostgreSQL must not be public
- minimum 4 vCPU/8 GB RAM; prefer 16 GB RAM and 100 GB SSD when local
  embeddings and backtests run together

## First deployment

```bash
cp deploy/production.env.example deploy/production.env
chmod 600 deploy/production.env

# Generate secrets and paste them into production.env:
openssl rand -hex 32
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

# Validate interpolation before creating resources.
docker compose \
  --env-file deploy/production.env \
  -f docker-compose.production.yml \
  config --quiet

docker compose \
  --env-file deploy/production.env \
  -f docker-compose.production.yml \
  build backend frontend migrate
docker compose \
  --env-file deploy/production.env \
  -f docker-compose.production.yml \
  up -d postgres
docker compose \
  --env-file deploy/production.env \
  -f docker-compose.production.yml \
  --profile ops run --rm migrate
docker compose \
  --env-file deploy/production.env \
  -f docker-compose.production.yml \
  up -d backend frontend caddy
```

`POSTGRES_PASSWORD` and the password embedded in `DATABASE_URL` must match.
Percent-encode reserved URL characters in `DATABASE_URL`. Production startup
will reject weak JWT keys, the default outbox encryption key, automatic email
verification, incomplete SMTP settings, or a non-HTTPS frontend URL.

Check the deployment:

```bash
curl --fail https://YOUR_DOMAIN/health
curl --fail https://YOUR_DOMAIN/
docker compose \
  --env-file deploy/production.env \
  -f docker-compose.production.yml \
  ps
```

## Updates and rollback

Before every update:

```bash
./deploy/backup-postgres.sh
git pull --ff-only
docker compose --env-file deploy/production.env \
  -f docker-compose.production.yml build backend frontend migrate
docker compose --env-file deploy/production.env \
  -f docker-compose.production.yml stop backend frontend
docker compose --env-file deploy/production.env \
  -f docker-compose.production.yml --profile ops run --rm migrate
docker compose --env-file deploy/production.env \
  -f docker-compose.production.yml up -d backend frontend caddy
```

The one-shot `migrate` service is deliberately behind the `ops` profile and is
not a backend startup dependency. Operators must run it explicitly before a
forward deployment; this prevents an older rollback image from being blocked
because its Alembic code cannot recognize a newer database revision.
Alembic migrations are forward-oriented and some downgrades are intentionally
disabled to avoid data loss. Application rollback therefore means:

1. preserve the current database backup;
2. verify that the previous application is compatible with the current
   expand/contract schema;
3. deploy the previous Git tag/image **without running `migrate`**;
4. if compatibility is not guaranteed, restore the backup into a separate
   database and point the previous release at that database.

Never run destructive schema rollback commands directly against the only
production database.

## Backups

`backup-postgres.sh` creates a custom-format `pg_dump` with mode `0600`, verifies
its catalog with `pg_restore --list`, writes a SHA-256 checksum, and removes
files older than `RETENTION_DAYS` (default 14):

```bash
./deploy/backup-postgres.sh
RETENTION_DAYS=30 BACKUP_DIR=/mnt/offsite ./deploy/backup-postgres.sh
```

Run it from host cron/systemd and copy backups to independent object storage.
Regularly test restoration into a disposable database; an untested backup is
not a recovery plan.

## Operational notes

- Caddy has fixed private address `172.30.0.10`; only its `/32` is trusted for
  forwarded client IPs used by authentication rate limiting.
- Proxy/Uvicorn access logs are disabled because the current WebSocket handshake
  carries a short-lived ticket in the query string. Application and error logs
  remain available; introduce structured redaction before enabling access logs.
- Uvicorn stays at one worker because the scheduler, quote cache, WebSocket
  connections, and in-process AI quotas are not shared between processes.
- `LLMQUANT_ENABLED=false` is the safe container default because the backend
  image does not include Node/npx. Add a pinned Node runtime before enabling it.
- For managed PostgreSQL, retain pgvector support and automated backups, set
  `DATABASE_URL` to the managed endpoint, and remove/disable the local
  `postgres` service only after adjusting service dependencies.
- Store `deploy/production.env` outside Git and restrict it to the deployment
  user. Prefer a cloud secret manager when the target provider supports one.
