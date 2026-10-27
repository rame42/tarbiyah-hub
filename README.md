# Tarbiyah Hub

An autonomous research and knowledge-collection system for **Tarbiyah**, covering
children's tarbiyah, parents & family, and murabbi (educator) development, in **Arabic and English**.

It runs as two processes on your own computer (or later on a server):

| Process | Command | What it does |
|---|---|---|
| **Worker** | `python -m tarbiyah worker` | Runs the scheduled research loop: discovers sources, scrapes permitted pages, downloads legally available files, extracts and indexes text, and generates and investigates research questions. Keeps going without you or Claude Code. |
| **Dashboard** | `python -m tarbiyah web` | The website at http://127.0.0.1:8000: daily dashboard, library, research center, questions, AI assistant, sources, jobs, outputs, settings. |

All progress is stored in a database (`data/tarbiyah.db`) and in files under `data/`. Stopping or
restarting the computer loses nothing: interrupted jobs resume where they left off.

## Quick start (Windows)

1. Install **Python 3.11+** from python.org and tick "Add python.exe to PATH".
2. Double-click **`install.bat`** (once).
3. Double-click **`start.bat`**. The dashboard opens in your browser.
4. To stop safely, double-click **`stop.bat`**.
5. Optional: to start automatically at login, right-click `scripts\install-autostart-windows.ps1` and choose **Run with PowerShell**.

Linux/macOS: `./install.sh`, `./start.sh`, `./stop.sh` (systemd units are in `scripts/`).
Full guide: [docs/INSTALL.md](docs/INSTALL.md).

## What works without any paid service

- Collecting from websites (Arabic and English), RSS feeds, podcasts, YouTube channels (feeds and captions),
  public Telegram channels, a local "inbox" folder, and free academic and book indexes (OpenAlex, Crossref,
  DOAJ, ERIC, Internet Archive, Open Library, Project Gutenberg, Google Books).
- Legal acquisition: a file is downloaded only when there is a positive legal basis (public domain, an open
  licence, your own file, or a site you registered with permission). Everything else is catalogued with its
  link, including paid books with their price and purchase link.
- Text extraction (PDF, EPUB, DOCX, HTML, TXT, transcripts), language detection, rule-based
  classification into the three pillars, and bilingual keyword search: an Arabic query finds English
  sources and vice versa.
- The research loop: planning, rule-based question generation, bilingual discovery, a persistent
  queue, daily reports, and the next-day plan.

## What needs a Claude API key (`ANTHROPIC_API_KEY`)

Knowledge extraction (claims, quotes, scholars, institutions, citations), AI research questions,
source-grounded synthesis with verified evidence, the AI assistant's written answers, literature
reviews and briefs, and OCR of scanned pages when Tesseract is not installed. These calls are
limited by daily caps on number and cost. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md): installation, start/stop/resume, auto-start, troubleshooting
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md): Claude, budgets, optional APIs, OCR, settings
- [docs/SOURCES.md](docs/SOURCES.md): adding websites, feeds, channels, research topics, new adapters
- [docs/APIFY.md](docs/APIFY.md): collecting TikTok, YouTube, Facebook, Instagram, X, Reddit via Apify
- [docs/BACKUP.md](docs/BACKUP.md): backup and restore
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the system is built
- [docs/STATUS.md](docs/STATUS.md): what is complete, test results, limitations, next steps

## Tests

```
.venv\Scripts\python -m pip install -r requirements-dev.txt      (Linux: .venv/bin/python ...)
.venv\Scripts\python -m pytest
```
