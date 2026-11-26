
import json
from pathlib import Path

from qforge_toolkit.lab_index import build, validate
from qforge_toolkit.sealkit import sha_file


def test_build_and_validate(tmp_path: Path):
    # A real small file acts as a "seal"
    blob = tmp_path / "QFORGE_TOOLKIT_SAMPLE.tgz"
    blob.write_bytes(b"not-a-real-archive-just-bytes")
    seed = {
        "guardrails": ["Never over-claim."],
        "seals": [{"name": blob.name, "sha256": "", "locations": [str(tmp_path)]}],
        "cards": [{"id": "C1", "question": "toy"}],
        "open_problems": [{"id": "P1", "title": "toy problem"}],
        "claim_ledger": [],
    }
    (tmp_path / "lab_index_seed.json").write_text(json.dumps(seed), encoding="utf-8")
    index = build(tmp_path)
    assert index["seals"][0]["sha256"] == sha_file(blob)
    rec = validate(tmp_path)
    assert rec["status"] == "PASS", rec
    # Tamper
    blob.write_bytes(b"tampered")
    rec2 = validate(tmp_path)
    assert rec2["status"] == "FAIL"
    assert any("hash mismatch" in p for p in rec2["problems"])
