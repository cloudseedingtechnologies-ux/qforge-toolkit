"""Build and validate a small lab index of seals, cards, and open problems.

The index directory is taken from --dir or QFORGE_INDEX_DIR. `validate`
re-hashes every seal file that still has a location. Empty location lists
are allowed (for illustrative indexes). Paths may start with `~`.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "qforge.lab_index.v1"
REQUIRED = ("schema", "seals", "cards", "open_problems", "claim_ledger")


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def render_markdown(index: dict[str, Any]) -> str:
    lines = ["# Lab index", ""]
    if index.get("guardrails"):
        lines.append("## Guardrails")
        for g in index["guardrails"]:
            lines.append(f"- {g}")
        lines.append("")
    lines.append(f"## Seals ({len(index.get('seals') or [])})")
    for s in index.get("seals") or []:
        lines.append(f"- `{s.get('name')}` sha256 `{s.get('sha256', '')[:16]}…`")
    lines.append("")
    lines.append(f"## Cards ({len(index.get('cards') or [])})")
    for c in index.get("cards") or []:
        lines.append(f"- `{c.get('id')}`: {c.get('question', '')}")
    lines.append("")
    lines.append(f"## Open problems ({len(index.get('open_problems') or [])})")
    for p in index.get("open_problems") or []:
        lines.append(f"- `{p.get('id')}`: {p.get('title', p.get('question', ''))}")
    lines.append("")
    return "\n".join(lines) + "\n"


def build(index_dir: Path, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    seed_path = index_dir / "lab_index_seed.json"
    if seed is None:
        if seed_path.exists():
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
        elif (index_dir / "lab_index.json").exists():
            seed = json.loads((index_dir / "lab_index.json").read_text(encoding="utf-8"))
        else:
            seed = {"schema": SCHEMA, "seals": [], "cards": [], "open_problems": [], "claim_ledger": []}
    index = dict(seed)
    index["schema"] = SCHEMA
    for key in ("seals", "cards", "open_problems", "claim_ledger"):
        index.setdefault(key, [])
    # Fill missing sha256 values from files that are present.
    for seal in index["seals"]:
        for loc in seal.get("locations") or []:
            path = _expand(loc)
            candidate = path / seal["name"] if path.is_dir() or not path.suffix else path
            if candidate.is_file():
                digest = sha_file(candidate)
                if not seal.get("sha256"):
                    seal["sha256"] = digest
                elif seal["sha256"] != digest:
                    seal.setdefault("conflicts", []).append(str(candidate))
                break
    body = json.dumps(index, indent=2, sort_keys=True) + "\n"
    md = render_markdown(index) + f"<!-- json_sha256 {hashlib.sha256(body.encode()).hexdigest()} -->\n"
    lock = index_dir / ".lock"
    with open(lock, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            for name, text in (("lab_index.json", body), ("LAB_INDEX.md", md)):
                tmp = index_dir / (name + ".tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(index_dir / name)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)
    return index


def validate(index_dir: Path) -> dict[str, Any]:
    index_dir = Path(index_dir)
    path = index_dir / "lab_index.json"
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "problems": [f"unreadable lab_index.json: {type(exc).__name__}"]}
    problems: list[str] = []
    for key in REQUIRED:
        if key not in index:
            problems.append("missing " + key)
    checked = 0
    for seal in index.get("seals") or []:
        if seal.get("conflicts"):
            problems.append("sha conflict " + str(seal.get("name")))
        for loc in seal.get("locations") or []:
            base = _expand(loc)
            candidate = base / seal["name"] if base.is_dir() or not str(base).endswith(seal["name"]) else base
            if not candidate.is_file():
                # also try loc as the file itself
                if base.is_file() and base.name == seal["name"]:
                    candidate = base
                else:
                    problems.append("missing seal file " + str(candidate))
                    continue
            if seal.get("sha256") and sha_file(candidate) != seal["sha256"]:
                problems.append("hash mismatch " + str(candidate))
            checked += 1
    md = index_dir / "LAB_INDEX.md"
    if md.exists():
        body = (index_dir / "lab_index.json").read_bytes()
        if f"json_sha256 {hashlib.sha256(body).hexdigest()}" not in md.read_text(encoding="utf-8"):
            problems.append("markdown is not generated from the current json")
    else:
        problems.append("missing LAB_INDEX.md")
    return {
        "status": "PASS" if not problems else "FAIL",
        "seal_files_rehashed": checked,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build or validate a lab index directory.")
    ap.add_argument("command", choices=("build", "validate"))
    ap.add_argument("--dir", default=os.environ.get("QFORGE_INDEX_DIR"), help="index directory")
    a = ap.parse_args(argv)
    if not a.dir:
        raise SystemExit("pass --dir or set QFORGE_INDEX_DIR")
    if a.command == "build":
        index = build(Path(a.dir))
        print(json.dumps({
            "seals": len(index["seals"]),
            "cards": len(index["cards"]),
            "open_problems": len(index["open_problems"]),
        }))
        return 0
    res = validate(Path(a.dir))
    print(json.dumps(res, indent=1))
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
