# Installation and daily operation

## 1. Requirements

- Windows 10/11, Linux or macOS
- **Python 3.11 or newer** (python.org). On Windows tick **"Add python.exe to PATH"** in the installer.
- About 1 GB free disk for the program, plus space for the collection (default storage limit: 20 GB, adjustable).
- Internet access (for collection; the dashboard itself works offline).
- Optional: **Tesseract OCR** with Arabic, for scanned books ([CONFIGURATION.md](CONFIGURATION.md#ocr)).
- Not needed: Docker, a GPU, or a local AI model. Node.js is needed only if you change the dashboard code.

## 2. Install (once)

**Windows:** double-click `install.bat`. It creates a private Python environment in `.venv`, installs the
packages, creates `.env` from `.env.example`, and prepares the database.

**Linux/macOS:**
```bash
./install.sh
```

## 3. Start, stop, resume

| Action | Windows | Linux/macOS | Any system (terminal) |
|---|---|---|---|
| Start everything | `start.bat` | `./start.sh` | `python -m tarbiyah run` |
| Start only the worker | | | `python -m tarbiyah worker` |
| Start only the dashboard | | | `python -m tarbiyah web` |
| Stop safely | `stop.bat` | `./stop.sh` | `python -m tarbiyah stop` |
| Pause all automated work | Dashboard > Research Center > Pause | | `python -m tarbiyah pause` |
| Resume | Dashboard > Resume | | `python -m tarbiyah resume` |
| Run one research cycle now | Dashboard > Research Center | | `python -m tarbiyah cycle` |
| Show status | Dashboard | | `python -m tarbiyah status` |

(In a terminal, first activate the environment: Windows `.venv\Scripts\activate`, Linux `source .venv/bin/activate`.)

**What "resume" means.** Every job is stored in the database. If the computer turns off or a window is
closed, the jobs that were running are re-queued automatically the next time the worker starts, and a
crawl continues from its saved checkpoint. Finished work is never repeated. Searches identical to
recent ones are skipped, and resources already in the library are never duplicated.

**`stop` vs closing the window.** `stop` lets running jobs finish first. Closing the window is
also safe: the interrupted job is simply resumed later.

## 3b. Updating to a new version (no reinstall)

Updates replace **program files only**. `data\`, `.env`, `.venv\` and `backups\` are never touched, so your
library, sources, questions, settings and keys stay exactly as they are.

- **From a zip file:** drag the new `tarbiyah-hub.zip` **onto `update.bat`**. It stops the system,
  updates, and starts again by itself.
- **Automatically from GitHub:** put `TH_UPDATE_REPO=owner/repository` (and `TH_UPDATE_TOKEN=` for a private
  repository) in `.env`. Settings > Updates then shows when a new version is ready, and double-clicking
  `update.bat` installs it.

Never delete the folder and extract a new copy: that would delete `data\` too.

## 4. Run automatically

**Windows (at login, restarts if it crashes):** right-click `scripts\install-autostart-windows.ps1` >
*Run with PowerShell*. This runs the worker and dashboard without console windows. To remove it:
`Unregister-ScheduledTask -TaskName "TarbiyahHub" -Confirm:$false` in PowerShell.

**Linux server (at boot):** copy `scripts/tarbiyah-worker.service` and `scripts/tarbiyah-web.service` to
`/etc/systemd/system/`, edit `User` and the paths, then
`sudo systemctl daemon-reload && sudo systemctl enable --now tarbiyah-worker tarbiyah-web`.

The worker works only during the **operating hours** set in Settings (default: all day), and within the
daily limits (web requests, downloads, AI calls and AI spend). When a limit is reached, work waits until
the next day.

## 5. First steps after starting

1. Open http://127.0.0.1:8000.
2. **Settings:** review the limits (storage, daily requests, AI budget) and the operating hours.
3. **Sources:** the free academic and book indexes are enabled. Add websites, RSS feeds, YouTube channels
   and Telegram channels you want monitored ([SOURCES.md](SOURCES.md)).
4. **Research Center:** three starter objectives (one per pillar) are included. Edit them or add your own.
5. Drop PDFs/EPUBs you own into `data/inbox/`; they are imported within 15 minutes.
6. Optional: put your `ANTHROPIC_API_KEY` in `.env` and restart, to enable AI analysis.

## 6. Where things are stored

| Path | Content |
|---|---|
| `data/tarbiyah.db` | database (metadata, questions, findings, jobs, reports) |
| `data/files/` | downloaded / imported files (checksum-named) |
| `data/text/` | extracted original text |
| `data/outputs/` | generated reports, bibliographies, evidence tables |
| `data/inbox/` | drop files here to import them |
| `data/logs/tarbiyah.log` | log file |
| `.env` | your keys (never shared, never shown in the dashboard) |

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `install.bat` says Python is required | Install Python 3.11+ with "Add to PATH", then reopen the folder. |
| The dashboard shows "Worker: not running" | Start it (`start.bat` or `python -m tarbiyah worker`). Check `data/logs/tarbiyah.log`. |
| A source shows `needs_credentials` | That platform needs a key in `.env`; see CONFIGURATION.md. Others keep working. |
| A source shows `error` | Open Sources to read the error. Fix the configuration and click **Run now**. Failed jobs can be retried in Jobs. |
| Documents marked `needs_ocr` | Install Tesseract with Arabic, or add a Claude key; they are reprocessed automatically. |
| "Daily ... limit reached" | Raise the limit in Settings, or wait until tomorrow (work resumes automatically). |
| Port 8000 in use | `python -m tarbiyah web --port 8080` |
| Want to reset everything | Stop the system, back up, then delete the `data` folder. |
