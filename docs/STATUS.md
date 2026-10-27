# Status record: what works, what was tested, what remains

Last updated: 2026-10-27 (first working milestone).

## Test results

`python -m pytest`: **37 passed**. These tests run real code against real files and a real HTTP server on
localhost. The development environment could not reach the public internet sources (see "Not yet verified live").

| Area | What the tests verify |
|---|---|
| Arabic/English text | normalization (diacritics, tatweel, alif/ya/ta-marbuta), language detection, title keys, verbatim quote checks |
| Extraction | Arabic and English PDFs (with page numbers, presentation-form repair), DOCX, EPUB, HTML (boilerplate removal, licence detection), scanned PDF → `needs_ocr` |
| Library | import keeps metadata/provenance/checksum; duplicates by checksum, DOI, URL, Arabic title variants; conservative licensing rules |
| Bilingual search | Arabic query → Arabic and English results and vice versa; snippets from original text; filters; question-style passage retrieval |
| Queue and worker | dedupe, priorities, leases, paused groups, retries with backoff, permanent failure + manual retry, deferral without consuming attempts, budget exhaustion → wait until tomorrow |
| Restart recovery | worker started as an **independent OS process**, killed with SIGKILL mid-crawl, restarted: it reports "recovered 1 interrupted job", finishes, no duplicates; graceful SIGTERM stop |
| Web scraping | Arabic site and English site: sitemaps, pagination, robots.txt (`/private/` never fetched), CC licence detection, PDF stored only with permission, document titles from file content |
| Incremental crawling | second run creates nothing new; a changed page is detected (hash), re-indexed, not duplicated |
| Feeds/social | RSS podcast with `<podcast:transcript>` (timestamps), Telegram public-channel preview, local inbox folder |
| API adapters | parsing + licence decisions for OpenAlex, Crossref, DOAJ, ERIC, Internet Archive (lending vs public domain), Open Library, Gutenberg, Google Books (paid: price + buy link), Reddit, X; credentials enforced |
| Research loop (no AI) | objective planning, bilingual questions, bounded investigation, bilingual searches, search de-repetition, synthesis waits for AI instead of inventing answers |
| AI plumbing (scripted test double, *not* Claude) | fabricated quotes are discarded, unverified findings downgraded, follow-up questions depth-limited, assistant marks unverified citations, AI-needed outputs refuse to run without a key |
| Reports/outputs/API | daily report + next-day plan, bibliography, evidence table CSV, all endpoints, secrets never returned, backup → restore round trip |

The dashboard was checked separately with Playwright: 15 pages in English and Arabic, desktop and phone widths, with
no console errors or failed requests. Library search, resource detail, assistant, adding questions, source toggles and
settings were exercised.

## Not yet verified live (needs internet access or keys)

These are fully implemented, but they could not be run against the real services from the development environment:

- **Live API calls** to OpenAlex, Crossref, DOAJ, ERIC, CORE, Internet Archive, Open Library, Gutendex, Google Books,
  YouTube (feeds/captions/API), Reddit, Facebook, Instagram, X, TikTok, Voyage. Parsing follows each API's
  documented response format. Run the system with internet access and check each source's health on the Sources page.
- **Claude calls** (`ANTHROPIC_API_KEY` was not available). The request code follows the current Anthropic Python SDK
  (structured outputs, streaming for long text, refusal fallbacks), but no real Claude response has been processed yet.
- **Real Arabic/English websites** (tested on a local bilingual site with the same structures).
- **Windows**: scripts are written for Windows (`.bat`, PowerShell auto-start, `msvcrt` file locks), but the tests ran on Linux.
- **Tesseract OCR** (not installed in the test environment; the code path is implemented).

## Known limitations

- Arabic search uses normalization and light stemming, not full morphological analysis, so some word forms
  (e.g. verb vs noun of the same root) only match through glossary entries, Claude query expansion or Voyage embeddings.
- Rule-based pillar classification is keyword-based. Claude analysis adds a second, AI-labelled classification.
- Social platforms: Facebook/Instagram require Meta app approval, X requires a paid API, TikTok transcripts require
  Research API approval. Without these, those collectors stay disabled (by design; no scraping workarounds).
- Audio without a published transcript is catalogued but not transcribed (no local speech model, by your requirement).
- Daily report summaries are generated in English text. The dashboard labels are bilingual.
- PostgreSQL needs a `tsvector` version of the search module (see ARCHITECTURE.md).
- Spend estimates use a static price table. Verify against your Anthropic usage page.

## Suggested next steps

1. Run with internet access and an `ANTHROPIC_API_KEY`. Check each source's health, then tune `daily_ai_budget_usd`.
2. Register 5–10 trusted Arabic and English sites, feeds and YouTube channels (SOURCES.md).
3. Review the first week of findings and questions. Extend the glossary with missed terms.
4. Add dedicated adapters for important Islamic libraries whose terms permit it (e.g. sites with open licences).
5. Optional: Arabic morphological analyzer (e.g. CAMeL Tools) for better recall; sqlite-vec/pgvector for large embedding sets.
6. Optional: a speech-to-text API for podcasts without transcripts.
