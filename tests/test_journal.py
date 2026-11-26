
from pathlib import Path

from qforge_toolkit.journal import append, read, resume_report


def test_append_and_resume(tmp_path: Path):
    append(tmp_path, "ADMISSION", run="t1")
    append(tmp_path, "RESULT", run="t1", status="ok")
    append(tmp_path, "DONE", run="t1")
    rows = read(tmp_path)
    assert [r["event"] for r in rows] == ["ADMISSION", "RESULT", "DONE"]
    report = resume_report(tmp_path)
    assert report["has_done"] and report["events"] == 3
