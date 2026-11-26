
from pathlib import Path

from qforge_toolkit.hostguard import check


def test_hostguard_with_fake_proc(tmp_path: Path):
    mem = tmp_path / "meminfo"
    vm = tmp_path / "vmstat"
    mem.write_text("MemAvailable:       2000000 kB\n")  # ~1.9 GiB
    vm.write_text("pswpin 10\npswpout 10\n")
    rec = check(min_avail_gib=9, swap_pages=2000, window_s=0, sleep=lambda _s: None, meminfo=mem, vmstat=vm)
    assert rec["ok"] is False and rec["reason"] == "mem_available"
    mem.write_text("MemAvailable:       20000000 kB\n")  # ~19 GiB
    rec2 = check(min_avail_gib=9, swap_pages=2000, window_s=0, sleep=lambda _s: None, meminfo=mem, vmstat=vm)
    assert rec2["ok"] is True
