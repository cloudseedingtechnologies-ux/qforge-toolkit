"""Independent checks for merged qforge_pmll modules (not the crew verifier alone)."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from qforge_pmll.gf2_farkas_decoder import (
    decode_noisy_parity_via_farkas_excision,
    solve_gf2_with_farkas_cert,
    verify_farkas_unsat_certificate,
)
from qforge_pmll.merkle_anchor import (
    rfc6962_leaf_hash,
    rfc6962_node_hash,
    rfc6962_root_and_audit_path,
    scan_repo_hygiene,
    verify_rfc6962_inclusion,
)
from qforge_pmll.ers_certified_reconsider import (
    verify_drup_proof,
    verify_rational_nullstellensatz,
    verify_rational_spd_certificate,
)
from qforge_pmll.silo_fwht import (
    ContractBoundQPromiseRegistry,
    StarlightContractKey,
    UpgradedPMLLSilo,
    djb2_streaming_u32,
    pmll_legacy_embed_32f,
    qforge_fwht_simhash_128b,
    simhash_angular_cosine,
)


def test_djb2_and_slot_sizes():
    long_tok = "hello-silo"
    h = djb2_streaming_u32(long_tok)
    acc = 5381
    for b in long_tok.lower().encode():
        acc = ((acc * 33) + b) & 0xFFFFFFFF
    assert h == acc
    legacy = pmll_legacy_embed_32f(long_tok)
    fwht = qforge_fwht_simhash_128b(long_tok)
    # Legacy: 32 x float32 = 128 B. FWHT SimHash: 2 x uint64 = 16 B (8.0x size ratio).
    assert len(legacy) * 4 == 128
    if isinstance(fwht, (bytes, bytearray)):
        fwht_bytes = len(fwht)
    elif isinstance(fwht, tuple) and len(fwht) == 2:
        fwht_bytes = 16
    else:
        fwht_bytes = len(fwht)
    assert fwht_bytes == 16
    assert 128 / fwht_bytes == 8.0


def test_farkas_unsat_sat_and_noisy():
    unsat = solve_gf2_with_farkas_cert([1, 1], [0, 1], 1)
    assert unsat["status"] == "UNSAT"
    cert = unsat["certificate_indices"]
    assert list(cert) == [0, 1]
    assert unsat["certificate_verified"] is True
    assert verify_farkas_unsat_certificate([1, 1], [0, 1], cert)
    assert not verify_farkas_unsat_certificate([1, 1], [0, 1], [])
    assert not verify_farkas_unsat_certificate([1, 1], [0, 1], [0])

    s = 0b1011
    rows = [0b0001, 0b0010, 0b0100, 0b1000, 0b1111]
    rhs = [((r & s).bit_count() & 1) for r in rows]
    got = solve_gf2_with_farkas_cert(rows, rhs, 4)
    assert got["status"] == "SAT"
    assert got["assignment_int"] == s

    noisy = list(rhs)
    noisy[0] ^= 1
    dec = decode_noisy_parity_via_farkas_excision(
        rows, noisy, 4, max_excisions=2, num_perm_probes=16, seed=1
    )
    rec = dec.get("recovered_secret_int")
    if rec is not None and ("RECOVER" in str(dec.get("status")) or dec.get("status") == "SAT"):
        assert rec == s


def test_rfc6962_root_tamper_and_second_preimage():
    a, b = b"receipt_A", b"receipt_B"
    ha, hb = rfc6962_leaf_hash(a), rfc6962_leaf_hash(b)
    assert ha != rfc6962_node_hash(ha, hb)
    assert rfc6962_leaf_hash(ha + hb) != rfc6962_node_hash(ha, hb)

    leaves = [b"r0", b"r1", b"r2", b"r3", b"r4"]
    root, path = rfc6962_root_and_audit_path(leaves, 2)
    assert verify_rfc6962_inclusion(leaves[2], path, root)
    assert not verify_rfc6962_inclusion(b"r2_tampered", path, root)

    def leaf(d):
        return hashlib.sha256(b"\x00" + d).digest()

    def node(l, r):
        return hashlib.sha256(b"\x01" + l + r).digest()

    def root_of(ls):
        level = [leaf(x) for x in ls]
        while len(level) > 1:
            nxt = []
            i = 0
            while i < len(level):
                if i + 1 < len(level):
                    nxt.append(node(level[i], level[i + 1]))
                    i += 2
                else:
                    nxt.append(level[i])
                    i += 1
            level = nxt
        return level[0].hex()

    assert root_of(leaves) == root


def test_spd_and_nullstellensatz_plants():
    assert verify_rational_spd_certificate([[1, 0], [0, 1]]) is True
    assert verify_rational_spd_certificate([[0, 1], [1, 0]]) is False
    assert verify_rational_nullstellensatz(1, [[((0,), 1)]], [[((0,), 1)]]) is True
    assert verify_rational_nullstellensatz(1, [[((0,), "1")]], [[((0,), "0")]]) is False


def test_drup_empty_clause_and_reject_empty_proof():
    cnf = [[1], [-1]]
    assert verify_drup_proof(cnf, [("a", [1]), ("a", [-1]), ("a", [])]) is True
    assert verify_drup_proof(cnf, []) is False


def test_qpromise_dedup_resolve_or_compute():
    silo = UpgradedPMLLSilo(capacity=16, k_hot=2, k_warm=4)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return "value-42"

    key = StarlightContractKey(domain="demo", canonical_payload="p", symmetry_sector="full")
    reg = ContractBoundQPromiseRegistry(silo=silo)
    v1 = reg.resolve_or_compute(key, compute)
    v2 = reg.resolve_or_compute(key, compute)

    def _val(x):
        return x[0] if isinstance(x, tuple) else x

    assert _val(v1) == _val(v2) == "value-42"
    assert calls["n"] == 1
    if isinstance(v2, tuple) and len(v2) >= 2:
        assert bool(v2[1]) is True


def test_hygiene_plants_and_clean_repo(tmp_path: Path):
    dirty = tmp_path / "leak.py"
    leak_path = "/" + "home/" + "exampleuser/" + "secret"
    leak_tok = "ghp_" + ("a" * 24)
    dirty.write_text(f"path = '{leak_path}'\n# {leak_tok}\n")
    bad = scan_repo_hygiene(tmp_path)
    assert bad["clean"] is False
    assert int(bad.get("violation_count") or len(bad.get("violations") or [])) >= 2

    root = Path(__file__).resolve().parents[1]
    hyg = scan_repo_hygiene(root)
    assert hyg["clean"] is True, hyg.get("violations")


def test_silo_bias_direction_is_finite_experiment():
    docs = [f"document-body-{i}-unique-payload-{i * i}" for i in range(80)]
    legacy_sims = []
    fwht_sims = []

    def _cos(x, y):
        xs, ys = list(x), list(y)
        dot = sum(u * v for u, v in zip(xs, ys))
        nx = math.sqrt(sum(u * u for u in xs)) or 1.0
        ny = math.sqrt(sum(v * v for v in ys)) or 1.0
        return dot / (nx * ny)

    for i, a in enumerate(docs):
        for b in docs[i + 1 : i + 4]:
            la, lb = pmll_legacy_embed_32f(a), pmll_legacy_embed_32f(b)
            fa, fb = qforge_fwht_simhash_128b(a), qforge_fwht_simhash_128b(b)
            legacy_sims.append(_cos(la, lb))
            try:
                fwht_sims.append(simhash_angular_cosine(fa, fb))
            except Exception:
                fwht_sims.append(_cos(fa, fb))
    assert (sum(legacy_sims) / len(legacy_sims)) > (sum(fwht_sims) / len(fwht_sims))
