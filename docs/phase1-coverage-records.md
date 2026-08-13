# Phase 1: durable coverage records

Phase 1 extends the existing Email Generator into a durable, exportable placement record. It does
not replace the Coverage Tracker, write to Google Sheets, infer LLM impact, or backfill historical
placements. Those remain separate later phases.

## Score policy

The available August 11 source defines one draft weighted formula:

- Impact: 35%
- Quality: 30%
- Outlet strength: 20%
- Outlet audience: 15%

The same source says Lexi review and click-band calibration are still pending. Therefore
`shift6-draft-2026-08-11` is stored as a versioned draft with a SHA-256 formula hash. Missing
components are never reweighted. A total remains `NULL` until all four components have approved,
defensible 0–100 inputs. Today only a real, high-confidence, non-estimated Moz Domain Authority can
score Outlet strength. Open PageRank estimates, internal traffic fallbacks, and unapproved audience
normalization are not score inputs.

Every calculation is append-only and retains its component states, exact input snapshot,
methodology version, formula hash, calculation time, source revision, and provider provenance.

## Record model

Each generated coverage email now creates or links:

1. A canonical publication keyed by normalized domain.
2. An immutable source revision containing requested/final/canonical URLs, extracted text, author,
   source hash, fetch method and time, links, and publication-date evidence.
3. Immutable publication metric snapshots with provider, method, confidence, observed time, and the
   raw provider response used by the report.
4. A versioned Shift6 score snapshot.
5. A full-page screenshot, thumbnail, hash-addressed files, and a JSON evidence manifest.
6. The generated summary linked to the exact source revision.

The mutable legacy Article fields remain as a current projection for compatibility. Historical
reproducibility comes from the append-only revision and snapshot tables.

## Publication dates

Publication timestamps are selected in this order while retaining every candidate:

1. Article or NewsArticle JSON-LD `datePublished`.
2. `article:published_time` metadata.
3. Publication-marked `<time>` elements inside the article body.
4. Exact-URL Exa `publishedDate` fallback.

Values with explicit timezones are normalized to UTC at high confidence. Date-only or timezone-less
values are retained with reduced confidence. Modified/updated timestamps are excluded rather than
silently substituted for publication time.

## Screenshot evidence

Screenshot capture is best-effort and nonfatal. The report transaction commits first, then pending
evidence rows are committed and capture runs in the API process. Chromium revalidates public URLs,
blocks private-network subrequests, bounds time, byte size, and page height, and requires the final
article URL to match the submitted source. A publisher block or timeout produces a durable failed
state without discarding the report.

Files live under `EVIDENCE_DIR` using hash-addressed paths. Database rows store the SHA-256 digest,
byte size, MIME type, source/final URL, viewport, capture time, and error state. The evidence volume
and manifests are included in staging backups.

## Query and export contract

The authenticated API and Email Generator UI support the same filters:

- exact client name
- normalized publication domain
- inclusive start/end date
- date basis: publication, screenshot capture, or report generation

CSV exports flatten publication-date, metric, score, and screenshot provenance and neutralize cells
that spreadsheet programs might treat as formulas. A read-only MCP server exposes list, search,
detail, summary, and CSV tools over the same query layer. Its staging HTTP transport is bound only to
loopback until a dedicated MCP authentication policy is added.

## Acceptance gates

Phase 1 is ready for staging acceptance only when all of the following pass:

- backend and production frontend container builds
- focused Email, date, score, evidence, export, and MCP tests
- migration from an empty legacy database to the new Alembic head
- a real Email Generator run produces revision, metric, score, and evidence records
- filtered UI and API CSVs agree on record count and contents
- screenshot files and hashes survive a backup and restore drill
- staging remains on separate ports, volumes, database, checkout, and Git branch
- staging is either protected by Cloudflare Access or kept server-local

Production promotion is a later explicit decision. Merging this branch and running the production
deploy script are intentionally outside the Phase 1 staging workflow.
