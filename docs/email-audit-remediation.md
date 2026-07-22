# Shift6 Email Audit Remediation

## Product contract

Given a client name and one earned-media URL, Shift6 creates a client-ready coverage email tied to that exact page. It fails clearly when the source or provider cannot be verified. Publication metrics remain source-attributed in the structured API data, while the client-facing email shows only the concise metric label and value.

Every generated email has a deterministic subject:

`Coverage Live: <Publication>`

## Remediated failures

- Submitted URLs, every redirect, `robots.txt`, and publisher about pages pass the same public-network validation. Response bytes, redirects, cache size, and cache age are bounded.
- Direct article fetch is preferred. Exa content is accepted only when its normalized result URL is the submitted article URL.
- Submitted, final, and canonical URLs are compared. The source body hash, fetch time, method, and URL identities are persisted.
- Anchor text and destinations are retained as structured source data. Client links are no longer inferred from flattened body text.
- Client mentions use normalized boundaries. Quotes require client attribution; unrelated quoted text is not selected.
- Remote publisher text is sent to Claude Opus 4 as untrusted JSON evidence. The model supplies only three subjective analysis fields, which are rejected if they add unsupported audience, positioning, or metric claims. Headline, URL, links, quote, metrics, and labels are rendered deterministically from verified data.
- Model-provider failure uses a conservative evidence-only analysis so an otherwise verified report remains usable. Source-fetch failure still returns an error; there is no successful-looking placeholder article.
- Moz v2 URL Metrics supplies the actual `Moz Domain Authority`; results are cached for 30 days per publication to conserve API rows. Open PageRank remains a clearly labeled directional fallback.
- Semrush's website traffic overview supplies the primary `Estimated monthly visits` value. A conservative authority-based estimate is used only when provider traffic is unavailable, so the email always contains a clearly estimated number. Full provenance remains available in the structured API data.
- The client-facing report always retains Outlet Snapshot, Coverage Details, Message Pull-Through, Quote Highlight, Strategic Value, and Performance / Reach. Missing evidence is stated inside the relevant section instead of removing the section.
- Article identity is unique per client and URL. History, search, and summary reads require the client name and summaries are ordered from the summary record.
- Coverage search results are re-fetched before persistence. Exact quote and client-name boundaries are verified against the fetched body.
- Coverage hits are committed before an atomic email-delivery claim. SMTP requires verified TLS, and only source-verified hits can be sent.

## Application controls

- `AUTH_MODE=none` is an explicit public-production mode for this installation; request-size, quota, concurrency, and idempotency controls still apply.
- `AUTH_MODE=cloudflare_access` validates the Access JWT issuer, audience, signature, expiry, and required claims. `AUTH_MODE=api_key` is available for non-browser API clients.
- Paid routes have identity/IP quotas and concurrency limits. Valid idempotency keys receive duplicate-request protection when supplied, while cached browser bundles remain compatible when the header is absent.
- Request, upload, model-input, paste-import, and outbound-response sizes are bounded.
- Client prompt slugs use a strict allowlist and resolved-path containment.
- Production ports bind only to localhost; PostgreSQL has no published host port.
- FastAPI, Starlette, python-multipart, and PyJWT are on the verified current compatible stack recorded in `backend/requirements.txt`.

## Deployment

1. Copy `.env.example` to the server's protected `.env`. This installation currently uses public `AUTH_MODE=none`; configure Cloudflare Access or API-key authentication before storing sensitive client data.
2. Configure `CORS_ALLOW_ORIGINS=https://shift6.dwings.app`, either `MOZ_API_TOKEN` or the `MOZ_ACCESS_ID`/`MOZ_SECRET_KEY` pair, and the remaining provider/SMTP variables.
3. Deploy backend and frontend together. The backend entrypoint runs the Alembic chain through `c3e5f7a9b1d2` before starting.
4. Confirm `/health`, `/docs`, one known-good email fixture, one wrong-URL rejection, and one source-verified coverage hit.
5. Monitor authentication failures, source-verification failures, provider errors, rate limits, and `email_delivery_status=failed`.

## Verification commands

```bash
.venv/bin/pytest tests/test_email_integrity.py tests/test_security_controls.py tests/test_coverage_integrity.py -q
cd frontend && npm run build
cd backend && DATABASE_URL='postgresql+psycopg://user:pass@localhost/db' ../.venv/bin/alembic -c alembic.ini upgrade head --sql
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

The older integration suites require the dedicated PostgreSQL test database and a running API. Do not point them at production.
