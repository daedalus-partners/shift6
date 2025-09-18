## Shift6 – Client Quote Generator

Planner Document • Last updated: (fill during edits)

### Background and Motivation
We are a PR agency that needs to generate high‑quality media quotes for many clients, fast and consistently. Each client has:
- Knowledge: internal docs used as grounding (RAG).
- Style: short style snippets like “be funny”, “be less technical”.
- Sample Quotes: prior quotes to mimic tone.

Users manage all three on one page (three side‑by‑side panels), then use a chat UI below to ask for a quote. The assistant retrieves relevant knowledge, injects style and samples, and produces a quote using OpenRouter (Claude Sonnet family) with optional web search via Exa AI. We’ll deploy via Docker Compose and expose via Cloudflare Tunnel + Cloudflare Access (email OTP).

### Key Challenges and Analysis
- Multi‑tenant data separation: ensure all data is scoped by `client_id`.
- RAG correctness vs context window: budget tokens across retrieved chunks, style, and samples; trim deterministically.
- File ingestion pipeline: robust parsing (PDF, DOCX, TXT) with minimal deps; incremental updates on add/delete.
- Vector store choice: prefer Postgres + pgvector for simplicity and ops (one DB) vs external vector DBs.
- Style and Sample integration: retrieve top‑N style snippets and semantically nearest sample quotes to the query.
- Web search via Exa AI: optional augmentation with freshness; avoid over‑stuffing.
- Streamed UI and memory: store last 30 messages per client conversation; stream model output to UI.
- Secure public access: Cloudflare Tunnel + Access (email OTP) instead of building custom auth.
- Observability: structured logs; minimal metrics to diagnose retrieval quality.

### Architecture Overview
- Frontend (React + TypeScript + Vite)
  - Pages: Client Workspace (dropdown to select client) with three panels (Knowledge, Style, Sample Quotes) and a Chat section below.
  - State: lightweight via Zustand; HTTP via axios; SSE for streaming.
  - Styling: minimalist black/white CSS modules; responsive.
  - Each of the three panels support both file/structured input and manual text entry:
    - Knowledge: drag/drop files + a text area to add a knowledge note; notes appear alongside files and can be edited/deleted.
    - Style: list with add/edit modal for short text snippets.
    - Sample Quotes: list with add/edit modal for quote text and optional source.
- Backend (Python + FastAPI)
  - CRUD for clients, knowledge (files & chunks), style, sample quotes, and chat messages.
  - RAG service: embeddings (fastembed), pgvector similarity, prompt builder with context budgeting, Exa AI web search.
  - LLM client: OpenRouter (Claude Sonnet family) with streaming.
  - CLI: Typer utilities to manage clients and system prompts in `backend/system_prompts/`.
  - Knowledge supports both file uploads and manual text notes (stored, chunked, embedded the same pipeline).
- Database (Postgres + pgvector)
  - Tables: clients, knowledge_files, knowledge_chunks, knowledge_embeddings (vector), styles, sample_quotes, chats, chat_messages.
- Deployment
  - Docker Compose: `frontend`, `backend`, `postgres` (pgvector image), `cloudflared`.
  - Cloudflare Access: email OTP to gate the tunnel URL (no app‑level auth initially).
  - Dev profile: run locally without Cloudflare and without login (no Access required); open CORS for localhost; backend auth disabled.

### Implementation Options (with recommendations)
- Vector store
  - Option A: Postgres + pgvector (recommended: single DB, simpler ops, good perf for medium scale).
  - Option B: Qdrant (great performance, extra service to run).
- Embeddings
  - Option A: Google Embedding Gemma (recommended: OSS, strong quality; see https://developers.googleblog.com/en/introducing-embeddinggemma/).
  - Option B: fastembed with `bge-small-en-v1.5` (fallback: very fast, CPU‑friendly, OSS).
  - Option C: sentence-transformers larger models (higher quality, slower).
- RAG orchestration
  - Option A: Custom small service (recommended: lean, transparent, easier to test).
  - Option B: LangChain/LlamaIndex (faster to prototype, more deps/complexity).
- File parsing
  - Option A: Lean: `pypdf`, `python-docx`, TXT (recommended start; add more as needed).
  - Option B: `unstructured` (broader formats, heavier stack).
- Frontend stack
  - Option A: Vite + React + Zustand + CSS Modules (recommended minimalism).
  - Option B: Next.js + Tailwind (more features, more footprint).
- Access control
  - Option A: Cloudflare Access email OTP (recommended: no auth code to maintain).
  - Option B: In‑app auth (more work, less leverage).

Recommendation summary: Postgres+pgvector, Google Embedding Gemma, custom RAG, Vite React minimal UI, Cloudflare Access.
 
Note on model versions: We’ll read `OPENROUTER_MODEL_ID` from `.env` and target the latest Sonnet model available on OpenRouter. If "Claude Sonnet 4" is available, use that ID; otherwise use the latest `anthropic/claude-3.x-sonnet` (e.g., `anthropic/claude-3.7-sonnet`). Verify via OpenRouter `/models` at runtime.

### System Components and Data Model
- clients(id, slug, name)
- knowledge_files(id, client_id, filename, mime, bytes_size, sha256, uploaded_at)
 - knowledge_files(id, client_id, source_type[file|note], filename, mime, bytes_size, sha256, uploaded_at, text)
- knowledge_chunks(id, file_id, client_id, chunk_index, text, token_count)
- knowledge_embeddings(id, chunk_id, client_id, embedding vector(d))
- styles(id, client_id, label, text, created_at)
- sample_quotes(id, client_id, source, text, created_at)
- chats(id, client_id, title, created_at)
- chat_messages(id, chat_id, client_id, role[system|user|assistant], content, created_at)

Indexes: vector ivfflat on embeddings; btree on foreign keys.

### Prompting and Context Budgeting
- Assemble prompt as:
  - System: per‑client system prompt from `backend/system_prompts/{client_slug}.md`.
  - Context: top‑K retrieved knowledge chunks (semantic similarity), with per‑source attribution headers.
  - Style: top‑N style snippets (recent first or curated weight).
  - Sample quotes: top‑M nearest to the user query (embed quotes for retrieval too).
  - Optional web search: Exa AI top results summarized.
  - Instruction: “Write a single press/media quote …” with output constraints.
- Budgeting: compute approximate tokens; cap each section (e.g., knowledge 60%, samples 25%, style 10%, web 5%); trim by sentence.

### External Integrations
- OpenRouter
  - Use Chat Completions endpoint with streaming; model id from env.
  - Add HTTP headers `HTTP-Referer` and `X-Title` per OpenRouter guidance.
- Exa AI
  - Use Python SDK (`exa-py`; module `exa_py`) to run targeted searches; summarize top results.

### Environment Variables (in project‑root .env)
Do not create another file; this `.env` already exists.
- BACKEND_PORT=8000
- FRONTEND_PORT=5173
- DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/quotes
- POSTGRES_USER=postgres
- POSTGRES_PASSWORD=postgres
- POSTGRES_DB=quotes
- OPENROUTER_API_KEY=…
- OPENROUTER_MODEL_ID=anthropic/claude-3.7-sonnet (verify via /models)
- EXA_API_KEY=…
- CLOUDFLARED_TUNNEL_TOKEN=…
- LOG_LEVEL=INFO
 - AUTH_MODE=none            # set to 'none' for dev, 'cloudflare' for prod
 - CORS_ALLOW_ORIGINS=http://localhost:5173

### Docker Compose (high‑level sketch)
```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    profiles: ["dev", "prod"]
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]

  backend:
    build: ./backend
    profiles: ["dev", "prod"]
    env_file: .env
    environment:
      AUTH_MODE: ${AUTH_MODE:-none}
      CORS_ALLOW_ORIGINS: ${CORS_ALLOW_ORIGINS:-http://localhost:5173}
    depends_on:
      - postgres
    ports: ["${BACKEND_PORT}:8000"]

  frontend:
    build: ./frontend
    profiles: ["dev", "prod"]
    env_file: .env
    depends_on:
      - backend
    ports: ["${FRONTEND_PORT}:5173"]

  cloudflared:
    image: cloudflare/cloudflared:latest
    profiles: ["prod"]
    command: tunnel run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARED_TUNNEL_TOKEN}
    depends_on:
      - frontend
      - backend

volumes:
  pgdata:
```

### High‑level Task Breakdown (Executor Steps)
1) Initialize repo and scaffolding
- Success: Monorepo with `frontend/`, `backend/`, `.env` references only.
- Steps:
  - Create Vite React TS app; install axios, react-router-dom, zustand.
  - Create FastAPI app; install dependencies (fastapi, uvicorn[standard], sqlalchemy, psycopg[binary], alembic, fastembed, numpy, httpx, typer, pydantic-settings, exa-py).
  - Add pre‑commit config for formatting (black, isort, ruff) and ESLint/Prettier.

2) Database schema + migrations
- Success: Alembic migrations create all tables and `vector` extension.
- Steps:
  - Use `pgvector` extension; `CREATE EXTENSION IF NOT EXISTS vector;` in migration.
  - Define SQLAlchemy models aligned to data model.
  - Create IVFFLAT index for embeddings (list size tuned during testing).

3) Embedding service
- Success: `POST /clients/{id}/knowledge/ingest` produces chunks + embeddings.
- Steps:
  - File store on disk (volume); compute sha256; avoid duplicate ingestion.
  - Parse PDF/TXT/DOCX minimally.
  - Chunk by tokens/characters; store chunks and token counts.
  - Embed with fastembed (`bge-small-en-v1.5`), store 384‑d vector.

4) Knowledge CRUD and live RAG updates
- Success: Adding/deleting a file updates chunks/embeddings; list reflects.
- Steps:
  - `POST /knowledge` upload; `DELETE /knowledge/{file_id}` cascade delete.
  - Background task for embedding to keep API snappy.

5) Style + Sample Quotes CRUD
- Success: Users can create/edit/delete style snippets and sample quotes per client.
- Steps:
  - Minimal text fields; track created_at.
  - Index quotes for retrieval (optionally embed quotes for nearest‑neighbors to query).

6) Retrieval + Prompt Builder
- Success: `POST /chat/:generate` returns streamed quote using context budgeting.
- Steps:
  - Retrieve K knowledge chunks by similarity to user message.
  - Retrieve N style snippets (recent or pinned) and M sample quotes (semantic nearest).
  - Optional: Exa search when query includes `@web` or freshness heuristics; summarize.
  - Build prompt parts; enforce budgets.

7) OpenRouter integration (streaming)
- Success: SSE/WS stream to frontend; messages stored; last 30 shown.
- Steps:
  - Use OpenRouter Chat Completions with `model` = env.
  - Stream tokens; persist assistant message on completion.

8) Frontend UI – Client page layout
- Success: Three panels side‑by‑side; chat below; responsive.
- Steps:
  - Client dropdown selector at top.
  - Panels:
    - Knowledge: drag/drop (react-dropzone), list, delete.
    - Style: list + add/edit modal.
    - Sample Quotes: list + add/edit modal.
  - Chat: message list (latest 30), input, send, streaming indicator.

9) System prompts per client (CLI‑friendly)
- Success: `backend/system_prompts/{client_slug}.md` exists and is editable.
- Steps:
  - Typer CLI commands: `prompt list|edit|show`.
  - API reads prompt file by slug at runtime.

10) Cloudflare Tunnel + Access
- Success: App reachable at tunnel URL; gated by email OTP.
- Steps:
  - Create tunnel; set `CLOUDFLARED_TUNNEL_TOKEN` in `.env`.
  - Configure Cloudflare Access policy (emails allowed).

11) Quality, tests, and docs
- Success: Unit tests for splitter, retriever, prompt builder; E2E for chat.
- Steps:
  - Pytests; React tests for core flows; basic load test for retrieval.
  - Add developer docs (README) and runbook.

### Detailed Executor Instructions (Do in order)
- Verify current model IDs via OpenRouter `/models`; set `OPENROUTER_MODEL_ID`.
- Backend
  1. Scaffold FastAPI app with routers: clients, knowledge, styles, samples, chat, health.
  2. Configure SQLAlchemy 2.0, alembic, and pgvector; create migrations.
  3. Implement file storage service and parsers (PDF/TXT/DOCX).
  4. Implement chunker and embedder (fastembed) with batching.
  5. Implement similarity search (cosine) with ivfflat index.
  6. Implement Exa search utility (exa-py) with simple summarizer (LLM or heuristic).
  7. Implement prompt builder with strict token budgeting.
  8. Implement chat generation endpoint with streaming from OpenRouter and message persistence.
- Frontend
  9. Create layout and theme; assemble panels and data grids.
  10. Implement drag/drop uploads and progress; CRUD forms for style and samples.
  11. Implement chat UI with SSE stream; show last 30 messages; virtualize if needed.
- DevOps
  12. Write Dockerfiles; compose file as above; healthchecks; volumes.
  13. Add cloudflared service and document Cloudflare Access setup.
  14. Add Compose profiles: `dev` (no cloudflared, AUTH_MODE=none) and `prod` (with cloudflared, AUTH_MODE=cloudflare).
  15. Add simple logging & request IDs; configure CORS.

Local run commands:
- Dev (no Cloudflare, no login): `docker compose --profile dev up --build`
- Prod (with Cloudflare Access): `docker compose --profile prod up --build`

### Project Status Board
- [x] Repo scaffolding complete
- [x] DB schema + migrations in place
- [ ] Embedding pipeline working
- [x] Knowledge CRUD + auto RAG updates (manual notes + file upload + chunking)
- [ ] Style + Sample CRUD
- [ ] Retrieval + prompt builder
- [ ] OpenRouter streaming wired
- [ ] Frontend panels + chat UI
- [ ] System prompts folder + CLI
- [x] Docker Compose up locally
- [ ] Cloudflare Tunnel + Access configured
- [ ] Tests + docs

### Current Status / Progress Tracking
Planner: Document drafted.
Executor: Dev profile compose created; backend/health OK at http://localhost:8000/health; frontend container running.
DB: Alembic set up; `vector` extension migration applied; initial schema migration applied; tables present in Postgres.

### Executor’s Feedback or Assistance Requests
- If a document type frequently fails parsing, note the sample and consider adding `unstructured` for that format only.
- If retrieval quality is poor, increase chunk overlap, tune chunk size, and test a larger embedding model.
- Confirm model availability on OpenRouter and pricing before enabling streaming in production.

### Lessons
- Keep token budgets strict to avoid truncation by the model.
- Debounce ingestion UI to prevent duplicate uploads; dedupe by sha256 on backend.
- Prefer Postgres + pgvector to reduce operational surface area; index tuning matters.

### Minimalist UI Notes
- Colors: pure black/white with subtle gray lines; high contrast; generous spacing.
- Typography: system font stack; 16–18px base; 600 weight for headings.
- Motion: minimal; only for file upload progress and typing indicator.

### System Prompt Template (example guidance)
Store in `backend/system_prompts/{client_slug}.md`. Example skeleton:
```
You are a media quote assistant for CLIENT_NAME.
Goals: craft concise, punchy, on‑brand quotes.
Voice: follow the client’s Style snippets and mimic Sample Quotes tone.
Rules: be factual per Knowledge; if unsure, ask for clarification; avoid hallucinations.
Output: a single paragraph under 70 words unless instructed otherwise.
```
