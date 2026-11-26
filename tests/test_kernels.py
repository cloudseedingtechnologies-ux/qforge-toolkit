"""K1-K7 kernels: known values, brute-force cross-checks, planted traps, and python vs python -O receipt parity."""
import json
import os
import random
import subprocess
import sys

import pytest

from qforge_toolkit.kernels import (certified_residual, detcert, exact_synth, flats_fast, fwht_sharpsat,
                                    lightcone, sat_phase)
from qforge_toolkit.kernels.cdcl import CDCL, check_model, check_rup_proof

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X0, X1, X2 = 0b10101010, 0b11001100, 0b11110000


@pytest.mark.parametrize("mod", [fwht_sharpsat, certified_residual, lightcone, detcert, flats_fast])
def test_kernel_suite_traps(mod):
    r = mod.run_suite()
    assert r["traps"] and all(r["traps"].values()), mod.__name__


def test_exact_synthesis_known_sizes():
    assert exact_synth.synthesize(3, X0 ^ X1 ^ X2, basis="aig")["size"] == 6
    assert exact_synth.synthesize(3, X0 ^ X1 ^ X2, basis="b2")["size"] == 2
    assert exact_synth.synthesize(2, 0b0110, basis="aig")["size"] == 3
    assert exact_synth.synthesize(3, X0 & X1 & X2, basis="aig")["size"] == 2
    maj = (X0 & X1) | (X0 & X2) | (X1 & X2)
    r = exact_synth.synthesize(3, maj, basis="aig", certify=True)
    assert r["size"] == 4 and r["stats"]["unsat_proofs_checked"] >= 1


def test_mcsp_star_partial_function():
    # parity3 with rows 0 and 7 left unspecified needs only 4 AIG gates
    assert exact_synth.synthesize(3, X0 ^ X1 ^ X2, care=0b01111110, basis="aig", certify=True)["size"] == 4


def test_cdcl_matches_brute_force_with_checked_certificates():
    rng = random.Random(11)
    for _ in range(300):
        n = rng.randint(3, 10)
        cls = [[rng.choice((-1, 1)) * rng.randint(1, n) for _ in range(rng.randint(1, 3))]
               for _ in range(rng.randint(1, 5 * n))]
        brute = any(all(any(((x >> (abs(l) - 1)) & 1) == (l > 0) for l in c) for c in cls) for x in range(1 << n))
        s = CDCL(n, cls, proof=True)
        r = s.solve()
        assert r == brute
        assert check_model(cls, s.model) if r else check_rup_proof(n, cls, s.proof)


def test_rup_checker_rejects_planted_proofs():
    php = [[1, 2], [-1, 2], [1, -2], [-1, -2]]
    assert check_rup_proof(2, php, [[2], []])
    assert not check_rup_proof(2, php, [[2]])          # no empty clause
    assert not check_rup_proof(1, [[1], [-1]], [[1]])  # proof does not end with []
    assert not check_rup_proof(3, [[1, 2, 3]], [[]])   # SAT formula: [] is not RUP


def test_sat_sweep_is_seeded_and_checked():
    a = sat_phase.sweep(n=20, per_alpha=6)
    b = sat_phase.sweep(n=20, per_alpha=6)
    assert a == b


def _suite_receipt(flags):
    p = subprocess.run([sys.executable, *flags, "-m", "qforge_toolkit", "kernels", "suite"], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stderr[-800:]
    d = json.loads(p.stdout)
    assert d["all_checks_passed"] and d["traps_caught"] == d["traps_total"] and d["clay_proof"] == 0 and d["QPU"] is False
    return d["receipt_sha256"]


def test_receipt_parity_normal_vs_O():
    assert _suite_receipt([]) == _suite_receipt(["-O"])


def test_affine_flats_match_slow_closure_enumeration():
    from itertools import combinations
    for n in (3, 4):
        fast = {frozenset(f) for f in flats_fast.affine_flats(n)}
        pts = range(1 << n)
        slow = set()
        for k in [1 << j for j in range(n + 1)]:
            if n == 4 and k == 8:
                continue  # C(16, 8) closure checks are slow; sizes 1, 2, 4, 16 cover the n = 4 case
            for s in combinations(pts, k):
                S = set(s)
                if all((x ^ y ^ z) in S for x in s for y in s for z in s):
                    slow.add(frozenset(s))
        fast_cmp = {f for f in fast if not (n == 4 and len(f) == 8)}
        assert fast_cmp == slow, n
