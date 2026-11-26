"""One registered VRAM lease at a time, recorded in a flocked JSON table.

The table path is QFORGE_GPU_LEASE_TABLE, or else
$XDG_CACHE_HOME/qforge/gpu/leases.json (falling back to ~/.cache/...).
A lease is admitted only when free VRAM minus already reserved amounts
is at least requested MiB plus a reserve margin (default 1536 MiB).
Nested leases are refused via QFORGE_GPU_IN_LEASE. This module does not
run CUDA itself; the wrapper script sets the environment after admission.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

DEFAULT_MARGIN = 1536


def table_path() -> Path:
    env = os.environ.get("QFORGE_GPU_LEASE_TABLE")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "qforge" / "gpu" / "leases.json"


def _smi_free_mib() -> int | None:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # First GPU only; callers that need a different device should set
    # CUDA_VISIBLE_DEVICES before asking for a lease.
    return int(proc.stdout.strip().splitlines()[0].split()[0])


def _open_locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    fcntl.flock(fh, fcntl.LOCK_EX)
    fh.seek(0)
    text = fh.read().strip()
    data = json.loads(text) if text else {"leases": []}
    return fh, data


def _save(fh, data: dict) -> None:
    fh.seek(0)
    fh.truncate()
    json.dump(data, fh, indent=2, sort_keys=True)
    fh.write("\n")
    fh.flush()
    os.fsync(fh.fileno())


def _live(leases: list[dict], now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    live = []
    for lease in leases:
        exp = lease.get("expires_at")
        if exp is not None and now > exp:
            continue
        pid = lease.get("pid")
        if pid and not Path(f"/proc/{pid}").exists():
            continue
        live.append(lease)
    return live


def status(free_mib: int | None = None, path: Path | None = None) -> dict[str, Any]:
    path = path or table_path()
    free = _smi_free_mib() if free_mib is None else free_mib
    fh, data = _open_locked(path)
    try:
        live = _live(data.get("leases") or [])
        reserved = sum(int(l.get("mib") or 0) for l in live)
        available = None if free is None else free - reserved
        return {
            "table": str(path),
            "free_mib": free,
            "reserved_mib": reserved,
            "available_mib": available,
            "live_leases": live,
        }
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def acquire(
    mib: int,
    owner: str = "",
    margin: int = DEFAULT_MARGIN,
    timeout: float = 600,
    *,
    free_mib: int | None = None,
    path: Path | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    if os.environ.get("QFORGE_GPU_IN_LEASE"):
        return {"admitted": False, "refused": "nested_lease"}
    if mib <= 0 or margin < 0:
        return {"admitted": False, "refused": "bad_request"}
    path = path or table_path()
    deadline = time.time() + timeout
    while True:
        free = _smi_free_mib() if free_mib is None else free_mib
        fh, data = _open_locked(path)
        try:
            live = _live(data.get("leases") or [])
            reserved = sum(int(l.get("mib") or 0) for l in live)
            if free is None:
                info = {"admitted": False, "refused": "no_gpu_query", "free": None}
                return info
            available = free - reserved
            if available >= mib + margin:
                lease = {
                    "lease_id": uuid.uuid4().hex,
                    "mib": int(mib),
                    "margin": int(margin),
                    "owner": owner,
                    "pid": os.getpid() if pid is None else pid,
                    "acquired_at": time.time(),
                    "expires_at": time.time() + max(timeout, 1),
                }
                data["leases"] = live + [lease]
                _save(fh, data)
                return {
                    "admitted": True,
                    "refused": None,
                    "free": free,
                    "reserved": reserved + mib,
                    "available": available - mib,
                    "live_leases": len(live) + 1,
                    **lease,
                }
            info = {
                "admitted": False,
                "refused": "insufficient_vram",
                "free": free,
                "reserved": reserved,
                "available": available,
                "need": mib + margin,
            }
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()
        if time.time() >= deadline:
            info["refused"] = "lease_timeout"
            return info
        time.sleep(0.25)


def release(lease_id: str, path: Path | None = None) -> bool:
    path = path or table_path()
    fh, data = _open_locked(path)
    try:
        leases = data.get("leases") or []
        keep = [l for l in leases if l.get("lease_id") != lease_id]
        data["leases"] = keep
        _save(fh, data)
        return len(keep) != len(leases)
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


@contextlib.contextmanager
def lease(mib: int, owner: str = "", margin: int = DEFAULT_MARGIN, timeout: float = 600, **kw):
    info = acquire(mib, owner, margin, timeout, **kw)
    if not info.get("admitted"):
        raise RuntimeError(f"gpu lease refused: {info.get('refused')}")
    try:
        yield info
    finally:
        release(info["lease_id"], path=kw.get("path"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Acquire, release, or show GPU VRAM leases.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    acq = sub.add_parser("acquire")
    acq.add_argument("--mib", type=int, required=True)
    acq.add_argument("--margin", type=int, default=DEFAULT_MARGIN)
    acq.add_argument("--timeout", type=float, default=600)
    acq.add_argument("--owner", default="")
    rel = sub.add_parser("release")
    rel.add_argument("lease_id")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if a.cmd == "acquire":
        info = acquire(a.mib, a.owner, a.margin, a.timeout)
        print(json.dumps(info, indent=1))
        return 0 if info["admitted"] else 75
    print(json.dumps({"released": release(a.lease_id)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
