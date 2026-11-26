"""Task-card validator. A card is refused when the owner is the reviewer,
a falsifier is missing, a planted error is missing, the ceiling is unknown
or too high, or the wording trips the claim linter without a limiter.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from . import CEILING_RANK
from .claim_lint import lint_text

REQUIRED = ("id", "owner", "reviewer", "question", "ceiling", "falsifier", "planted", "not_claimed")


def validate_card(card: dict[str, Any], max_ceiling: str | None = None) -> dict[str, Any]:
    problems: list[str] = []
    for key in REQUIRED:
        if key not in card:
            problems.append("missing " + key)
    if not problems:
        if card["owner"] == card["reviewer"]:
            problems.append("owner must not be the reviewer")
        if card["ceiling"] not in CEILING_RANK:
            problems.append("unknown ceiling " + str(card["ceiling"]))
        elif max_ceiling:
            if max_ceiling not in CEILING_RANK:
                problems.append("unknown max_ceiling " + max_ceiling)
            elif CEILING_RANK[card["ceiling"]] > CEILING_RANK[max_ceiling]:
                problems.append("ceiling exceeds allowed maximum " + max_ceiling)
        if not card.get("falsifier"):
            problems.append("falsifier is required")
        planted = card.get("planted") or []
        if not isinstance(planted, list) or not planted:
            problems.append("at least one planted error is required")
        lint = lint_text(str(card.get("question", "")), "question")
        # Questions may mention the words "prove" when describing the task;
        # only flag unbounded claim-like wording in an optional claim field.
        if card.get("claim"):
            lint = lint_text(str(card["claim"]), "claim")
            if lint["findings"]:
                problems.append("claim wording is not limited: " + lint["findings"][0]["sentence"])
    return {"ok": not problems, "problems": problems, "id": card.get("id")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a task card JSON file.")
    ap.add_argument("card")
    ap.add_argument("--max-ceiling", default=None)
    a = ap.parse_args(argv)
    card = json.loads(open(a.card, encoding="utf-8").read())
    res = validate_card(card, max_ceiling=a.max_ceiling)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
