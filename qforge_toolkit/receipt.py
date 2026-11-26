"""Deterministic receipts with a hashed body and an unhashed runtime section.

The hashed body covers the question, inputs, baseline, candidate, independent
checker verdict, falsifier, claim, not_claimed, and failures. Timings, host
names and interpreter versions belong in `runtime` and do not affect the hash.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "qforge.receipt.v1"


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def receipt_sha256(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def build_receipt(
    *,
    question: str,
    inputs: dict[str, Any],
    baseline: Any,
    candidate: Any,
    checker: dict[str, Any],
    falsifier: dict[str, Any],
    claim: str,
    not_claimed: list[str],
    failures: list[Any] | None = None,
    ceiling: str = "FINITE_EXPERIMENT",
    planted: list[dict[str, Any]] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "schema": SCHEMA,
        "question": question,
        "inputs": inputs,
        "baseline": baseline,
        "candidate": candidate,
        "checker": checker,
        "falsifier": falsifier,
        "claim": claim,
        "not_claimed": list(not_claimed),
        "failures": list(failures or []),
        "ceiling": ceiling,
        "planted": list(planted or []),
    }
    receipt = dict(body)
    receipt["receipt_sha256"] = receipt_sha256(body)
    receipt["runtime"] = dict(runtime or {})
    return receipt


def hashed_body(receipt: dict[str, Any]) -> dict[str, Any]:
    skip = {"receipt_sha256", "runtime"}
    return {k: v for k, v in receipt.items() if k not in skip}


def verify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("schema") != SCHEMA:
        return {"ok": False, "reason": "unknown or missing schema"}
    want = receipt.get("receipt_sha256")
    got = receipt_sha256(hashed_body(receipt))
    if want != got:
        return {"ok": False, "reason": "receipt_sha256 mismatch", "got": got, "want": want}
    return {"ok": True, "receipt_sha256": got}


def write_receipt(path: Path, receipt: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    sidecar = Path(str(path) + ".sha256")
    sidecar.write_text(receipt["receipt_sha256"] + "  " + path.name + "\n", encoding="utf-8")
    return path
