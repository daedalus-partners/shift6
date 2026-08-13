# Shift6 staging operations

The staging deployment is deliberately isolated from production at every stateful boundary.

| Boundary | Production | Staging |
| --- | --- | --- |
| Checkout | `/var/www/shift6` | `/home/defibeats/shift6-staging` |
| Git branch | `master` | `codex/phase1-staging` |
| Compose project | `shift6` | `shift6-staging` |
| Frontend host port | `127.0.0.1:3005` | `127.0.0.1:3015` |
| Backend host port | `127.0.0.1:8001` | `127.0.0.1:8011` |
| MCP host port | not deployed | `127.0.0.1:8021` (loopback only) |
| Caddy listener | `:8085` | `:8112` |
| Postgres volume | `shift6_pgdata` | `shift6-staging_pgdata` |
| Upload volume | `shift6_uploads` | `shift6-staging_uploads` |
| Evidence volume | production-specific | `shift6-staging_evidence` |

Never mount, rename, copy, or declare the production volumes as external staging volumes. A production snapshot may be imported only through the explicit restore procedure after it has been reviewed for sensitive client data.

## One-time server setup

Clone the staging branch into its own checkout:

```bash
git clone --branch codex/phase1-staging --single-branch \
  git@github.com:daedalus-partners/shift6.git /home/defibeats/shift6-staging
cd /home/defibeats/shift6-staging
cp .env.example .env.staging
```

Start in server-local mode. This keeps the unauthenticated app bound to loopback and makes it
available only through an explicit SSH tunnel:

```dotenv
APP_ENV=staging
STAGING_EXPOSURE=local
AUTH_MODE=none
CF_ACCESS_TEAM_DOMAIN=
CF_ACCESS_AUDIENCE=
CORS_ALLOW_ORIGINS=http://127.0.0.1:3015

POSTGRES_USER=shift6_staging
POSTGRES_PASSWORD=generate-a-new-unique-password
POSTGRES_DB=shift6_staging
DATABASE_URL=postgresql+psycopg://shift6_staging:the-url-encoded-password@postgres:5432/shift6_staging

SMTP_URL=
UI_BASE_URL=http://127.0.0.1:3015
API_BASE_URL=http://127.0.0.1:3015
GOOGLE_SCRIPT_URL=
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SHEETS_ID=

STAGING_FRONTEND_PORT=3015
STAGING_BACKEND_PORT=8011
STAGING_CADDY_PORT=8112
STAGING_MCP_PORT=8021
EVIDENCE_DIR=/data/evidence
```

Open the local staging site without exposing it publicly:

```bash
ssh -L 3015:127.0.0.1:3015 Austin_Server
```

Then visit `http://127.0.0.1:3015`. Do not add the Caddy or tunnel route while
`STAGING_EXPOSURE=local` or `AUTH_MODE=none`.

Generate the database password with a password manager. URL-encode it in `DATABASE_URL`. Third-party read-only metric keys may be reused, but staging intentionally refuses to deploy when SMTP or Google write integrations are configured.

Run the deployment through the guard-railed script:

```bash
cd /home/defibeats/shift6-staging
bash deploy-staging.sh
```

The script refuses the production directory, wrong Git remote, wrong branch, dirty checkout,
production database name, unsafe URLs for the selected exposure mode, or outbound SMTP/Google
writes. It uses the following Compose shape and verifies all three isolated volumes after startup:

```bash
docker compose \
  --project-name shift6-staging \
  --env-file .env.staging \
  -f docker-compose.yml \
  -f docker-compose.staging.yml \
  up -d --build
```

Do not run the production `deploy.sh` in the staging checkout; it pulls `master` and relies on an implicit project name.

## Coverage CSV and MCP

The staging website exposes filtered CSV downloads through the Email Generator's
Coverage Records section. The same query layer is available through a read-only MCP server on
`127.0.0.1:8021/mcp`. It provides tools to list clients/publications, search or summarize records,
retrieve one record, and return a CSV. The MCP port is deliberately **not** routed through Caddy or
the Cloudflare public hostname; Streamable HTTP remains server-local until a dedicated MCP
authorization policy is configured.

For a local stdio client, run the server in the backend container or a configured Python environment:

```bash
python -m app.mcp_server
```

For the staging Streamable HTTP transport, connect only from the Austin host:

```text
http://127.0.0.1:8021/mcp
```

## Caddy and Cloudflare

Only after the Cloudflare Access application exists, change the staging environment to:

```dotenv
STAGING_EXPOSURE=cloudflare
AUTH_MODE=cloudflare_access
CF_ACCESS_TEAM_DOMAIN=https://your-team.cloudflareaccess.com
CF_ACCESS_AUDIENCE=replace-with-staging-application-audience
CORS_ALLOW_ORIGINS=https://shift6-staging.dwings.app
UI_BASE_URL=https://shift6-staging.dwings.app
API_BASE_URL=https://shift6-staging.dwings.app
```

Add this block to `/etc/caddy/Caddyfile` on the Austin server:

```caddyfile
# Shift6 staging; Cloudflare Access protects the public hostname.
:8112 {
    import force_https
    import baseline_headers
    reverse_proxy localhost:3015
}
```

Validate before reloading:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl --fail http://127.0.0.1:8112/health
```

The active tunnel is remotely managed. In the Cloudflare dashboard, create a public hostname for `shift6-staging.dwings.app` whose origin is `http://localhost:8112`, and create a Cloudflare Access self-hosted application for that hostname. Use its audience value in `CF_ACCESS_AUDIENCE`. Editing only `/etc/cloudflared/config.yml` is insufficient because the running tunnel receives remote configuration.

Keep staging local/Tailscale-only until the Access application and tunnel route are both active. Confirm an unauthenticated browser receives the Access login and an authenticated browser can reach the Email Generator.

## Backups

Backups contain a custom-format PostgreSQL dump, uploads archive, screenshot-evidence archive, non-secret manifest, and SHA-256 checksums. The script requires a new, absolute destination and refuses production and Docker data paths.

```bash
backup_dir="/home/defibeats/shift6-staging-backups/$(date -u +%Y-%m-%dT%H%M%SZ)"
STAGING_ENV_FILE=/home/defibeats/shift6-staging/.env.staging \
  bash /home/defibeats/shift6-staging/ops/backup-staging.sh \
  --destination "${backup_dir}"
```

Schedule that command from root cron after replacing the timestamp expression with the same dated path convention. Escape every `%` as `\%` when using `date` directly in a crontab. Keep at least 14 daily, 8 weekly, and 12 monthly recovery points. Pruning must target only `/mnt/cold/backups/shift6-staging`; never prune from this repository script.

After each scheduled backup, monitor its exit status and verify these five files exist:

- `database.dump`
- `uploads.tar.gz`
- `evidence.tar.gz`
- `manifest.env`
- `SHA256SUMS`

Austin's installed nightly wrapper writes to the separate cold-storage RAID:

```bash
bash /home/defibeats/shift6-staging/ops/backup-staging-nightly.sh
```

The corresponding user cron entry runs at 03:45 UTC under `flock` and writes its log to
`/home/defibeats/shift6-staging-backups/nightly.log`. The wrapper intentionally does not delete
old recovery points. Establish and approve a retention policy before adding pruning.

## Restore drill and recovery

Restores are intentionally cumbersome. They require the source backup, the exact project confirmation, and a separate destination for an automatic backup of the current staging state. The script verifies checksums and archive paths before stopping either app container.

```bash
source_backup=/mnt/cold/backups/shift6-staging/2026-08-13T030000Z
safety_backup="/mnt/cold/backups/shift6-staging/pre-restore-$(date -u +%Y-%m-%dT%H%M%SZ)"

STAGING_ENV_FILE=/home/defibeats/shift6-staging/.env.staging \
  bash /home/defibeats/shift6-staging/ops/restore-staging.sh \
  --backup-dir "${source_backup}" \
  --pre-restore-destination "${safety_backup}" \
  --confirm-project shift6-staging
```

The restore affects only `shift6-staging`, recreates only the `shift6_staging` database, clears only `/data/uploads` and `/data/evidence` inside staging volumes, runs Alembic through the normal backend entrypoint, and waits for the backend health check.

For a restore drill, create an identifiable staging-only row and evidence file, take a backup, make a second change, and restore the first backup during a maintenance window. Then compare row counts, evidence counts, sampled checksums, and the Email Generator history. A successful `pg_restore` alone is not proof that screenshots and client exports are recoverable.

## Promotion

Commit application, migration, test, Compose, and operations changes to `codex/phase1-staging` and push that branch. Never commit `.env.staging`, database dumps, CSV exports, screenshots, or archives. Open a pull request only after staging acceptance; merging to `master` and running the production deployment are separate actions.
