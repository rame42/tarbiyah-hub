"""Command line: python -m tarbiyah <command>

  init                      create/upgrade the database and seed data
  web [--host H --port P]   start the dashboard + API (http://127.0.0.1:8000)
  worker                    start the background worker + scheduler (keeps running)
  run                       start web server and worker together (one terminal)
  status                    print queue / worker / source status
  import PATH [PATH...]     import local files or folders
  search QUERY              keyword search (Arabic or English)
  pause | resume            pause or resume all automated work
  cycle                     queue one research cycle now
  drain [--seconds N]       process queued jobs in the foreground until the queue is empty
  report [--day YYYY-MM-DD] build (or rebuild) a daily report
  backup [--dest DIR]       consistent backup of the database and files
  restore ARCHIVE           restore a backup archive (stop web/worker first)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _setup_logging() -> None:
    from .config import get_config

    cfg = get_config()
    handlers = [logging.StreamHandler(sys.stdout),
                logging.FileHandler(cfg.logs_dir / "tarbiyah.log", encoding="utf-8")]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tarbiyah", description="Tarbiyah Hub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    w = sub.add_parser("web")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    sub.add_parser("worker")
    r = sub.add_parser("run")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, default=8000)
    sub.add_parser("status")
    im = sub.add_parser("import")
    im.add_argument("paths", nargs="+")
    im.add_argument("--type", default="book")
    se = sub.add_parser("search")
    se.add_argument("query")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("cycle")
    dr = sub.add_parser("drain")
    dr.add_argument("--seconds", type=int, default=600)
    rp = sub.add_parser("report")
    rp.add_argument("--day")
    bk = sub.add_parser("backup")
    bk.add_argument("--dest")
    rs = sub.add_parser("restore")
    rs.add_argument("archive")
    args = ap.parse_args(argv)

    _setup_logging()
    if args.cmd == "restore":  # must run before the database is opened
        from .backup import restore

        print(restore(Path(args.archive)))
        return 0

    from .bootstrap import init_app

    init_app()
    from .db import session_scope

    if args.cmd == "init":
        print("Database ready.")
    elif args.cmd == "web":
        import uvicorn

        uvicorn.run("tarbiyah.api.app:app", host=args.host, port=args.port, log_level="info")
    elif args.cmd == "worker":
        from .jobs.worker import Worker

        wk = Worker()
        wk.install_signal_handlers()
        wk.run_forever()
    elif args.cmd == "run":
        import multiprocessing

        p = multiprocessing.Process(target=main, args=(["worker"],), daemon=False)
        p.start()
        try:
            import uvicorn

            uvicorn.run("tarbiyah.api.app:app", host=args.host, port=args.port, log_level="info")
        finally:
            p.terminate()  # SIGTERM -> the worker finishes running jobs and stops cleanly
            p.join(60)
    elif args.cmd == "status":
        from .api.status import system_status

        with session_scope() as s:
            print(json.dumps(system_status(s), indent=2, ensure_ascii=False, default=str))
    elif args.cmd == "import":
        from .ingest.extract import SUPPORTED_EXT
        from .ingest.pipeline import import_local_file
        from .jobs import queue

        files: list[Path] = []
        for p in args.paths:
            pp = Path(p)
            files += [f for f in pp.rglob("*") if f.suffix.lower() in SUPPORTED_EXT] if pp.is_dir() else [pp]
        with session_scope() as s:
            for f in files:
                res, created = import_local_file(s, f, resource_type=args.type)
                if created:
                    queue.enqueue(s, "process", {"resource_id": res.id}, group="processing", dedupe_key=f"process:{res.id}")
                print(("imported " if created else "already in library ") + f"#{res.id}: {f.name}")
        print("Files are processed by the worker (or run: python -m tarbiyah drain).")
    elif args.cmd == "search":
        from .search.fts import search

        with session_scope() as s:
            res = search(s, args.query, limit=10)
        print(f"{res['total']} result(s); expansions: {list(res['expansions'])}")
        for x in res["results"]:
            r = x["resource"]
            print(f"#{r['id']} [{r['language']}] {r['title'][:90]}")
            if x["passage"]:
                print("    " + x["passage"]["text"][:200].replace("\n", " "))
    elif args.cmd in ("pause", "resume"):
        from .settings import set_setting

        with session_scope() as s:
            set_setting(s, "paused", args.cmd == "pause")
        print("Automation " + ("paused." if args.cmd == "pause" else "resumed."))
    elif args.cmd == "cycle":
        from .jobs import queue

        with session_scope() as s:
            j = queue.enqueue(s, "research_cycle", {}, priority=30, dedupe_key="research_cycle", group="research")
        print(f"research cycle queued (job {j.id})")
    elif args.cmd == "drain":
        from .jobs.worker import Worker

        wk = Worker(with_scheduler=False)
        wk.startup()
        wk.drain(timeout=args.seconds)
        print("queue drained (or time limit reached)")
    elif args.cmd == "report":
        from datetime import date

        from .agents.reports import build_daily_report

        with session_scope() as s:
            rep = build_daily_report(s, date.fromisoformat(args.day) if args.day else date.today())
            print(rep.summary)
    elif args.cmd == "backup":
        from .backup import backup

        print(backup(Path(args.dest) if args.dest else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
