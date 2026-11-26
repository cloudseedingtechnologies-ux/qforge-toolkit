"""Receipt ledger: re-check hashes and sidecars, and flag STALE/NEW/SAME/REFRESHED.

A receipt is STALE when a listed source file has changed since the ledger
baseline was written and the receipt hash has not. INVALID means the
receipt hash or sidecar does not match the file bytes / hashed body.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .receipt import SCHEMA, verify_receipt

LEDGER_SCHEMA = "qforge.ledger.v1"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_receipts(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if path.name == "LEDGER.json" or path.name.endswith(".tmp"):
                continue
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(obj, dict) and obj.get("schema") == SCHEMA:
                found.append(path)
    return found


def _sidecar_ok(path: Path, receipt_sha: str) -> bool | None:
    sidecar = Path(str(path) + ".sha256")
    if not sidecar.exists():
        return None
    text = sidecar.read_text(encoding="utf-8").split()
    return bool(text) and text[0] == receipt_sha


def scan(roots: list[Path], ledger_path: Path | None = None, update: bool = False) -> dict[str, Any]:
    roots = [Path(r) for r in roots]
    ledger_path = Path(ledger_path) if ledger_path else (roots[0] / "LEDGER.json" if roots else Path("LEDGER.json"))
    baseline: dict[str, Any] = {}
    if ledger_path.exists():
        try:
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            baseline = raw.get("receipts") or {}
        except (OSError, json.JSONDecodeError):
            baseline = {}

    rows = []
    for path in find_receipts(roots):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        check = verify_receipt(receipt)
        file_sha = sha_file(path)
        sidecar = _sidecar_ok(path, receipt.get("receipt_sha256") or "")
        sources = receipt.get("inputs", {}).get("source_sha256") or {}
        source_now = dict(sources) if isinstance(sources, dict) else {}
        key = str(path)
        prev = baseline.get(key)
        if not check["ok"] or sidecar is False:
            status = "INVALID"
        elif prev is None:
            status = "NEW"
        elif prev.get("receipt_sha256") == receipt.get("receipt_sha256"):
            if prev.get("source_sha256") and prev["source_sha256"] != source_now:
                status = "STALE"
            else:
                status = "SAME"
        else:
            status = "REFRESHED"
        rows.append({
            "path": key,
            "status": status,
            "receipt_sha256": receipt.get("receipt_sha256"),
            "file_sha256": file_sha,
            "sidecar_ok": sidecar,
            "verify": check,
            "source_sha256": source_now,
        })

    summary = {k: 0 for k in ("invalid", "stale", "new", "same", "refreshed")}
    for row in rows:
        summary[row["status"].lower()] += 1

    if update:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": LEDGER_SCHEMA,
            "receipts": {
                row["path"]: {
                    "receipt_sha256": row["receipt_sha256"],
                    "file_sha256": row["file_sha256"],
                    "source_sha256": row["source_sha256"],
                }
                for row in rows
                if row["status"] != "INVALID"
            },
        }
        tmp = ledger_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(ledger_path)

    return {
        "schema": LEDGER_SCHEMA,
        "ledger": str(ledger_path),
        "rows": rows,
        "summary": summary,
    }


def format_table(result: dict[str, Any]) -> str:
    lines = ["status     receipt"]
    for row in result["rows"]:
        lines.append(f"{row['status']:<10} {row['path']}")
    s = result["summary"]
    lines.append(
        "-- invalid={invalid} stale={stale} new={new} same={same} refreshed={refreshed}".format(**s)
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan receipt roots and report ledger status.")
    ap.add_argument("--root", action="append", required=True, help="receipt directory (repeatable)")
    ap.add_argument("--ledger", default=None, help="ledger JSON path")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = scan([Path(r) for r in a.root], ledger_path=Path(a.ledger) if a.ledger else None, update=a.update)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(format_table(res))
    s = res["summary"]
    return 1 if (s["invalid"] or s["stale"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
