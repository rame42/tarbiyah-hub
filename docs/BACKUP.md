# Backup and restore

A backup is a single `.zip` with the database (a consistent snapshot, safe to take while the system runs),
downloaded files, extracted text, outputs and the inbox. **Your `.env` keys are not included.** Keep
a separate copy of `.env` in a safe place.

## Create a backup

- Dashboard: **Settings > Backup now**. The file is written to the `backups/` folder.
- Terminal: `python -m tarbiyah backup` (or `--dest D:\MyBackups`).

Recommended: back up weekly and copy the zip to an external drive or cloud storage. To automate it on Windows,
add a Task Scheduler task running `.venv\Scripts\python.exe -m tarbiyah backup --dest D:\MyBackups`
in the project folder.

## Restore

1. Stop Tarbiyah Hub (`stop.bat` / `python -m tarbiyah stop`).
2. `python -m tarbiyah restore backups\tarbiyah-backup-YYYYMMDD-HHMMSS.zip`
3. Start again.

The current `data` folder is kept as `data.before-restore-<time>`, so a restore can be undone by
renaming folders. Delete that copy once you're satisfied.

## Moving to another computer

Install Tarbiyah Hub on the new computer, copy the backup zip and your `.env`, run the restore command, and start.
