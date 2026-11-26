"""
Proof-Carrying ERS Reconsideration Engine (`drQedwards/ERS` x Q-Forge Certifiers)
=================================================================================
Upgrades `drQedwards/ERS` (`MemoryBlock`, `reconsider_memory`, `detect_contradiction`)
from heuristic float confidence scoring into a mathematically certified epistemic lattice:

  - `EPISTEMIC_HEURISTIC`: decays exponentially (`e^(-lambda * dt)`), evictable.
  - `EPISTEMIC_DEVICE_MEASURED`: bound to hardware receipt & VRAM provenance.
  - `EPISTEMIC_EXACT_CERTIFIED`: carries a verified proof certificate checked by one of
    four independent exact stdlib verifiers:
      1. `gf2_farkas`          : GF(2) parity UNSAT Farkas dual certificate
      2. `cnf_drup`            : DIMACS CNF + deletion-aware (`d`) DRUP Reverse Unit Propagation
      3. `rational_ldl_spd`    : Exact `Fraction` symmetric L D L^T Sylvester positive-definiteness
      4. `nullstellensatz_qq`  : Exact `Fraction` multivariate polynomial `1 == sum_i c_i * f_i`

Certified blocks lock into `TIER_HOT` (`decay_rate = 0.0`, `confidence = 1.0`) and
deterministically invalidate contradicting heuristic blocks during `reconsider_all()`.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .gf2_farkas_decoder import verify_farkas_unsat_certificate
from .silo_fwht import TIER_COLD, TIER_HOT, TIER_WARM, UpgradedPMLLSilo

EPISTEMIC_HEURISTIC = "HEURISTIC"
EPISTEMIC_DEVICE_MEASURED = "DEVICE_MEASURED"
EPISTEMIC_EXACT_CERTIFIED = "EXACT_CERTIFIED"

PolyTerm = Tuple[Tuple[int, ...], Fraction]  # (exponent_tuple, rational_coeff)


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(f"ERS certification error: {msg}")


# ===========================================================================
# Exact Verifier 1: Deletion-Aware DRUP Reverse Unit Propagation Checker
# ===========================================================================
def _is_rup_implied(clauses: Sequence[Set[int]], target_clause: Sequence[int]) -> bool:
    """
    Checks whether `target_clause` is implied by `clauses` via Reverse Unit Propagation (RUP):
    Assumes the negation of every literal in `target_clause` and runs unit propagation to conflict.
    """
    assigned_true: Set[int] = set()
    for lit in target_clause:
        if -lit in assigned_true:
            # Target clause is tautological, trivially implied
            return True
        assigned_true.add(-lit)

    changed = True
    while changed:
        changed = False
        for cl in clauses:
            satisfied = False
            unassigned_lit: Optional[int] = None
            unassigned_count = 0
            for lit in cl:
                if lit in assigned_true:
                    satisfied = True
                    break
                if -lit not in assigned_true:
                    unassigned_lit = lit
                    unassigned_count += 1
                    if unassigned_count > 1:
                        break
            if satisfied:
                continue
            if unassigned_count == 0:
                return True  # Conflict derived!
            if unassigned_count == 1 and unassigned_lit is not None:
                assigned_true.add(unassigned_lit)
                changed = True
    return False


def verify_drup_proof(
    cnf_clauses: Sequence[Sequence[int]],
    drup_steps: Sequence[Tuple[str, Sequence[int]]],
) -> bool:
    """
    Verifies a DRUP UNSAT proof (`("a", lits)` additions and `("d", lits)` deletions,
    matching `c_core/pmll_sat_and_silo_upgrades.c`) ending in the empty clause `("a", [])`.
    """
    active_db: List[Set[int]] = [set(int(x) for x in cl if int(x) != 0) for cl in cnf_clauses]
    for op, raw_lits in drup_steps:
        lits = [int(x) for x in raw_lits if int(x) != 0]
        if op == "d":
            target_set = set(lits)
            for idx, existing in enumerate(active_db):
                if existing == target_set:
                    active_db.pop(idx)
                    break
        elif op == "a":
            if not _is_rup_implied(active_db, lits):
                return False
            if len(lits) == 0:
                return True  # Empty clause proved via RUP!
            active_db.append(set(lits))
        else:
            return False
    return False


# ===========================================================================
# Exact Verifier 2: Exact Rational Sylvester / LDL^T SPD + Margin Certifier
# ===========================================================================
def verify_rational_spd_certificate(
    sym_matrix_rows: Sequence[Sequence[str | int | float]],
    shift_margin_str: str = "0",
) -> bool:
    """
    Verifies over exact `Fraction` arithmetic that `A == A^T` and `A - margin * I` has a
    strictly positive unit-lower `L D L^T` pivot sequence (`D_k > 0` for all `k`),
    proving `lambda_min(A) > margin >= 0` (exact counterpart to `V163`/`V167` Rump SPD!).
    """
    n = len(sym_matrix_rows)
    if n == 0:
        return False
    margin = Fraction(str(shift_margin_str))
    if margin < 0:
        return False

    a: List[List[Fraction]] = []
    for r in range(n):
        if len(sym_matrix_rows[r]) != n:
            return False
        row = [Fraction(str(v)) for v in sym_matrix_rows[r]]
        a.append(row)

    for r in range(n):
        for c in range(r + 1, n):
            if a[r][c] != a[c][r]:
                return False
        a[r][r] -= margin

    # Exact rational LDL^T / Gaussian symmetric pivot elimination
    for k in range(n):
        piv = a[k][k]
        if piv <= 0:
            return False
        for i in range(k + 1, n):
            factor = a[i][k] / piv
            if factor != 0:
                for j in range(k + 1, n):
                    a[i][j] -= factor * a[k][j]
    return True


# ===========================================================================
# Exact Verifier 3: Multivariate Rational Nullstellensatz (`1 == sum c_i f_i`)
# ===========================================================================
def verify_rational_nullstellensatz(
    n_vars: int,
    generators: Sequence[Sequence[Tuple[Sequence[int], str | int]]],
    multipliers: Sequence[Sequence[Tuple[Sequence[int], str | int]]],
) -> bool:
    """
    Verifies over exact `Q[x_0, ..., x_{n-1}]` that `sum_i multipliers[i] * generators[i] == 1`
    with EVERY non-constant monomial cancelling identically to `0/1` (`V170`-`V172` contract).
    """
    if n_vars < 1 or len(generators) != len(multipliers) or len(generators) == 0:
        return False

    acc: Dict[Tuple[int, ...], Fraction] = {}
    for gen_poly, mul_poly in zip(generators, multipliers):
        for g_exp_raw, g_val in gen_poly:
            g_exp = tuple(int(e) for e in g_exp_raw)
            if len(g_exp) != n_vars or any(e < 0 for e in g_exp):
                return False
            gf = Fraction(str(g_val))
            if gf == 0:
                continue
            for m_exp_raw, m_val in mul_poly:
                m_exp = tuple(int(e) for e in m_exp_raw)
                if len(m_exp) != n_vars or any(e < 0 for e in m_exp):
                    return False
                mf = Fraction(str(m_val))
                if mf == 0:
                    continue
                prod_exp = tuple(g_exp[k] + m_exp[k] for k in range(n_vars))
                acc[prod_exp] = acc.get(prod_exp, Fraction(0)) + gf * mf

    zero_exp = (0,) * n_vars
    if acc.get(zero_exp, Fraction(0)) != Fraction(1):
        return False
    for exp, coeff in acc.items():
        if exp != zero_exp and coeff != Fraction(0):
            return False
    return True


# ===========================================================================
# Proof-Carrying ERS MemoryBlock & Reconsideration Loop
# ===========================================================================
@dataclasses.dataclass
class ERSMemoryBlock:
    block_id: str
    proposition_id: str
    polarity: bool  # True = asserts proposition_id holds; False = asserts negation (!proposition_id)
    statement: str
    confidence: float
    timestamp_s: float
    epistemic_tier: str = EPISTEMIC_HEURISTIC
    decay_lambda: float = 0.05
    cert_kind: Optional[str] = None
    cert_payload: Optional[Dict[str, object]] = None
    cert_verified: bool = False
    status: str = "ACTIVE"

    def sha256_hex(self) -> str:
        raw = json.dumps(
            {
                "block_id": self.block_id,
                "proposition_id": self.proposition_id,
                "polarity": self.polarity,
                "statement": self.statement,
                "epistemic_tier": self.epistemic_tier,
                "cert_kind": self.cert_kind,
                "cert_verified": self.cert_verified,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class ProofCarryingERSEngine:
    """
    Integrates `drQedwards/ERS` recursive reconsideration with Q-Forge's exact verifiers
    and `UpgradedPMLLSilo`.
    """

    def __init__(self, silo: Optional[UpgradedPMLLSilo] = None) -> None:
        self.silo = silo or UpgradedPMLLSilo(capacity=128, k_hot=24, k_warm=48)
        self.blocks: Dict[str, ERSMemoryBlock] = {}

    @staticmethod
    def verify_attached_certificate(cert_kind: str, payload: Dict[str, object]) -> bool:
        if cert_kind == "gf2_farkas":
            return verify_farkas_unsat_certificate(
                payload["rows_mask"],  # type: ignore[arg-type]
                payload["rhs_bits"],  # type: ignore[arg-type]
                payload["certificate_indices"],  # type: ignore[arg-type]
            )
        if cert_kind == "cnf_drup":
            return verify_drup_proof(
                payload["cnf_clauses"],  # type: ignore[arg-type]
                payload["drup_steps"],  # type: ignore[arg-type]
            )
        if cert_kind == "rational_ldl_spd":
            return verify_rational_spd_certificate(
                payload["matrix"],  # type: ignore[arg-type]
                str(payload.get("margin", "0")),
            )
        if cert_kind == "nullstellensatz_qq":
            return verify_rational_nullstellensatz(
                int(payload["n_vars"]),  # type: ignore[arg-type]
                payload["generators"],  # type: ignore[arg-type]
                payload["multipliers"],  # type: ignore[arg-type]
            )
        return False

    def ingest_block(self, block: ERSMemoryBlock) -> ERSMemoryBlock:
        if block.cert_kind is not None and block.cert_payload is not None:
            ok = self.verify_attached_certificate(block.cert_kind, block.cert_payload)
            if not ok:
                block.cert_verified = False
                block.status = "REJECTED_INVALID_CERTIFICATE"
                block.confidence = 0.0
                self.blocks[block.block_id] = block
                return block
            block.cert_verified = True
            block.epistemic_tier = EPISTEMIC_EXACT_CERTIFIED
            block.confidence = 1.0
            block.decay_lambda = 0.0
            self.silo.set(block.block_id, block.statement, reward=1.0, lock_hot=True)
        else:
            self.silo.set(block.block_id, block.statement, reward=block.confidence, lock_hot=False)

        self.blocks[block.block_id] = block
        return block

    def reconsider_all(self, now_s: float) -> Dict[str, object]:
        """
        Executes Dr. Q's `reconsider_memory` pass upgraded with exact proof precedence:
          1. Applies `e^(-lambda * dt)` temporal decay to non-certified blocks.
          2. Detects any contradicting `(proposition_id, !polarity)` pairs; if one side is
             `EPISTEMIC_EXACT_CERTIFIED`, deterministically evicts the contradicted heuristic block!
          3. Detects unresolvable Certified-vs-Certified bugs (raises `RuntimeError` if two
             opposite polarities ever both claimed valid proofs — soundness canary!).
        """
        certified_truths: Dict[str, Tuple[bool, str]] = {}
        for blk in self.blocks.values():
            if blk.status != "ACTIVE":
                continue
            if blk.epistemic_tier == EPISTEMIC_EXACT_CERTIFIED and blk.cert_verified:
                if blk.proposition_id in certified_truths:
                    prev_pol, prev_id = certified_truths[blk.proposition_id]
                    require(
                        prev_pol == blk.polarity,
                        f"Soundness violation: conflicting certified blocks {prev_id} vs {blk.block_id}",
                    )
                certified_truths[blk.proposition_id] = (blk.polarity, blk.block_id)

        evicted_contradicted: List[str] = []
        decayed_expired: List[str] = []
        active_certified: List[str] = []
        active_heuristic: List[str] = []

        for blk in self.blocks.values():
            if blk.status != "ACTIVE":
                continue
            if blk.epistemic_tier == EPISTEMIC_EXACT_CERTIFIED and blk.cert_verified:
                active_certified.append(blk.block_id)
                continue

            # Check contradiction against certified theorems
            if blk.proposition_id in certified_truths:
                cert_pol, _ = certified_truths[blk.proposition_id]
                if blk.polarity != cert_pol:
                    blk.confidence = 0.0
                    blk.status = "EVICTED_CONTRADICTED_BY_PROOF"
                    evicted_contradicted.append(blk.block_id)
                    continue

            # Apply exponential temporal decay
            dt = max(0.0, now_s - blk.timestamp_s)
            blk.confidence = blk.confidence * math.exp(-blk.decay_lambda * dt)
            if blk.confidence < 0.05:
                blk.status = "EXPIRED_DECAY"
                decayed_expired.append(blk.block_id)
            else:
                active_heuristic.append(blk.block_id)

        tier_counts = self.silo.step_decay_and_reclassify()
        return {
            "active_certified": sorted(active_certified),
            "active_heuristic": sorted(active_heuristic),
            "evicted_contradicted_by_proof": sorted(evicted_contradicted),
            "expired_by_decay": sorted(decayed_expired),
            "silo_tier_counts": tier_counts,
        }
