
from pathlib import Path

from qforge_toolkit.ledger import scan
from qforge_toolkit.receipt import build_receipt, write_receipt, verify_receipt


def _receipt(**kw):
    defaults = dict(
        question="What is 2+2?",
        inputs={"source_sha256": {"toy.py": "abc"}},
        baseline=4,
        candidate=4,
        checker={"accepted": True, "independent": True},
        falsifier={"plant": "3", "rejected": True},
        claim="The checker accepted 2+2=4 on this fixture only.",
        not_claimed=["This is not a proof of arithmetic."],
        ceiling="FINITE_EXPERIMENT",
        planted=[{"input": 3, "rejected": True}],
        runtime={"host": "ci", "seconds": 0.01},
    )
    defaults.update(kw)
    return build_receipt(**defaults)


def test_hash_stable_when_runtime_changes(tmp_path: Path):
    a = _receipt(runtime={"seconds": 1})
    b = _receipt(runtime={"seconds": 99})
    assert a["receipt_sha256"] == b["receipt_sha256"]
    assert verify_receipt(a)["ok"]
    b["claim"] = b["claim"] + " extra"
    assert verify_receipt(b)["ok"] is False


def test_ledger_new_same_stale_invalid(tmp_path: Path):
    rec = _receipt()
    path = write_receipt(tmp_path / "r.json", rec)
    led = tmp_path / "LEDGER.json"
    first = scan([tmp_path], ledger_path=led, update=True)
    assert first["summary"]["new"] == 1
    second = scan([tmp_path], ledger_path=led, update=False)
    assert second["summary"]["same"] == 1
    # Change the listed source hash but not the receipt hash -> STALE
    rec["inputs"]["source_sha256"]["toy.py"] = "ddd"
    # keep receipt_sha256 stale relative to sources only: we must rewrite file
    # but keep old hash so verify fails... For STALE, receipt hash stays the
    # same while source_sha256 in the file changes, which also changes the
    # hashed body. So STALE is defined on the *recorded* inputs.source_sha256
    # versus the ledger baseline. That requires an updated body + new hash
    # (REFRESHED) OR we update only the baseline interpretation.
    #
    # The intended STALE case: the receipt file is unchanged, but the caller
    # records a new source hash in a sidecar... Our scan compares the
    # receipt's own inputs.source_sha256 to the baseline. To get STALE we
    # update the baseline's source hash independently.
    import json
    data = json.loads(led.read_text())
    key = str(path)
    data["receipts"][key]["source_sha256"] = {"toy.py": "old"}
    led.write_text(json.dumps(data))
    stale = scan([tmp_path], ledger_path=led, update=False)
    assert stale["summary"]["stale"] == 1
    # Invalidate the sidecar
    Path(str(path) + ".sha256").write_text("0" * 64 + "  r.json\n")
    bad = scan([tmp_path], ledger_path=led, update=False)
    assert bad["summary"]["invalid"] == 1
