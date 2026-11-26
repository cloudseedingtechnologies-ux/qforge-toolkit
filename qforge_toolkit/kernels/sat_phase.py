"""Measured random 3-SAT sweep for the Millennium Studio P vs NP panel,
Charmander V174. Replaces the synthetic alpha_c = 4.267 sigmoid with REAL,
reproducible finite-n data: seeded random 3-CNFs are decided by our CDCL;
every SAT answer is model-checked and every UNSAT answer is RUP-checked.

Finite n (default 20 variables) only: the location/sharpness of the
threshold at this size is NOT the asymptotic value ~4.267 from the literature,
and nothing here bears on P vs NP.
"""
from __future__ import annotations

import random
import statistics
from typing import Dict, List

from .cdcl import CDCL, check_model, check_rup_proof


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("SAT_PHASE_INVARIANT: " + msg)


def random_3cnf(n: int, m: int, rng: random.Random) -> List[List[int]]:
    return [[rng.choice((-1, 1)) * v for v in rng.sample(range(1, n + 1), 3)] for _ in range(m)]


def sweep(n: int = 20, per_alpha: int = 12, alphas=None, seed: int = 4267, certify: bool = True) -> Dict[str, object]:
    _require(5 <= n <= 60 and 1 <= per_alpha <= 200, "parameters out of range")
    alphas = alphas or [round(3.2 + 0.2 * i, 1) for i in range(10)]
    rows = []
    for a in alphas:
        m = int(round(a * n))
        sat = 0
        confl = []
        props = []
        for i in range(per_alpha):
            rng = random.Random(f"{seed}:{n}:{a}:{i}")
            cls = random_3cnf(n, m, rng)
            s = CDCL(n, cls, proof=certify)
            r = s.solve()
            _require(r is not None, "solver gave up")
            if r:
                _require(check_model(cls, s.model), "bad model")
                sat += 1
            elif certify:
                _require(check_rup_proof(n, cls, s.proof), "RUP proof rejected")
            confl.append(s.conflicts)
            props.append(s.propagations)
        rows.append({
            "alpha": a,
            "clauses": m,
            "instances": per_alpha,
            "sat_fraction": round(sat / per_alpha, 4),
            "median_conflicts": statistics.median(confl),
            "max_conflicts": max(confl),
            "median_propagations": statistics.median(props),
        })
    return {
        "kernel": "CHARM-V174-RANDOM-3SAT-SWEEP",
        "data_source": "MEASURED (seeded random 3-CNF, our CDCL, models checked, UNSAT RUP-checked)" if certify
        else "MEASURED (seeded random 3-CNF, our CDCL, models checked, UNSAT not proof-checked)",
        "n_vars": n,
        "seed": seed,
        "rows": rows,
        "literature_reference_alpha_c": 4.267,
        "note": "Finite-n measurement; the asymptotic threshold ~4.267 is a literature value, not measured here.",
        "clay_proof": 0,
    }
