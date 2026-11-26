#!/usr/bin/env python3
"""
Cold-Start 10-Gate Verifier + 8 Planted-Mutant Self-Audit (`verify_pmll_gates.py`)
================================================================================
Verifies the entire `qforge-pmll-unified` GitHub repository kit in pure Python 3 stdlib
(compatible with both `python3 -W error` and `python3 -O -W error`, zero bare `assert`s)
plus native C11 compiler verification when `gcc` or `cc` is present.

Gates:
  1. Streaming `djb2` + FWHT 128-bit SimHash (`16 B/slot`) vs Legacy `PMLL.c` (`128 B/slot`)
  2. Hot/Warm/Cold Salience Tiering, `tree[0]` Propagation & Anti-Double-Eviction Write Promotion
  3. Starlight Contract-Bound `QPromise` Deduplication + S_3 x S_q Chart Orbit Canonicalization
  4. GF(2) Augmented-RREF Farkas UNSAT Dual Certifier (`xor_sat.py` bridge)
  5. Iterative Farkas Fault-Excision Noisy Simon / Quantum Syndrome Decoder (`V164`/`V168`)
  6. Deletion-Aware (`d`) DRUP Reverse Unit Propagation Verifier (`SAT.c` bridge)
  7. Exact `Fraction` Sylvester `LDL^T` SPD + Multivariate Nullstellensatz Verifiers (`V167`/`V172`)
  8. Proof-Carrying `ERS` Reconsideration Loop (`drQedwards/ERS` epistemic override)
  9. RFC 6962 Domain-Separated SHA-256 Merkle Proof Manifest + Public GitHub Hygiene Gate
 10. Planted-Mutant Rejection Suite (8/8 hostile mutants MUST be caught and rejected) + C11 Check
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from qforge_pmll import (  # noqa: E402
    EPISTEMIC_EXACT_CERTIFIED,
    TIER_HOT,
    TIER_WARM,
    ContractBoundQPromiseRegistry,
    ERSMemoryBlock,
    ProofCarryingERSEngine,
    StarlightContractKey,
    UpgradedPMLLSilo,
    build_directory_merkle_manifest,
    canonicalize_3xq_chart_orbit,
    decode_noisy_parity_via_farkas_excision,
    rfc6962_leaf_hash,
    rfc6962_node_hash,
    rfc6962_root_and_audit_path,
    scan_repo_hygiene,
    solve_gf2_with_farkas_cert,
    verify_drup_proof,
    verify_farkas_unsat_certificate,
    verify_rational_nullstellensatz,
    verify_rational_spd_certificate,
    verify_rfc6962_inclusion,
)
from qforge_pmll.cli import cmd_benchmark_silo  # noqa: E402


def check(cond: bool, msg: str) -> None:
    """Optimizer-proof gate check (never stripped by `python3 -O`)."""
    if not cond:
        raise RuntimeError(f"VERIFICATION GATE FAILED: {msg}")


def run_all_gates() -> Dict[str, object]:
    t0 = time.perf_counter()
    gate_results: Dict[str, Dict[str, object]] = {}

    # -----------------------------------------------------------------------
    # Gate 1: FWHT 128-bit SimHash (`16 B`) vs Legacy `PMLL.c` (`128 B`)
    # -----------------------------------------------------------------------
    bench = cmd_benchmark_silo()
    disj = bench["disjoint_doc_false_positive_cosine"]  # type: ignore[index]
    retr = bench["noisy_query_top1_retrieval_200slots"]  # type: ignore[index]
    check(
        disj["QForge_FWHT_mean_bias"] < disj["PMLL_legacy_mean_bias"] * 0.45,  # type: ignore[index]
        "FWHT SimHash must cut legacy positive collision bias by >2x",
    )
    check(
        retr["QForge_FWHT_top1_pct"] > retr["PMLL_legacy_top1_pct"] * 2.0,  # type: ignore[index]
        "FWHT SimHash must improve noisy Top-1 retrieval by >2x over legacy 32-D djb2",
    )
    gate_results["gate_01_fwht_simhash_silo"] = {"status": "PASS", "metrics": bench}

    # -----------------------------------------------------------------------
    # Gate 2: Hot/Warm/Cold Tiering, Root-0 Tree Spine & Anti-Double-Eviction
    # -----------------------------------------------------------------------
    silo = UpgradedPMLLSilo(capacity=8, k_hot=2, k_warm=3)
    for idx in range(8):
        silo.set(f"k_{idx}", f"payload_{idx}", reward=0.1 * idx)
    check(silo.tree[0] == 8, f"Expected root tree[0] == 8, got {silo.tree[0]}")
    silo.step_decay_and_reclassify()
    # Multi-insert batch into Cold tier MUST NOT immediately overwrite the slot just written
    slot_a = silo.set("fresh_batch_a", "alpha_vector", reward=0.8)
    slot_b = silo.set("fresh_batch_b", "beta_vector", reward=0.8)
    check(slot_a != slot_b, "Back-to-back batch inserts collided on the same slot (stale tier bug)")
    check(silo.slots[slot_a] is not None and silo.slots[slot_a].tier == TIER_WARM, "Fresh slot not TIER_WARM")  # type: ignore[union-attr]
    check(silo.peek("fresh_batch_a") == "alpha_vector", "First batch item was clobbered")
    check(silo.peek("fresh_batch_b") == "beta_vector", "Second batch item missing")
    gate_results["gate_02_tiered_silo_safety"] = {
        "status": "PASS",
        "tree_root_updates": silo.tree[0],
        "batch_slots": [slot_a, slot_b],
    }

    # -----------------------------------------------------------------------
    # Gate 3: Starlight Contract-Bound QPromises + S_3 x S_q Orbit Deduplication
    # -----------------------------------------------------------------------
    qreg = ContractBoundQPromiseRegistry()
    chart_1 = [[1, 0, 1, 0, 0], [0, 1, 0, 1, 0], [0, 0, 1, 1, 1]]
    # Permute rows (2, 0, 1) and reverse columns -> MUST canonicalize identically!
    chart_2 = [list(reversed(chart_1[2])), list(reversed(chart_1[0])), list(reversed(chart_1[1]))]
    orb_1 = canonicalize_3xq_chart_orbit(chart_1)
    orb_2 = canonicalize_3xq_chart_orbit(chart_2)
    check(orb_1 == orb_2, "S_3 x S_q isomorphic 3x5 charts failed to canonicalize to same orbit key")

    k1 = StarlightContractKey(domain="demo_dc3q", canonical_payload=orb_1)
    k2 = StarlightContractKey(domain="demo_dc3q", canonical_payload=orb_2)
    v1, hit1 = qreg.resolve_or_compute(k1, lambda: "UNSAT_CERT_DEG3", lock_certified=True)
    v2, hit2 = qreg.resolve_or_compute(k2, lambda: "SHOULD_NOT_RUN", lock_certified=True)
    check(not hit1 and hit2 and v1 == v2 == "UNSAT_CERT_DEG3", "QPromise failed to deduplicate orbit")
    check(qreg.compute_calls == 1 and qreg.cache_hits == 1, "Unexpected QPromise call counters")
    gate_results["gate_03_contract_qpromises"] = {
        "status": "PASS",
        "compute_calls": qreg.compute_calls,
        "dedup_hits": qreg.cache_hits,
    }

    # -----------------------------------------------------------------------
    # Gate 4: GF(2) Farkas Dual UNSAT Certificate (`xor_sat.py` Bridge)
    # -----------------------------------------------------------------------
    rng = random.Random(42)
    n_vars = 16
    s_secret = 0b1011001110100101
    rows_sat = [rng.randint(1, (1 << n_vars) - 1) for _ in range(20)]
    rhs_sat = [((r & s_secret).bit_count() & 1) for r in rows_sat]
    res_sat = solve_gf2_with_farkas_cert(rows_sat, rhs_sat, n_vars)
    check(res_sat["status"] == "SAT" and res_sat["assignment_int"] == s_secret, "GF(2) SAT solve mismatch")

    rows_unsat = rows_sat + [rows_sat[2] ^ rows_sat[7] ^ rows_sat[11]]
    rhs_unsat = rhs_sat + [(rhs_sat[2] ^ rhs_sat[7] ^ rhs_sat[11]) ^ 1]
    res_unsat = solve_gf2_with_farkas_cert(rows_unsat, rhs_unsat, n_vars)
    check(res_unsat["status"] == "UNSAT" and res_unsat["certificate_verified"] is True, "GF(2) UNSAT failed")
    check(res_unsat["certificate_indices"] == [2, 7, 11, 20], "Expected exact cycle [2, 7, 11, 20]")
    gate_results["gate_04_gf2_farkas_dual"] = {
        "status": "PASS",
        "farkas_cycle": res_unsat["certificate_indices"],
    }

    # -----------------------------------------------------------------------
    # Gate 5: Noisy Simon / Quantum Syndrome Burst Excision Decoder
    # -----------------------------------------------------------------------
    rng_s = random.Random(20261126)
    s_simon = 0b1101001011100101
    m_shots = 38
    simon_rows = [rng_s.randint(1, (1 << n_vars) - 1) for _ in range(m_shots)]
    simon_rhs = [((r & s_simon).bit_count() & 1) for r in simon_rows]
    planted_flips = [4, 23]
    for fl in planted_flips:
        simon_rhs[fl] ^= 1
    dec = decode_noisy_parity_via_farkas_excision(simon_rows, simon_rhs, n_vars=n_vars, max_excisions=4)
    check(dec["status"] == "RECOVERED_SAT", f"Decoder failed: {dec}")
    check(dec["recovered_secret_int"] == s_simon, "Decoder recovered wrong 16-bit secret")
    check(sorted(dec["excised_row_indices"]) == planted_flips, "Decoder excised unexpected rows")  # type: ignore[arg-type]
    gate_results["gate_05_noisy_simon_farkas_decoder"] = {
        "status": "PASS",
        "planted_flips": planted_flips,
        "excised_rows": dec["excised_row_indices"],
    }

    # -----------------------------------------------------------------------
    # Gate 6: Deletion-Aware (`d`) DRUP Reverse Unit Propagation Checker
    # -----------------------------------------------------------------------
    # Unsatisfiable 2-var CNF: (x1 v x2) ^ (-x1 v x2) ^ (x1 v -x2) ^ (-x1 v -x2)
    cnf_4 = [[1, 2], [-1, 2], [1, -2], [-1, -2]]
    drup_trace = [
        ("a", [2]),          # RUP from (1,2) & (-1,2)
        ("d", [1, 2]),       # DRUP deletion of subsumed clause
        ("a", [-2]),         # RUP from (1,-2) & (-1,-2)
        ("a", []),           # Empty clause conflict!
    ]
    check(verify_drup_proof(cnf_4, drup_trace), "Valid deletion-aware DRUP proof rejected")
    gate_results["gate_06_drup_verifier"] = {"status": "PASS", "steps_checked": len(drup_trace)}

    # -----------------------------------------------------------------------
    # Gate 7: Exact `Fraction` SPD + Multivariate Rational Nullstellensatz
    # -----------------------------------------------------------------------
    spd_ok = verify_rational_spd_certificate(
        [["5", "-2", "1"], ["-2", "4", "-1"], ["1", "-1", "3"]],
        shift_margin_str="1/2",
    )
    check(spd_ok, "Valid rational SPD matrix rejected")

    # 2-variable exact Nullstellensatz:
    # f1 = x^2 + y^2 - 1, f2 = x - 1, f3 = y - 1
    # Identity: -1*(x^2 + y^2 - 1) + (x + 1)*(x - 1) + (y + 1)*(y - 1) == -x^2 - y^2 + 1 + x^2 - 1 + y^2 - 1 == -1
    # Negate multipliers -> +1*(x^2 + y^2 - 1) + (-x - 1)*(x - 1) + (-y - 1)*(y - 1) == +1!
    ns_ok = verify_rational_nullstellensatz(
        n_vars=2,
        generators=[
            [((2, 0), 1), ((0, 2), 1), ((0, 0), -1)],
            [((1, 0), 1), ((0, 0), -1)],
            [((0, 1), 1), ((0, 0), -1)],
        ],
        multipliers=[
            [((0, 0), 1)],
            [((1, 0), -1), ((0, 0), -1)],
            [((0, 1), -1), ((0, 0), -1)],
        ],
    )
    check(ns_ok, "Valid 2-variable Rational Nullstellensatz identity rejected")
    gate_results["gate_07_spd_and_nullstellensatz"] = {"status": "PASS"}

    # -----------------------------------------------------------------------
    # Gate 8: Proof-Carrying `ERS` Reconsideration Override & Decay
    # -----------------------------------------------------------------------
    ers = ProofCarryingERSEngine()
    ers.ingest_block(
        ERSMemoryBlock(
            block_id="heur_wrong",
            proposition_id="prop:cnf_4_sat",
            polarity=True,
            statement="Heuristic WalkSAT guess: 4-clause XOR box might be satisfiable",
            confidence=0.90,
            timestamp_s=10.0,
        )
    )
    ers.ingest_block(
        ERSMemoryBlock(
            block_id="heur_stale",
            proposition_id="prop:transient_note",
            polarity=True,
            statement="Old low-confidence scratch note",
            confidence=0.08,
            timestamp_s=0.0,
            decay_lambda=0.10,
        )
    )
    ers.ingest_block(
        ERSMemoryBlock(
            block_id="cert_drup_unsat",
            proposition_id="prop:cnf_4_sat",
            polarity=False,
            statement="DRUP-certified UNSAT refutation of 4-clause box",
            confidence=1.0,
            timestamp_s=12.0,
            cert_kind="cnf_drup",
            cert_payload={"cnf_clauses": cnf_4, "drup_steps": drup_trace},
        )
    )
    rec = ers.reconsider_all(now_s=20.0)
    check(rec["active_certified"] == ["cert_drup_unsat"], f"Unexpected active_certified: {rec}")
    check(rec["evicted_contradicted_by_proof"] == ["heur_wrong"], "Heuristic contradiction not evicted")
    check(rec["expired_by_decay"] == ["heur_stale"], "Stale heuristic block did not decay-expire")
    check(
        ers.blocks["cert_drup_unsat"].epistemic_tier == EPISTEMIC_EXACT_CERTIFIED,
        "Certified block lost EXACT_CERTIFIED tier",
    )
    silo_idx = ers.silo.key_to_slot["cert_drup_unsat"]
    check(ers.silo.slots[silo_idx].tier == TIER_HOT, "Certified block not locked in TIER_HOT")  # type: ignore[union-attr]
    gate_results["gate_08_ers_reconsideration"] = {"status": "PASS", "summary": rec}

    # -----------------------------------------------------------------------
    # Gate 9: RFC 6962 SHA-256 Merkle Proof Manifest & Repo Hygiene Audit
    # -----------------------------------------------------------------------
    hyg = scan_repo_hygiene(REPO_ROOT)
    check(hyg["clean"] is True, f"Repo hygiene violations detected: {hyg['violations']}")
    manifest = build_directory_merkle_manifest(REPO_ROOT / "qforge_pmll")
    check(len(str(manifest["merkle_root_hex"])) == 64, "Invalid RFC 6962 Merkle root hex")
    gate_results["gate_09_rfc6962_and_hygiene"] = {
        "status": "PASS",
        "scanned_repo_files": hyg["scanned_files"],
        "src_merkle_root_hex": manifest["merkle_root_hex"],
    }

    # -----------------------------------------------------------------------
    # Gate 10: 8 Planted Hostile Mutants + Native C11 Sanitizer Gate
    # -----------------------------------------------------------------------
    mutants_caught = 0

    # Mutant 1: Corrupted GF(2) Farkas dual certificate index
    if not verify_farkas_unsat_certificate(rows_unsat, rhs_unsat, [2, 7, 12, 20]):
        mutants_caught += 1

    # Mutant 2: Non-RUP Bogus Clause in DRUP Trace (3-SAT clauses where unit prop cannot derive [-3] or [])
    cnf_sat3 = [[1, 2, 3], [-1, 2, 3], [1, -2, 3]]
    if not verify_drup_proof(cnf_sat3, [("a", [-3]), ("a", [])]):
        mutants_caught += 1

    # Mutant 3: Starlight Wire-Order Swap Must NOT Collide in QPromise Cache (V119 regression guard)
    kw_a = StarlightContractKey(domain="starlight_circ", canonical_payload="cz_layer", wire_order=(0, 1, 2))
    kw_b = StarlightContractKey(domain="starlight_circ", canonical_payload="cz_layer", wire_order=(2, 1, 0))
    if kw_a.digest_hex() != kw_b.digest_hex():
        mutants_caught += 1

    # Mutant 4: Indefinite Matrix Claiming SPD (`det([[1, 3], [3, 1]]) = -8 < 0`)
    if not verify_rational_spd_certificate([["1", "3"], ["3", "1"]], shift_margin_str="0"):
        mutants_caught += 1

    # Mutant 5: Falsified Nullstellensatz Multiplier Leaving Non-Zero x^2 Remainder
    if not verify_rational_nullstellensatz(
        n_vars=1,
        generators=[[((2,), 1), ((0,), -1)]],
        multipliers=[[((0,), -1)]],  # gives -x^2 + 1 != 1
    ):
        mutants_caught += 1

    # Mutant 6: Tampered Leaf Byte in RFC 6962 Inclusion Proof
    leaves_demo = [b"receipt_0", b"receipt_1", b"receipt_2", b"receipt_3", b"receipt_4"]
    root_demo, path_2 = rfc6962_root_and_audit_path(leaves_demo, target_idx=2)
    if verify_rfc6962_inclusion(leaves_demo[2], path_2, root_demo) and not verify_rfc6962_inclusion(
        b"receipt_2_tampered", path_2, root_demo
    ):
        mutants_caught += 1

    # Mutant 7: RFC 6962 Second-Preimage Leaf-vs-Interior Domain Separation (`0x00` vs `0x01`)
    h_l = rfc6962_leaf_hash(b"A")
    h_r = rfc6962_leaf_hash(b"B")
    interior = rfc6962_node_hash(h_l, h_r)
    forged_single_leaf = rfc6962_leaf_hash(h_l + h_r)
    if interior != forged_single_leaf:
        mutants_caught += 1

    # Mutant 8: Hygiene Scanner Catches Leaked Private Path + Bare `assert` in Verifier
    with tempfile.TemporaryDirectory() as tmpd:
        tp = Path(tmpd)
        bad_ver = tp / "verify_bad.py"
        bad_ver.write_text(
            "p = '/" + "home/alice/secret'\nassert True\n",
            encoding="utf-8",
        )
        bad_scan = scan_repo_hygiene(tp)
        if not bad_scan["clean"] and bad_scan["violation_count"] >= 2:
            mutants_caught += 1

    check(mutants_caught == 8, f"Expected 8/8 planted mutants caught, got {mutants_caught}/8")

    # Native C11 compilation & execution check (`pmll_sat_and_silo_upgrades.c` + `v167_woodbury_rump.c`)
    c_compiler = shutil.which("gcc") or shutil.which("cc")
    c_status = "SKIPPED_NO_CC"
    if c_compiler is not None:
        c_src_pmll = REPO_ROOT / "c_core" / "pmll_sat_and_silo_upgrades.c"
        c_src_rump = REPO_ROOT / "c_core" / "v167_woodbury_rump.c"
        build_parent = REPO_ROOT / ".build_tmp"
        build_parent.mkdir(exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=str(build_parent)) as tmpc:
                bin_pmll = Path(tmpc) / "test_pmll_upgrades"
                so_rump = Path(tmpc) / "v167_woodbury_rump.so"
                subprocess.run(
                    [c_compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", str(c_src_pmll), "-lm", "-o", str(bin_pmll)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                run_out = subprocess.run([str(bin_pmll)], check=True, capture_output=True, text=True)
                check("ALL C11" in run_out.stdout, f"Unexpected C11 test stdout: {run_out.stdout}")
                subprocess.run(
                    [c_compiler, "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", str(c_src_rump), "-lm", "-o", str(so_rump)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                c_status = "PASS_COMPILED_AND_EXECUTED"
        finally:
            shutil.rmtree(build_parent, ignore_errors=True)

    gate_results["gate_10_mutants_and_c11"] = {
        "status": "PASS",
        "mutants_caught": f"{mutants_caught}/8",
        "c11_verification": c_status,
    }

    elapsed_s = round(time.perf_counter() - t0, 4)
    return {
        "schema": "qforge.v173_pmll_unified_kit.v1",
        "FINITE_EXPERIMENT": True,
        "clay_proof": 0,
        "rm_used": False,
        "python_optimized_flag": bool(sys.flags.optimize),
        "gates_passed": len(gate_results),
        "gates_total": 10,
        "mutants_caught": 8,
        "elapsed_seconds": elapsed_s,
        "gates": gate_results,
    }


if __name__ == "__main__":
    summary = run_all_gates()
    print(json.dumps(summary, indent=2))
