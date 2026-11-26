"""Host memory and swap guard.

Default policy: pause (do not start) when MemAvailable is below 9 GiB or
when pswpin+pswpout moves by 2000 or more pages in a 3-second window.
A caller may kill only its own process if that process's VmSwap is above 0.
Thresholds are overridable through the environment or function arguments.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def mem_available_kib(meminfo: Path | None = None) -> int:
    path = Path(meminfo or "/proc/meminfo")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    raise RuntimeError("MemAvailable not found")


def swap_counters(vmstat: Path | None = None) -> tuple[int, int]:
    path = Path(vmstat or "/proc/vmstat")
    pin = pout = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("pswpin "):
            pin = int(line.split()[1])
        elif line.startswith("pswpout "):
            pout = int(line.split()[1])
    return pin, pout


def own_vmswap_kib(status: Path | None = None) -> int:
    path = Path(status or "/proc/self/status")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmSwap:"):
            return int(line.split()[1])
    return 0


def check(
    *,
    min_avail_gib: float | None = None,
    swap_pages: int | None = None,
    window_s: float | None = None,
    sleep=time.sleep,
    meminfo: Path | None = None,
    vmstat: Path | None = None,
) -> dict:
    min_avail_gib = float(os.environ.get("QFORGE_MIN_MEM_GIB", min_avail_gib or 9))
    swap_pages = int(os.environ.get("QFORGE_SWAP_PAGES", swap_pages or 2000))
    window_s = float(os.environ.get("QFORGE_SWAP_WINDOW_S", window_s or 3))
    avail = mem_available_kib(meminfo)
    need = int(min_avail_gib * 1024 * 1024)
    if avail < need:
        return {
            "ok": False,
            "reason": "mem_available",
            "mem_available_kib": avail,
            "need_kib": need,
        }
    p1, o1 = swap_counters(vmstat)
    sleep(window_s)
    p2, o2 = swap_counters(vmstat)
    moved = (p2 - p1) + (o2 - o1)
    if moved >= swap_pages:
        return {
            "ok": False,
            "reason": "swap_pages",
            "pages": moved,
            "threshold": swap_pages,
        }
    return {
        "ok": True,
        "mem_available_kib": avail,
        "swap_pages": moved,
        "own_vmswap_kib": own_vmswap_kib(),
    }
