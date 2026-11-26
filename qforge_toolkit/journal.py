"""Append-only journal: one JSON line per event, flocked and fsync'd.

Never uses a shared temporary directory. The journal file and its lock
live next to each other in the work directory you pass in.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z")


def append(work: Path, event: str, **fields: Any) -> dict[str, Any]:
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    path = work / "JOURNAL.log"
    lock = work / "JOURNAL.log.lock"
    record = {"ts": _now(), "event": event, **fields}
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(lock, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(path, "a") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)
    return record


def read(work: Path) -> list[dict[str, Any]]:
    path = Path(work) / "JOURNAL.log"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def resume_report(work: Path) -> dict[str, Any]:
    rows = read(work)
    events = [r.get("event") for r in rows]
    return {
        "work": str(Path(work)),
        "events": len(rows),
        "last": rows[-1] if rows else None,
        "has_done": "DONE" in events,
        "has_admission": "ADMISSION" in events,
        "has_result": "RESULT" in events,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Append or read a flocked work-dir journal.")
    ap.add_argument("--work", required=True)
    ap.add_argument("event", nargs="?", help="event name to append")
    ap.add_argument("--data", default="{}", help="JSON object of extra fields")
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args(argv)
    if a.resume or not a.event:
        print(json.dumps(resume_report(Path(a.work)), indent=1))
        return 0
    rec = append(Path(a.work), a.event, **json.loads(a.data))
    print(json.dumps(rec, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
