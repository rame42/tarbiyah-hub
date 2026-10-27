# Adding sources and research topics

## Built-in search sources

These are used automatically when research questions are investigated, in Arabic and English.
Enable or disable them on the **Sources** page.

| Source | Content | Files downloaded when |
|---|---|---|
| OpenAlex | papers, books, theses | an open licence (CC) is reported |
| Crossref | DOI metadata | an open licence and a PDF link are listed |
| DOAJ | open-access journal articles (many Arabic) | the journal licence is open (CC) |
| ERIC | education research | ERIC is authorized to distribute the full text |
| CORE (key) | repository full texts | an open licence is reported |
| Internet Archive | books, manuscripts | the item has a public-domain/CC licence (lending-library books: link only) |
| Open Library | book catalogue | a public scan exists |
| Project Gutenberg | public-domain books | always (public domain in the USA) |
| Google Books | catalogue incl. paid books | public-domain volumes only; paid books get price + buy link |
| YouTube (key) / Reddit (key) / X (paid key) / TikTok (Research API) | videos and posts | metadata and transcripts only |

## Monitored sources (revisited on a schedule)

Sources > **Add source**. Choose a type, give it a name, and fill in its settings (JSON). Examples:

**Arabic website**
```json
{
  "start_urls": ["https://example-institute.org/ar/articles"],
  "allowed_domains": ["example-institute.org"],
  "include_patterns": ["/ar/"],
  "content_patterns": ["/ar/articles/\\d+"],
  "language": "ar",
  "max_pages": 200,
  "max_depth": 3,
  "use_sitemap": true,
  "recrawl_hours": 168,
  "download_documents": false
}
```

**English website / institution / course catalogue:** same fields, for example `"resource_type": "institution_page"`
or `"course"`. Set `"render_js": true` only for sites that need JavaScript (this also requires
`pip install playwright` and `playwright install chromium`).

`download_documents: true` means *you confirm you have permission* to store that site's PDFs/EPUBs.
Leave it `false` otherwise. Documents are then catalogued with their link, unless the page shows an open licence.

**RSS feed / blog / podcast**
```json
{"feeds": ["https://example.org/feed.xml"], "fetch_full_text": true}
```
Podcast episodes with a published transcript (`<podcast:transcript>`) are collected with timestamps.

**YouTube channels** (no key needed)
```json
{"channel_ids": ["UCxxxxxxxxxxxxxxxxxxxxxx"], "playlist_ids": [], "transcripts": true}
```
Find a channel ID in the channel's page source (`"channelId"`) or its "About" > Share > Copy channel ID.

**Telegram public channels**
```json
{"channels": ["channel_username"], "max_pages": 5}
```

**Reddit** `{"subreddits": ["islam", "Parenting"], "queries": ["tarbiyah", "islamic parenting"]}`
**Facebook pages** `{"page_ids": ["123456789"]}`
**Instagram** `{"usernames": ["business_account"]}`
**X** `{"queries": ["تربية الأبناء"], "usernames": []}`
**TikTok** `{"video_urls": ["https://www.tiktok.com/@user/video/123"]}`
**Local folder** `{"path": "inbox", "resource_type": "book"}`

Each source has its own schedule (`schedule_minutes`), enable switch, pause switch, health status,
last/next run, and error message. **Run now** starts it immediately. One failing source never stops the others.

## Research topics

- **Objectives** (Research Center): broad goals per pillar. The planner breaks each one into questions.
  Use *Replan* after editing an objective.
- **Questions** (Questions page): add your own question. It is investigated immediately and
  takes part in the automatic cycle afterwards. Mark questions answered, unresolved, duplicate or not relevant.
- **Glossary** (Glossary page): Arabic ↔ English terms and spelling variants. They make an Arabic
  search also find English sources, and the reverse. Add terms whenever you notice a missed match.
- **Taxonomy topics** are seeded from `tarbiyah/taxonomy.py`. Edit that file to add topics and keywords,
  then restart (new topics are added; existing ones are kept).

## Writing a new adapter (for developers)

1. Create a class in `tarbiyah/sources/` that subclasses `SourceAdapter` and defines `info = AdapterInfo(...)`
   (name, label, kind, capabilities `("search",)` and/or `("monitor",)`, required credentials, access notes,
   default config).
2. Implement `search(query, lang, limit)` and/or `collect(ctx)`. Return or yield `ResourceIn` objects, and use
   `http()` for all requests (it handles robots.txt, rate limits, retries and the daily budget).
3. Set `access=decide(...)` from `tarbiyah/ingest/licensing.py`. Set `download_url` only when downloading is
   permitted. Put collected text in `text=` or timestamped `segments=`.
4. Register the adapter in `ADAPTERS` in `tarbiyah/sources/registry.py`.
5. Add a test in `tests/test_collectors.py` with a sample response.
