# Configuration

There are two kinds of configuration:

- **Keys and paths** go in the `.env` file (open it with Notepad). Restart Tarbiyah Hub after editing.
  Keys are never shown in the dashboard and never sent to any service except the one they belong to.
- **Operating settings** (limits, hours, AI options) are edited in **Dashboard > Settings** and take effect immediately.

## Claude (AI reasoning)

1. Create an API key at https://console.anthropic.com (Settings > API keys). API usage is billed by
   Anthropic per token. It is separate from a claude.ai subscription.
2. In `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
3. Restart. Settings > *AI* shows "configured".

The model is `claude-opus-5-5` by default (change with `TH_AI_MODEL=` in `.env`). Calls use
server-side refusal fallbacks (`fallbacks: "default"`), so a request declined by the model's safety
classifiers is retried on an appropriate fallback model instead of failing.

**Cost control:**

| Setting | Default | Meaning |
|---|---|---|
| `ai_enabled` | true | Master switch (still requires the key) |
| `daily_ai_call_limit` | 200 | Maximum AI requests per day |
| `daily_ai_budget_usd` | 2.00 | Stops AI work for the day when the estimated spend reaches this amount |
| `ai_effort` | low | Reasoning effort per call: low is cheapest, high is most thorough |
| `ai_summary_language` | source | Language of summaries: the source's language, or always `en` / `ar` |

Spend is estimated from token counts using the prices in `tarbiyah/ai/claude.py`; check current prices
at https://www.anthropic.com/pricing. When a limit is reached, AI jobs wait until the next day.
Collection, extraction and keyword search continue.

**What runs on Claude:**

| Component | AI role |
|---|---|
| Knowledge extraction | Claims, quotes, concepts, scholars, institutions, programs, cited works, relations, summary |
| Planner | Breaks objectives into bilingual questions and search terms |
| Question generation | Follow-up questions from new material and gaps |
| Synthesis | Answers questions from collected passages, with findings and evidence |
| QA | Checks whether each finding is supported by its quoted evidence |
| Assistant | Answers questions with citations; expands searches with Arabic/English synonyms |
| Outputs | Literature reviews, briefs, curriculum outlines and training-manual outlines |
| OCR (optional) | Transcribes scanned pages when Tesseract is not installed |

**Safeguards (built in):** Claude never takes actions. It receives collected text as data and returns
structured answers, and the program decides what to do. Every quote Claude reports is checked
word-for-word against the stored source passage. Unverified quotes are discarded, and findings
without verified evidence are downgraded to "insufficient". AI text is always labelled with the
model that produced it.

## Using another AI service instead of Claude

Any service with an OpenAI-style "chat completions" API works. Put these lines in `.env` and restart:

```
TH_AI_PROVIDER=openai_compatible
TH_AI_BASE_URL=<address from the table>
TH_AI_API_KEY=<your key from that service>
TH_AI_MODEL=<exact model name, copied from the service's model list>
TH_AI_PRICE_INPUT=<USD per million input tokens>     (for the daily budget)
TH_AI_PRICE_OUTPUT=<USD per million output tokens>
```

| Service | TH_AI_BASE_URL | Key from |
|---|---|---|
| OpenAI (ChatGPT models) | `https://api.openai.com/v1` | platform.openai.com > API keys |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | aistudio.google.com > Get API key |
| DeepSeek | `https://api.deepseek.com` | platform.deepseek.com |
| Mistral | `https://api.mistral.ai/v1` | console.mistral.ai |
| Groq | `https://api.groq.com/openai/v1` | console.groq.com |
| OpenRouter (many models, one key) | `https://openrouter.ai/api/v1` | openrouter.ai/keys |

Everything AI-related then uses that service: knowledge extraction, questions, synthesis, QA, assistant and
outputs, with the same daily limits and the same word-for-word quote checking. Differences: scanned-page OCR
stays Claude-only (use Tesseract), and quality depends on the model; smaller models make more mistakes in
Arabic and in following the required answer format (failed AI jobs are shown on the Jobs page). Set the two
price lines so the daily budget is accurate; without them spend is estimated at a conservative rate.
To return to Claude, set `TH_AI_PROVIDER=claude` (or remove the line).

## Semantic search (optional): Voyage AI

`VOYAGE_API_KEY=` (from https://www.voyageai.com, which has a free tier). This enables multilingual embeddings. They are
combined with keyword search, so meaning-based matches are found even when the words differ. Without
the key, search uses bilingual keyword matching, glossary expansion and, when Claude is configured,
Claude-generated synonyms.

## OCR

Scanned PDFs with no text layer are marked `needs_ocr`. Two options:

1. **Tesseract (free, local).** Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
   and select the **Arabic** language data during setup. If it is not on PATH, set
   `TH_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`. Linux: `sudo apt install tesseract-ocr tesseract-ocr-ara`.
2. **Claude:** with a Claude key and `ocr_provider` = `auto` or `claude`, scanned pages are sent to Claude
   for transcription. This costs API usage.

`ocr_provider`: `auto` (Tesseract if installed, otherwise Claude), `tesseract`, `claude`, or `none`.
Documents waiting for OCR are reprocessed automatically when OCR becomes available. OCR output gets a
quality score; low scores are flagged in the library.

## Optional collector credentials

| Platform | `.env` keys | How to get them | Notes |
|---|---|---|---|
| YouTube search | `YOUTUBE_API_KEY` | Google Cloud console > enable "YouTube Data API v3" > API key (free quota) | Channel monitoring and captions work without a key |
| CORE | `CORE_API_KEY` | https://core.ac.uk/services/api (free) | Open-access repository full texts |
| Reddit | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | https://www.reddit.com/prefs/apps, "script" app | Non-commercial use; posts only |
| Facebook | `FACEBOOK_ACCESS_TOKEN` | Meta for Developers: a Page token for pages you manage, or an app approved for Page Public Content Access | Scraping facebook.com is not implemented (not permitted) |
| Instagram | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Instagram professional account linked to a Meta app | Reads business/creator accounts via business discovery |
| X (Twitter) | `X_BEARER_TOKEN` | developer.x.com | **Paid** API tiers are required for reading |
| TikTok | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | TikTok Research API (approved researchers only) | Without it, only oEmbed metadata for video URLs you list |
| Telegram | none | | Public channels via their public web preview |
| Apify (any platform) | `APIFY_TOKEN` | https://console.apify.com > Settings > API & Integrations | **Paid per run**; see [APIFY.md](APIFY.md) |

Platforms without credentials show `needs_credentials` on the Sources page and are skipped. Nothing else is affected.

## Operating settings (Dashboard > Settings)

| Setting | Default | Meaning |
|---|---|---|
| `automation_enabled` | true | Scheduled collection and research on/off |
| `paused` | false | Temporarily hold all work (worker stays running) |
| `operating_hours` | 00:00–23:59 | Daily window for collection and research (local time) |
| `worker_concurrency` | 3 | Jobs running at the same time |
| `research_cycle_minutes` | 30 | Time between research cycles |
| `max_questions_per_cycle` | 2 | Questions investigated per cycle |
| `max_open_questions` | 300 | Upper bound on the open question queue |
| `max_new_questions_per_run` | 8 | New questions admitted per generation step |
| `max_question_depth` | 3 | How many generations of follow-up questions are allowed |
| `search_repeat_days` | 14 | An identical search is not repeated within this period |
| `daily_http_request_limit` | 3000 | Web requests per day |
| `daily_download_limit` / `daily_download_mb_limit` | 150 / 2000 | Downloads per day |
| `storage_limit_gb` / `min_free_disk_gb` | 20 / 2 | Storage caps |
| `max_file_mb` | 150 | Largest file downloaded |
| `download_free_to_read` | false | Also download open-access files that carry no explicit licence |
| `respect_robots_txt` | true | Obey website crawling rules (keep on) |
| `crawler_default_max_pages` / `_max_depth` | 200 / 3 | Defaults for website crawls |

Other `.env` options: `TH_DATA_DIR` (data folder), `TH_DATABASE_URL` (e.g. PostgreSQL, see ARCHITECTURE.md),
`TH_CONTACT_EMAIL` (sent to OpenAlex/Crossref as polite contact), `TH_USER_AGENT`.
