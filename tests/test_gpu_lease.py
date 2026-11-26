
from pathlib import Path

from qforge_toolkit.gpu_lease import acquire, release, status


def test_acquire_release_and_nested(tmp_path: Path, monkeypatch):
    table = tmp_path / "leases.json"
    info = acquire(256, owner="test", margin=128, free_mib=4096, path=table, timeout=1)
    assert info["admitted"] is True
    st = status(free_mib=4096, path=table)
    assert st["reserved_mib"] == 256
    # Insufficient
    denied = acquire(8000, owner="big", margin=1536, free_mib=4096, path=table, timeout=0)
    assert denied["admitted"] is False
    # Nested
    monkeypatch.setenv("QFORGE_GPU_IN_LEASE", "1")
    nested = acquire(256, free_mib=4096, path=table, timeout=1)
    assert nested["refused"] == "nested_lease"
    monkeypatch.delenv("QFORGE_GPU_IN_LEASE")
    assert release(info["lease_id"], path=table) is True
    st2 = status(free_mib=4096, path=table)
    assert st2["reserved_mib"] == 0
