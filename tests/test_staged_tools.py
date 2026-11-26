from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_circ_check_script_exits_zero():
    script = ROOT / "tools" / "test_circ_check.py"
    r = subprocess.run([sys.executable, str(script)], cwd=str(ROOT / "tools"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL" in r.stdout or r.returncode == 0


def test_model_adapter_script_exits_zero():
    script = ROOT / "tools" / "test_model_adapter.py"
    r = subprocess.run([sys.executable, str(script)], cwd=str(ROOT / "tools"), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
