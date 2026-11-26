"""ADOPT / STAGE / REJECT gate for a speed claim.

ADOPT only if the candidate is exact, the timings cover the complete task,
both sides used the same thread count (default 1), there are at least 3
paired repeats, and the median per-pair ratio is at least 10% faster.
Otherwise STAGE, or REJECT if the result is not exact.
"""
from __future__ import annotations

import argparse
import json
import statistics
from typing import Any

MARGIN = 0.10
MIN_PAIRS = 3
VERSION = "speedgate-v1"


def _median_ratio(base: list[float], cand: list[float]) -> float:
    if len(base) != len(cand) or len(base) < MIN_PAIRS:
        raise ValueError(f"need >= {MIN_PAIRS} paired timings")
    ratios = [c / b for b, c in zip(base, cand)]
    return float(statistics.median(ratios))


def decide_case(case: dict[str, Any]) -> dict[str, Any]:
    name = case.get("name", "<unnamed>")
    exact = bool(case.get("exact"))
    complete = bool(case.get("complete_task"))
    threads = case.get("threads", 1)
    reasons: list[str] = []
    if not exact:
        reasons.append("not exact")
    if not complete:
        reasons.append("not a complete-task timing")
    if threads != 1 and not case.get("threads_declared"):
        reasons.append("thread count is not 1 and not declared")
    try:
        ratio = _median_ratio(list(map(float, case["base_s"])), list(map(float, case["cand_s"])))
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "name": name,
            "decision": "REJECT",
            "reason": f"bad timings: {exc}",
            "version": VERSION,
        }
    faster = ratio <= (1.0 - MARGIN)
    if not exact:
        decision = "REJECT"
    elif exact and complete and faster and not reasons:
        decision = "ADOPT"
    else:
        decision = "STAGE"
        if not faster:
            reasons.append(f"median ratio {ratio:.4f} is not <= {1.0 - MARGIN:.2f}")
    return {
        "name": name,
        "decision": decision,
        "exact": exact,
        "complete_task": complete,
        "threads": threads,
        "pairs": min(len(case.get("base_s") or []), len(case.get("cand_s") or [])),
        "median_ratio": ratio,
        "reasons": reasons,
        "version": VERSION,
    }


def decide(spec: dict[str, Any]) -> dict[str, Any]:
    cases = [decide_case(c) for c in spec.get("cases") or []]
    if not cases:
        overall = "REJECT"
    elif any(c["decision"] == "REJECT" for c in cases):
        overall = "REJECT"
    elif all(c["decision"] == "ADOPT" for c in cases):
        overall = "ADOPT"
    else:
        overall = "STAGE"
    return {"overall": overall, "cases": cases, "version": VERSION}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ADOPT/STAGE/REJECT a speed-claim spec JSON.")
    ap.add_argument("spec")
    a = ap.parse_args(argv)
    spec = json.loads(open(a.spec, encoding="utf-8").read())
    res = decide(spec)
    print(json.dumps(res, indent=1))
    return 0 if res["overall"] != "REJECT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
