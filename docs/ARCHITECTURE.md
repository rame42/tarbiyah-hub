# Architecture

```
            ┌──────────────────────────── web process ────────────────────────────┐
 Browser ──►│ FastAPI (tarbiyah/api)  ─ serves React dashboard (frontend/dist)    │
            └──────────────┬──────────────────────────────────────────────────────┘
                           │ reads/writes            (SQLite WAL: 1 writer, many readers)
                     data/tarbiyah.db  ◄──────────── files: data/files, data/text, data/outputs
                           │
            ┌──────────────┴─────────── worker process ───────────────────────────┐
            │ APScheduler triggers ──► durable job queue (jobs table)             │
            │   every 60s  due monitored sources  -> collect_source              │
            │   every 2min research cycle (bounded) -> research_cycle             │
            │   every 10min daily report / finalize yesterday + next-day plan    │
            │   every 20min maintenance sweep (orphaned work, citations, QA)      │
            │ Worker threads claim jobs (lease + heartbeat + checkpoint)          │
            │   handlers: collect_source search_source acquire process analyze    │
            │   plan_objective investigate_question synthesize_question qa        │
            │   fetch_citations embed generate_output daily_report maintenance    │
            └─────────────────────────────────────────────────────────────────────┘
```

## Components (agents) and their responsibilities

| Component | Module | Input → Output |
|---|---|---|
| Research Planner | `agents/planner.py` | objective → bilingual questions + glossary terms (AI, or taxonomy templates) |
| Discovery Agent | `agents/discovery.py` | question → bilingual queries → `search_source` jobs per enabled source; skips searches repeated within N days |
| Acquisition Agent | `ingest/pipeline.acquire` | resource with legal download basis → verified file (type check, checksum, dedupe, limits) |
| Social & Media Collectors | `sources/*.py` | configured source → `ResourceIn` items (independent adapters) |
| Document Processing | `ingest/extract.py`, `pipeline.process` | file/page/post → passages with page/time, language, quality score, OCR |
| Knowledge Extraction | `agents/knowledge.py` | passages → claims (verified quotes), entities, relations, citations, AI summary |
| Research & Synthesis | `agents/synthesis.py` | question + retrieved passages → findings with verified evidence, gaps, disagreements |
| Question Generation | `agents/questions.py` | coverage gaps, citations, entities, AI reading → deduplicated, ranked, limited questions |
| Quality Assurance | `agents/qa.py` | quote re-verification, AI support review, OCR reprocessing, duplicate flags, link checks |
| Workflow Coordinator | `agents/coordinator.py`, `jobs/*` | bounded cycles, scheduling, retries, budgets, audit log (`agent_runs`) |
| Reports & Outputs | `agents/reports.py`, `agents/outputs.py` | daily reports + next-day plan; bibliographies, evidence tables, reviews |
| Assistant | `agents/assistant.py` | user question → cited answer from the collection |

## Key guarantees and how they are implemented

- **Persistence and resume:** all work is rows in `jobs`. A job is claimed atomically (`UPDATE … RETURNING`)
  with a lease. Crashed jobs are re-queued on restart (same host) or when their lease expires. Crawls save
  checkpoints, and the crawl frontier is stored in `crawl_urls`.
- **No duplicate work:** `dedupe_key` on active jobs; `search_log` prevents repeated searches; unique indexes on
  canonical URL and DOI, plus checksum, ISBN, source id and fuzzy title/author matching, prevent duplicate resources,
  even under concurrent collectors.
- **Bounded autonomy:** limits on questions per cycle, open questions, new questions per run and question depth;
  daily budgets for web requests, downloads, AI calls and AI spend; storage and free-disk limits; operating hours.
- **Legal collection:** robots.txt, per-host rate limits, no login/CAPTCHA/paywall bypass, and downloads only
  with a positive licence basis (`ingest/licensing.py`). Provenance is stored on each resource.
- **Prompt-injection resistance:** AI receives collected content as delimited untrusted data, returns only
  schema-validated JSON, and has no tools. All actions are taken by code under these policies.
- **Evidence integrity:** original text is never modified (normalized copies exist only in the search index).
  Translations and summaries are stored separately and labelled. Quotes are verified verbatim, and unverified
  AI statements are downgraded.

## Data model (main tables)

`resources` (metadata, provenance, licence/access, file, statuses, quality), `chunks` (original passages with page/
timestamp), `resource_pillars`, `topics`/`resource_topics`, `glossary`, `entities` (people, organizations,
programs, concepts, channels) + `resource_entities`, `relations` (graph edges), `claims`, `citations`, `objectives`,
`questions`, `findings`, `search_log`, `sources`, `crawl_urls`, `jobs`, `agent_runs` (audit), `usage_counters`,
`daily_reports`, `settings`, `outputs`, `embeddings`. Full-text indexes: `resource_fts`, `chunk_fts` (SQLite FTS5).

## Moving to PostgreSQL / a server

The schema is managed by Alembic (`migrations/`) through SQLAlchemy. To use PostgreSQL, set
`TH_DATABASE_URL=postgresql+psycopg://…` and install `psycopg`. The FTS5 search module is SQLite-specific: a
PostgreSQL deployment needs a `tsvector` implementation of `search/fts.py` (same functions). This is the
main porting task. Semantic search can then move to pgvector. The worker and web processes can run on separate
machines that share the database.
