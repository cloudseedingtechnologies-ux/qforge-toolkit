from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRIB = ROOT / "contrib" / "neptune_pmll"


def _run(script: str, opt: bool = False):
    cmd = [sys.executable]
    if opt:
        cmd.append("-O")
    cmd.append(str(CONTRIB / script))
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def test_audit_engine_normal_and_opt():
    a = _run("pmll_drq_audit_engine.py", False)
    b = _run("pmll_drq_audit_engine.py", True)
    assert a["all_checks_passed"] is True
    assert a["pillars_passed"] == a["pillars_total"] == 5
    assert a["finite_experiment"] is True
    assert b["all_checks_passed"] is True
    assert a["receipt_sha256"] == b["receipt_sha256"]


def test_sync_engine_normal_and_opt():
    a = _run("qforge_pmll_sync.py", False)
    b = _run("qforge_pmll_sync.py", True)
    assert a["all_checks_passed"] is True
    assert a["trap_battery"]["traps_caught"] == 6
    assert a["trap_battery"]["all_rejected_fail_closed"] is True
    assert b["all_checks_passed"] is True
    assert a["receipt_sha256"] == b["receipt_sha256"]
