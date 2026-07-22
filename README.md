# Shift6 – Client Quote Generator

FastAPI, PostgreSQL/pgvector, and React/Vite application for client media quotes, coverage tracking, task capture, and verified coverage-email generation.

## Development

```bash
cp .env.example .env
docker compose up -d --build
```

The default override publishes the API at `http://localhost:8000` and frontend at `http://localhost:5173`. Development may use `APP_ENV=development` and `AUTH_MODE=none`.

## Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Production binds the API and frontend to localhost for the reverse proxy and does not publish PostgreSQL. It sets `APP_ENV=production` and defaults to `AUTH_MODE=cloudflare_access`.

Required Cloudflare Access settings:

```dotenv
AUTH_MODE=cloudflare_access
CF_ACCESS_TEAM_DOMAIN=https://your-team.cloudflareaccess.com
CF_ACCESS_AUDIENCE=your-application-aud-tag
CORS_ALLOW_ORIGINS=https://shift6.dwings.app
```

For API-only deployments, use `AUTH_MODE=api_key` and a long random `SHIFT6_API_KEY`. This installation intentionally permits `AUTH_MODE=none` in production; that mode is public and should be changed before exposing sensitive client data.

See [.env.example](.env.example) for database, provider, size-limit, and auth variables. The backend entrypoint applies Alembic migrations before startup.

## Verification

```bash
.venv/bin/pytest tests/test_email_integrity.py tests/test_security_controls.py tests/test_coverage_integrity.py -q
cd frontend && npm run build
```

The legacy API/coverage integration tests expect a dedicated PostgreSQL database and running API. Never run them against production.

Detailed audit remediation and deployment checks are in [docs/email-audit-remediation.md](docs/email-audit-remediation.md).
