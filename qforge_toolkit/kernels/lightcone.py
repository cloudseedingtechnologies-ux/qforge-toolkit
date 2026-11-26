"""Exact light-cone closure for Z / ZZ expectations in brickwork circuits,
Charmander V174.

Gates are 4x4 RATIONAL orthogonal matrices from the Cayley transform
Q = (I - S)(I + S)^-1 of a rational skew-symmetric S, so states stay rational
and <Z_i>, <Z_i Z_j> are compared with exact equality (no tolerance).
The backward light cone of the observable keeps only gates that can reach its
support; simulating that sub-circuit on its own qubits must give the same
rational number as the full simulation. Classical simulation only:
QPU=false, no quantum-advantage claim.
"""
from __future__ import annotations

import random
from fractions import Fraction
from typing import Dict, List, Sequence, Tuple

Gate = Tuple[int, List[List[Fraction]]]  # (left qubit q acting on q,q+1), 4x4 matrix


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("LIGHTCONE_INVARIANT: " + msg)


def _inv(M: List[List[Fraction]]) -> List[List[Fraction]]:
    n = len(M)
    A = [list(M[i]) + [Fraction(int(i == j)) for j in range(n)] for i in range(n)]
    for c in range(n):
        p = next(r for r in range(c, n) if A[r][c] != 0)
        A[c], A[p] = A[p], A[c]
        pv = A[c][c]
        A[c] = [v / pv for v in A[c]]
        for r in range(n):
            if r != c and A[r][c] != 0:
                f = A[r][c]
                A[r] = [A[r][j] - f * A[c][j] for j in range(2 * n)]
    return [row[n:] for row in A]


def _mul(A, B):
    n = len(A)
    return [[sum(A[i][k] * B[k][j] for k in range(n)) for j in range(n)] for i in range(n)]


def cayley_orthogonal(rng: random.Random) -> List[List[Fraction]]:
    S = [[Fraction(0)] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(i + 1, 4):
            v = Fraction(rng.randint(-3, 3), rng.randint(1, 3))
            S[i][j] = v
            S[j][i] = -v
    I = [[Fraction(int(i == j)) for j in range(4)] for i in range(4)]
    ImS = [[I[i][j] - S[i][j] for j in range(4)] for i in range(4)]
    IpS = [[I[i][j] + S[i][j] for j in range(4)] for i in range(4)]
    Q = _mul(ImS, _inv(IpS))
    QtQ = _mul([list(r) for r in zip(*Q)], Q)
    _require(all(QtQ[i][j] == int(i == j) for i in range(4) for j in range(4)), "Cayley gate not orthogonal")
    return Q


def brickwork(n: int, depth: int, seed: int) -> List[List[Gate]]:
    rng = random.Random(seed)
    layers = []
    for d in range(depth):
        start = d % 2
        layers.append([(q, cayley_orthogonal(rng)) for q in range(start, n - 1, 2)])
    return layers


def simulate(n: int, layers: Sequence[Sequence[Gate]], qubits: Sequence[int]) -> List[Fraction]:
    """Simulate the gates acting inside `qubits` (sorted list) from |0...0>."""
    pos = {q: i for i, q in enumerate(qubits)}
    m = len(qubits)
    psi = [Fraction(0)] * (1 << m)
    psi[0] = Fraction(1)
    for layer in layers:
        for q, G in layer:
            if q not in pos or (q + 1) not in pos:
                continue
            a, b = pos[q], pos[q + 1]
            new = list(psi)
            for base in range(1 << m):
                if (base >> a) & 1 or (base >> b) & 1:
                    continue
                idx = [base, base | (1 << b), base | (1 << a), base | (1 << a) | (1 << b)]  # |q,q+1> = 00,01,10,11
                v = [psi[t] for t in idx]
                for r in range(4):
                    new[idx[r]] = sum(G[r][c] * v[c] for c in range(4) if G[r][c] and v[c])
            psi = new
    return psi


def expect_z(psi: Sequence[Fraction], positions: Sequence[int]) -> Fraction:
    tot = Fraction(0)
    for x, amp in enumerate(psi):
        if amp:
            sgn = -1 if sum((x >> p) & 1 for p in positions) & 1 else 1
            tot += sgn * amp * amp
    return tot


def backward_cone(n: int, layers, support: Sequence[int]) -> Tuple[List[List[Gate]], List[int]]:
    S = set(support)
    kept: List[List[Gate]] = []
    for layer in reversed(layers):
        keep = []
        for q, G in layer:
            if q in S or (q + 1) in S:
                keep.append((q, G))
        for q, _ in keep:
            S.update((q, q + 1))
        kept.append(keep)
    kept.reverse()
    return kept, sorted(S)


def observable(n: int, layers, support: Sequence[int], use_cone: bool) -> Tuple[Fraction, int]:
    if use_cone:
        sub, qs = backward_cone(n, layers, support)
    else:
        sub, qs = layers, list(range(n))
    psi = simulate(n, sub, qs)
    pos = {q: i for i, q in enumerate(qs)}
    return expect_z(psi, [pos[s] for s in support]), len(qs)


def kron_reference_state(n: int, layers) -> List[Fraction]:
    """Independent dense reference: build each layer as a full 2^n x 2^n matrix
    entry-by-entry (bit q of the basis index = qubit q) and multiply."""
    N = 1 << n
    psi = [Fraction(int(i == 0)) for i in range(N)]
    for layer in layers:
        for q, G in layer:
            new = [Fraction(0)] * N
            for col in range(N):
                if not psi[col]:
                    continue
                cin = (((col >> q) & 1) << 1) | ((col >> (q + 1)) & 1)
                for rout in range(4):
                    g = G[rout][cin]
                    if g:
                        row = col & ~((1 << q) | (1 << (q + 1)))
                        row |= ((rout >> 1) & 1) << q
                        row |= (rout & 1) << (q + 1)
                        new[row] += g * psi[col]
            psi = new
    return psi


def run_suite() -> Dict[str, object]:
    small = brickwork(5, 3, 7)
    ref = kron_reference_state(5, small)
    _require(simulate(5, small, list(range(5))) == ref, "simulator != dense reference")
    _require(sum(v * v for v in ref) == 1, "state norm is not exactly 1")
    n, depth, seed = 10, 3, 2026
    layers = brickwork(n, depth, seed)
    rows = []
    for support in ([4], [0], [4, 5], [2, 7]):
        full, nf = observable(n, layers, support, use_cone=False)
        cone, nc = observable(n, layers, support, use_cone=True)
        _require(full == cone, f"light-cone mismatch for {support}")
        rows.append({"observable": "Z" * len(support) + str(support), "value": str(cone),
                     "full_qubits": nf, "cone_qubits": nc, "exact_equal": True})
    # traps: a cone missing one gate, and a forward (wrong-direction) cone
    sub, qs = backward_cone(n, layers, [4])
    full, _ = observable(n, layers, [4], use_cone=False)
    drop = [list(l) for l in sub]
    drop[0] = drop[0][1:]  # remove one earliest-layer gate
    psi = simulate(n, drop, qs)
    pos = {q: i for i, q in enumerate(qs)}
    t1 = expect_z(psi, [pos[4]]) != full
    fwd = set([4])
    fwd_layers = []
    for layer in layers:
        keep = [(q, G) for q, G in layer if q in fwd or q + 1 in fwd]
        for q, _ in keep:
            fwd.update((q, q + 1))
        fwd_layers.append(keep)
    qf = sorted(fwd)
    psi2 = simulate(n, fwd_layers, qf)
    t2 = expect_z(psi2, [qf.index(4)]) != full
    traps = {"T1_cone_missing_gate_detected": t1, "T2_forward_cone_detected": t2}
    _require(all(traps.values()), f"trap not caught: {traps}")
    return {
        "kernel": "CHARM-V174-LIGHTCONE-Z-ZZ",
        "n_qubits": n, "depth": depth, "seed": seed,
        "rows": rows, "traps": traps, "QPU": False,
        "claim": "Exact rational equality of full vs light-cone expectations for 4 observables of one random rational-orthogonal brickwork circuit; classical simulation only.",
    }
