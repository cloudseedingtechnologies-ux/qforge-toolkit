
from pathlib import Path

from qforge_toolkit.sealkit import leak_scan, receipt, seal, sha_file


def test_seal_receipt_and_leak_plant(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("hello from the sample kit\n", encoding="utf-8")
    (src / "note.txt").write_text("path hint: /not/a/real/home/project\n", encoding="utf-8")
    out = tmp_path / "out"
    result = seal("SAMPLE_SEAL", src, out, max_bytes=1_000_000, work_home="/not/a/real/home")
    assert Path(result["archive"]).is_file()
    assert result["home_paths_replaced"] >= 1
    rec = receipt("SAMPLE_SEAL", out)
    assert rec["status"] == "PASS"
    assert rec["work_copy_ok"] is True
    # Plant a token and show the sealer refuses.
    plant = tmp_path / "plant"
    plant.mkdir()
    (plant / "secret.txt").write_text("token ghp_" + "a" * 24 + "\n", encoding="utf-8")
    hits = leak_scan(plant)
    assert hits, "planted token must be visible to the leak scanner"
    try:
        seal("PLANTED", plant, tmp_path / "out2", work_home="/no/such")
    except ValueError as exc:
        assert "leak scan failed" in str(exc)
    else:
        raise AssertionError("sealer must refuse a planted token")


def test_refuse_overwrite(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x\n")
    dest = tmp_path / "dest"
    seal("ONE", src, tmp_path / "o1", deliver_to=[dest])
    try:
        seal("ONE", src, tmp_path / "o2", deliver_to=[dest])
    except FileExistsError:
        pass
    else:
        raise AssertionError("delivery must refuse overwrite")
