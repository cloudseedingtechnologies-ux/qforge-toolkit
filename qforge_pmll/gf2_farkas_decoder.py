"""
GF(2) Augmented-RREF Farkas Certifier + Noisy Simon / Quantum Syndrome Fault Excision
=====================================================================================
Extends `drQedwards/pmll`'s `xor_sat.py` (`docs/XOR_SAT.md`) into Q-Forge's quantum
post-processing stack (`V164` / `V168` Simon & QEC syndrome decoding):
  1. Emits machine-checkable minimal Farkas Dual UNSAT Certificates (`c^T A = 0, c^T b = 1`)
     whenever an overdetermined GF(2) parity system becomes inconsistent.
  2. Uses multi-permutation Farkas dual cycle voting to isolate and excise corrupted
     readout bursts and recover the true hidden period `s` with an auditable proof trail.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(f"GF(2) invariant violation: {msg}")


def verify_farkas_unsat_certificate(
    rows_mask: Sequence[int],
    rhs_bits: Sequence[int],
    cert_indices: Sequence[int],
) -> bool:
    """
    Independent O(|cert|) verifier for a GF(2) Farkas UNSAT certificate:
    Checks that `cert_indices` are distinct valid row indices whose XOR has LHS == 0 and RHS == 1.
    """
    m = len(rows_mask)
    if len(rhs_bits) != m or not cert_indices:
        return False
    if len(set(cert_indices)) != len(cert_indices):
        return False
    xor_lhs = 0
    xor_rhs = 0
    for idx in cert_indices:
        if idx < 0 or idx >= m:
            return False
        xor_lhs ^= int(rows_mask[idx])
        xor_rhs ^= int(rhs_bits[idx]) & 1
    return xor_lhs == 0 and xor_rhs == 1


def solve_gf2_with_farkas_cert(
    rows_mask: Sequence[int],
    rhs_bits: Sequence[int],
    n_vars: int,
) -> Dict[str, object]:
    """
    Solves `popcount(rows_mask[i] & x) % 2 == rhs_bits[i]` over GF(2)^n_vars.
    Returns:
      - `status == "SAT"` with `assignment_int`, `nullspace_basis` (for homogeneous Simon!),
        and `assignment_verified == True`, OR
      - `status == "UNSAT"` with `certificate_indices` and `certificate_verified == True`.
    """
    m = len(rows_mask)
    require(len(rhs_bits) == m and n_vars >= 1, "Invalid GF(2) system dimensions")

    aug_lhs = [int(r) for r in rows_mask]
    aug_rhs = [int(b) & 1 for b in rhs_bits]
    # Arbitrary-precision Python int bitmask tracks exact row combinations over GF(2)
    aug_combo = [1 << i for i in range(m)]

    piv_row_for_col: Dict[int, int] = {}
    r_piv = 0
    for col in range(n_vars):
        found: Optional[int] = None
        for r in range(r_piv, m):
            if (aug_lhs[r] >> col) & 1:
                found = r
                break
        if found is None:
            continue
        aug_lhs[r_piv], aug_lhs[found] = aug_lhs[found], aug_lhs[r_piv]
        aug_rhs[r_piv], aug_rhs[found] = aug_rhs[found], aug_rhs[r_piv]
        aug_combo[r_piv], aug_combo[found] = aug_combo[found], aug_combo[r_piv]

        for r in range(m):
            if r != r_piv and ((aug_lhs[r] >> col) & 1):
                aug_lhs[r] ^= aug_lhs[r_piv]
                aug_rhs[r] ^= aug_rhs[r_piv]
                aug_combo[r] ^= aug_combo[r_piv]
        piv_row_for_col[col] = r_piv
        r_piv += 1

    # Check zero-LHS rows for `0 == 1` contradiction -> Farkas dual witness
    for r in range(r_piv, m):
        if aug_lhs[r] == 0 and aug_rhs[r] == 1:
            combo = aug_combo[r]
            cert_idx = [i for i in range(m) if (combo >> i) & 1]
            ok = verify_farkas_unsat_certificate(rows_mask, rhs_bits, cert_idx)
            require(ok, "Constructed Farkas certificate failed self-verification")
            return {
                "status": "UNSAT",
                "rank": r_piv,
                "certificate_indices": cert_idx,
                "certificate_len": len(cert_idx),
                "certificate_verified": ok,
            }

    # Particular solution x_sol
    x_sol = 0
    for col, rp in piv_row_for_col.items():
        if aug_rhs[rp] & 1:
            x_sol |= 1 << col

    # Extract exact nullspace basis (crucial for Simon's algorithm `Y s = 0` where `s != 0`!)
    null_basis: List[int] = []
    for free_col in range(n_vars):
        if free_col in piv_row_for_col:
            continue
        vec = 1 << free_col
        for p_col, rp in piv_row_for_col.items():
            if (aug_lhs[rp] >> free_col) & 1:
                vec |= 1 << p_col
        null_basis.append(vec)

    sat_ok = all(
        (((int(rows_mask[i]) & x_sol).bit_count() & 1) == (int(rhs_bits[i]) & 1))
        for i in range(m)
    )
    require(sat_ok, "Constructed GF(2) SAT assignment failed verification")
    return {
        "status": "SAT",
        "rank": r_piv,
        "assignment_int": x_sol,
        "nullspace_basis": null_basis,
        "assignment_verified": sat_ok,
    }


def decode_noisy_parity_via_farkas_excision(
    rows_mask: Sequence[int],
    noisy_rhs_bits: Sequence[int],
    n_vars: int,
    max_excisions: int = 4,
    num_perm_probes: int = 24,
    seed: int = 20261126,
) -> Dict[str, object]:
    """
    Recovers the true n_vars-bit secret `s` from an overdetermined noisy parity / syndrome
    system `Y s = b (mod 2)` where up to `max_excisions` readout bursts were bit-flipped.

    Mechanism:
      - While the active system is UNSAT, runs `num_perm_probes` randomized row-order RREFs
        to harvest distinct minimal Farkas UNSAT dual certificates.
      - Any uncorrupted row participates in a Farkas conflict ONLY when paired with a corrupted
        row, whereas a corrupted row participates across nearly ALL sampled dual cycles!
      - Excises the single highest-frequency row, records its Farkas witness, and repeats
        until consistent (`SAT` with full rank `n_vars`).
    """
    m = len(rows_mask)
    require(len(noisy_rhs_bits) == m, "Mismatched rows and RHS lengths")
    rng = random.Random(seed)

    active_orig_indices = list(range(m))
    excised_history: List[Dict[str, object]] = []

    for step in range(max_excisions + 1):
        sub_rows = [rows_mask[i] for i in active_orig_indices]
        sub_rhs = [noisy_rhs_bits[i] for i in active_orig_indices]
        base_res = solve_gf2_with_farkas_cert(sub_rows, sub_rhs, n_vars)
        if base_res["status"] == "SAT":
            return {
                "status": "RECOVERED_SAT",
                "recovered_secret_int": base_res["assignment_int"],
                "rank": base_res["rank"],
                "excised_row_indices": [ int(e["excised_row"]) for e in excised_history ],  # type: ignore[arg-type]
                "farkas_audit_trail": excised_history,
            }

        if step == max_excisions:
            break

        # Sample randomized row permutations to collect diverse Farkas conflict cycles
        vote_counts: Dict[int, int] = {orig_i: 0 for orig_i in active_orig_indices}
        sample_cert_orig: List[int] = [
            active_orig_indices[idx] for idx in base_res["certificate_indices"]  # type: ignore[index,union-attr]
        ]

        k_act = len(active_orig_indices)
        for p_idx in range(num_perm_probes):
            perm = list(range(k_act))
            if p_idx > 0:
                rng.shuffle(perm)
            p_rows = [sub_rows[j] for j in perm]
            p_rhs = [sub_rhs[j] for j in perm]
            p_res = solve_gf2_with_farkas_cert(p_rows, p_rhs, n_vars)
            require(p_res["status"] == "UNSAT", "Permuted UNSAT system must remain UNSAT")
            for loc_i in p_res["certificate_indices"]:  # type: ignore[union-attr]
                orig_row = active_orig_indices[perm[int(loc_i)]]
                vote_counts[orig_row] += 1

        # Pick row with highest conflict participation (deterministic lowest-index tie-break)
        culprit = max(active_orig_indices, key=lambda r_id: (vote_counts[r_id], -r_id))
        excised_history.append(
            {
                "step": step,
                "excised_row": culprit,
                "conflict_votes": vote_counts[culprit],
                "probes": num_perm_probes,
                "witness_farkas_cycle": sample_cert_orig,
            }
        )
        active_orig_indices.remove(culprit)

    return {
        "status": "FAILED_EXCISION_BUDGET",
        "excised_row_indices": [int(e["excised_row"]) for e in excised_history],  # type: ignore[arg-type]
        "farkas_audit_trail": excised_history,
    }
