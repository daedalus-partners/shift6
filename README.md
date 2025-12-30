# Shift6 – Client Quote Generator

Python FastAPI backend + React TypeScript frontend to generate client media quotes with RAG.

## Quick start (dev)

Requirements: Docker + Docker Compose.

```bash
docker compose --profile dev up -d --build
# API: http://localhost:8000/docs
# FE:  http://localhost:5173
```

## Profiles
- dev: backend, frontend, postgres. No Cloudflare, no login.
- prod: adds cloudflared (Tunnel). Gate with Cloudflare Access.

```bash
# prod example (requires CLOUDFLARED_TUNNEL_TOKEN set in .env)
docker compose --profile prod up -d --build
```

## Environment
Place variables in project root `.env` (file exists in runtime):
- BACKEND_PORT=8000
- FRONTEND_PORT=5173
- DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/quotes
- POSTGRES_USER=postgres
- POSTGRES_PASSWORD=postgres
- POSTGRES_DB=quotes
- AUTH_MODE=none
- CORS_ALLOW_ORIGINS=http://localhost:5173
- OPENPAGERANK_API_KEY =...
- OPENROUTER_API_KEY=...
- OPENROUTER_MODEL_ID=anthropic/claude-3.7-sonnet
- EXA_API_KEY=...
- CLOUDFLARED_TUNNEL_TOKEN=...

## Project layout
- backend/ FastAPI app, Alembic, models
- frontend/ React + Vite app
- docker-compose.yml profiles for dev/prod
- .cursor/scratchpad.md planner/executor doc

## Smoke tests
```bash
curl http://localhost:8000/health
curl -s -X POST http://localhost:8000/clients/ -H 'Content-Type: application/json' -d '{"slug":"demo","name":"Demo Client"}'
curl -s http://localhost:8000/clients/
curl -s -X POST http://localhost:8000/knowledge/1/notes -H 'Content-Type: application/json' -d '{"text":"hello"}'
```

## Notes
- Dev auth is disabled via AUTH_MODE=none.
- System prompts live in backend/system_prompts (to be added with client slugs).
- Embeddings: will use Google Embedding Gemma.

