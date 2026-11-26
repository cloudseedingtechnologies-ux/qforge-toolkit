"""Command-line entry: python -m qforge_toolkit <command> ..."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `pmll` (repo-root package) to import when run as -m.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

COMMANDS = {
    "claim-lint": "qforge_toolkit.claim_lint",
    "ledger": "qforge_toolkit.ledger",
    "card": "qforge_toolkit.task_card",
    "speedgate": "qforge_toolkit.speedgate",
    "index": "qforge_toolkit.lab_index",
    "journal": "qforge_toolkit.journal",
    "gpu-lease": "qforge_toolkit.gpu_lease",
    "pmll-export": "pmll.pmll_export",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("qforge_toolkit commands:")
        for name in COMMANDS:
            print("  " + name)
        print("Also: scripts/lean_check.sh and scripts/gpu_lease_run.sh")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    mod = __import__(COMMANDS[cmd], fromlist=["main"])
    return int(mod.main(rest))


if __name__ == "__main__":
    raise SystemExit(main())
