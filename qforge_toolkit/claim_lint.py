"""Over-claim linter for prose and receipt claims.

A sentence is flagged when it uses a strength word (prove, certified,
solved, quantum advantage, ...) unless the same sentence clearly limits
the claim (not, never, only, staged, refused, ...). JSON receipts are
checked on the "claim" field only; "not_claimed" is never scanned.

This is a review aid. A clean lint is not a proof.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import CEILING_RANK

RISK = re.compile(
    r"\b(prov(?:e|es|ed|en|ing)|proof of|clay proof|millennium proof|"
    r"certif(?:y|ies|ied|icate)|verified|solves the|solved|"
    r"quantum advantage|qpu advantage|guarantee\w*|speed-?up|faster)\b",
    re.I,
)
LIMIT = re.compile(
    r"\b(not|no|never|only|cannot|can't|without|nor|neither|isn't|"
    r"doesn't|don't|won't|didn't|forbid\w*|reject\w*|refus\w*|"
    r"over-?claim\w*|not_claimed|must not|fail-closed|ban\w*|"
    r"unproven|none|nothing|staged|not_run|unenforced|limits?|"
    r"hand|model|counterexample|fail)\b",
    re.I,
)
STRENGTH_VS_CEILING = [
    (5, re.compile(r"\b(bounded certificate|certified|certifies)\b", re.I)),
    (4, re.compile(r"\b(solved-case replay|solved case replay|reproduced a known)\b", re.I)),
]
_FENCE = re.compile(r"```.*?```", re.S)
_SPLIT = re.compile(r"(?<=[.!?;])\s+")


def _sentences(text: str):
    text = _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        lineno = text[:offset].count("\n") + 1
        offset += len(raw_line)
        if not line.strip() or line.strip().startswith("#"):
            continue
        parts = _SPLIT.split(line) if line else [line]
        col = 0
        for sent in parts:
            yield lineno, sent
            col += len(sent)


def lint_text(text: str, filename: str = "<text>") -> dict[str, Any]:
    findings = []
    for lineno, sentence in _sentences(text):
        hits = [m.group(0) for m in RISK.finditer(sentence)]
        if not hits:
            continue
        if LIMIT.search(sentence):
            continue
        findings.append({
            "file": filename,
            "line": lineno,
            "hits": hits,
            "sentence": sentence.strip()[:240],
        })
    return {"file": filename, "findings": findings}


def lint_json(obj: Any, filename: str = "<json>") -> dict[str, Any]:
    findings = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "claim" in node and isinstance(node["claim"], str):
                res = lint_text(node["claim"], filename)
                for f in res["findings"]:
                    f["where"] = path + ".claim"
                    findings.append(f)
                ceiling = node.get("ceiling") or node.get("evidence_ceiling")
                if isinstance(ceiling, str) and ceiling in CEILING_RANK:
                    rank = CEILING_RANK[ceiling]
                    for need, pat in STRENGTH_VS_CEILING:
                        if pat.search(node["claim"]) and rank < need:
                            findings.append({
                                "file": filename,
                                "line": path + ".claim",
                                "hits": [pat.pattern],
                                "sentence": (
                                    f"claim uses a stronger marker than ceiling {ceiling}"
                                ),
                            })
            for k, v in node.items():
                if k == "not_claimed":
                    continue
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(obj, "")
    return {"file": filename, "findings": findings}


def lint_path(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return lint_json(json.loads(text), str(path))
    return lint_text(text, str(path))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flag over-claim wording in prose or receipt JSON.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything is listed")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    findings: list[dict] = []
    files = []
    for f in a.files:
        p = Path(f)
        res = lint_path(p)
        findings.extend(res["findings"])
        files.append(str(p))
    out = {"files": files, "findings": findings}
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for f in findings:
            where = f.get("line", f.get("where"))
            print(f"{f['file']}:{where}: {','.join(map(str, f['hits']))}: {f['sentence']}")
        print(f"-- {len(files)} files, {len(findings)} sentences listed for review")
    return 1 if (a.strict and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
