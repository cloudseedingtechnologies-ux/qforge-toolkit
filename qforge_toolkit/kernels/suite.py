"""Run all seven kernels with their traps and return one receipt (timings under runtime, so the
hash is identical under python and python -O). Ported from the Charmander V174 Neptune lab.
Finite experiments only: clay_proof = 0, QPU = false.
"""
from __future__ import annotations

import json
import time

from . import certified_residual, detcert, exact_synth, flats_fast, fwht_sharpsat, lightcone, sat_phase
from .. import claim_lint, receipt

X0, X1, X2 = 0b10101010, 0b11001100, 0b11110000


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("KERNEL_INVARIANT: " + msg)


def k1_exact_synthesis(full_tables: bool = True) -> dict:
    named = {
        "xor2": X0 ^ X1, "parity3": X0 ^ X1 ^ X2, "majority3": (X0 & X1) | (X0 & X2) | (X1 & X2),
        "and3": X0 & X1 & X2, "mux3": (X2 & X1) | ((~X2 & 0xFF) & X0),
    }
    rows = []
    for name, tt in named.items():
        for basis in ("aig", "b2"):
            r = exact_synth.synthesize(3, tt, basis=basis, certify=True)
            rows.append({"function": name, "basis": basis, "size": r["size"], "minimality": r["minimality"],
                         "unsat_proofs_checked": r["stats"]["unsat_proofs_checked"]})
    sizes = {(r["function"], r["basis"]): r["size"] for r in rows}
    require(sizes[("parity3", "aig")] == 6 and sizes[("parity3", "b2")] == 2, "parity3 sizes")
    require(sizes[("majority3", "aig")] == 4 and sizes[("majority3", "b2")] == 4, "majority3 sizes")
    star = exact_synth.synthesize(3, X0 ^ X1 ^ X2, care=0b01111110, basis="aig", certify=True)
    xor4 = exact_synth.synthesize(4, sum(1 << t for t in range(16) if bin(t).count("1") & 1), basis="b2", certify=True)
    out = {"named": rows, "mcsp_star_parity3_6of8_aig": star["size"], "xor4_b2": xor4["size"]}
    if full_tables:
        aig = exact_synth.full_table(3, "aig", certify=True)
        b2 = exact_synth.full_table(3, "b2", certify=True)
        bfs = exact_synth.bfs_b2_table3()
        require(all(b2[t] == bfs[t] for t in range(256)), "B2 table: SAT vs independent BFS mismatch")
        hist = lambda T: {str(k): sum(1 for v in T.values() if v == k) for k in sorted(set(T.values()))}
        out["aig_table_histogram"] = hist(aig)
        out["b2_table_histogram"] = hist(b2)
        out["b2_sat_vs_bfs_mismatches"] = 0
        out["aig_table_sha256"] = receipt.receipt_sha256({"aig": [aig[t] for t in range(256)]})
    # traps
    traps = {}
    r = exact_synth.synthesize(3, X0 ^ X1 ^ X2, basis="aig", certify=False)
    g = [(tuple(op), a, b) for op, a, b in r["gates"]]
    g_bad = list(g)
    op, a, b = g_bad[0]
    g_bad[0] = ((op[0] ^ 1, op[1], op[2]), a, b)
    traps["T1_mutated_gate_fails_resimulation"] = any(
        exact_synth.simulate(3, g_bad, r["output_polarity"], t) != ((X0 ^ X1 ^ X2) >> t) & 1 for t in range(8))
    from .cdcl import check_rup_proof
    traps["T2_truncated_rup_proof_rejected"] = not check_rup_proof(2, [[1, 2], [-1, 2], [1, -2], [-1, -2]], [[2]])
    traps["T3_proof_without_empty_clause_rejected"] = not check_rup_proof(1, [[1], [-1]], [[1]])
    require(all(traps.values()), f"K1 trap not caught: {traps}")
    out["traps"] = traps
    out["claim"] = ("Exact minimum sizes for small fixed functions, each SAT answer re-simulated and each "
                    "smaller size refuted with a checked RUP proof; finite experiment, not a P vs NP statement.")
    out["ceiling"] = "FINITE_EXPERIMENT"
    return out


def run_suite(full_tables: bool = True) -> dict:
    t0 = time.perf_counter()
    timings = {}
    parts = {}
    for key, fn in (
        ("K1_exact_synthesis_mcsp", lambda: k1_exact_synthesis(full_tables)),
        ("K2_fwht_thr_xor_sharpsat", fwht_sharpsat.run_suite),
        ("K3_certified_residual_cg", certified_residual.run_suite),
        ("K4_lightcone_z_zz", lightcone.run_suite),
        ("K5_determinantal_certificates", detcert.run_suite),
        ("K6_random_3sat_sweep", lambda: sat_phase.sweep(n=40, per_alpha=30)),
        ("K7_flats_ip2", flats_fast.run_suite),
    ):
        t = time.perf_counter()
        parts[key] = fn()
        timings[key + "_s"] = round(time.perf_counter() - t, 4)
    lint = claim_lint.lint_json(parts, "kernels")
    require(not lint["findings"], f"claim_lint findings: {lint['findings']}")
    traps = {f"{k}.{tk}": tv for k, v in parts.items() for tk, tv in (v.get("traps") or {}).items()}
    require(all(traps.values()), "a planted trap was not caught")
    body = receipt.build_receipt(
        question="Do the qforge-toolkit kernels reproduce their exact checks and catch every planted mutant?",
        inputs={"module": "qforge_toolkit.kernels.suite", "full_tables": full_tables},
        baseline="independent references inside each kernel (brute force, BFS, exact solve, dense simulator, slow flat enumeration)",
        candidate=parts,
        checker={"traps_caught": sum(traps.values()), "traps_total": len(traps), "claim_lint_findings": 0},
        falsifier={"traps": traps},
        claim="All seven kernels passed their exact cross-checks on these finite instances only.",
        not_claimed=["any P vs NP, Clay or Millennium result", "quantum advantage (QPU=false)",
                     "constant-time or side-channel safety", "results beyond the listed instances"],
        ceiling="FINITE_EXPERIMENT",
        runtime={"total_s": round(time.perf_counter() - t0, 3), **timings, "python_O": not __debug__},
    )
    body["clay_proof"] = 0
    body["QPU"] = False
    body["all_checks_passed"] = True
    body["traps_caught"] = sum(traps.values())
    body["traps_total"] = len(traps)
    return body


def pvsnp_panel(n: int = 40, per_alpha: int = 30) -> dict:
    """Small payload for POST /api/millennium/simulate (p_vs_np)."""
    sweep = sat_phase.sweep(n=n, per_alpha=per_alpha)
    k1 = k1_exact_synthesis(full_tables=False)
    k2 = fwht_sharpsat.run_suite()
    payload = {
        "sat_sweep": sweep,
        "exact_synthesis": {"named": k1["named"], "mcsp_star_parity3_6of8_aig": k1["mcsp_star_parity3_6of8_aig"]},
        "fwht_sharpsat": {k: k2[k] for k in ("n_vars", "xor_gates", "threshold", "count_ge_threshold", "brute_force_match")},
        "clay_proof": 0,
        "QPU": False,
    }
    payload["receipt_sha256"] = receipt.receipt_sha256(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run the K1-K7 kernel suite (receipt JSON) or the small 3-SAT panel.")
    ap.add_argument("mode", nargs="?", default="suite", choices=["suite", "panel", "quick"])
    a = ap.parse_args(argv)
    if a.mode == "panel":
        print(json.dumps(pvsnp_panel(), sort_keys=True))
    else:
        print(json.dumps(run_suite(full_tables=(a.mode == "suite")), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
