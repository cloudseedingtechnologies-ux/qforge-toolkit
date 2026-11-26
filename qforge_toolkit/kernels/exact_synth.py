"""Exact circuit synthesis (small-n MCSP / MCSP*) by SAT, Charmander V174.

Generalises the desk engine (pequalnp-desk work/synth.py, validated against
site-accepted rows) to any n-input truth table, total or partial (MCSP*),
over two bases with free output negation:
  basis="aig": fan-in-2 AND with free input/output inversions (U2 basis)
  basis="b2" : all 16 two-input functions (B2 basis)
Every gate is normalised (g(0,0)=0); the output polarity absorbs row 0.

Each SAT answer is decoded and re-simulated on every specified row (fail-closed).
Minimality: sizes k < k_min are UNSAT; with certify=True each UNSAT answer
carries a RUP proof checked by an independent forward checker.
Finite experiment only: small-n circuit sizes say nothing about P vs NP.
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

from .cdcl import CDCL, check_model, check_rup_proof

# normal gate functions as (f01, f10, f11) with f(a,b) table; f00 = 0
AIG_OPS = {(0, 0, 1), (0, 1, 0), (1, 0, 0), (1, 1, 1)}
B2_OPS = AIG_OPS | {(1, 1, 0)}
ALL_NORMAL = {(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)}


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("EXACT_SYNTH_INVARIANT: " + msg)


def _gate_eval(op: Tuple[int, int, int], p: int, q: int) -> int:
    if p == 0 and q == 0:
        return 0
    return op[0] if (p, q) == (0, 1) else op[1] if (p, q) == (1, 0) else op[2]


def simulate(n: int, gates: List[Tuple[Tuple[int, int, int], int, int]], polarity: int, row: int) -> int:
    w = [(row >> j) & 1 for j in range(n)]
    for op, a, b in gates:
        w.append(_gate_eval(op, w[a], w[b]))
    out = w[-1] if gates else 0
    return out ^ polarity


def _encode(n: int, rows: Dict[int, int], k: int, ops: set, useall: bool = True):
    nv = 0

    def new() -> int:
        nonlocal nv
        nv += 1
        return nv

    cl: List[List[int]] = []
    R = sorted(t for t in rows if t != 0)
    X = [{t: new() for t in R} for _ in range(k)]
    F = [[new() for _ in range(3)] for _ in range(k)]
    SEL: List[List[Tuple[int, int, int]]] = []
    for g in range(k):
        W = n + g
        opts = [(new(), a, b) for a in range(W) for b in range(a + 1, W)]
        SEL.append(opts)
        cl.append([o[0] for o in opts])
        # restrict the gate function to the basis
        for bits in ALL_NORMAL - ops:
            cl.append([(-F[g][i] if bits[i] else F[g][i]) for i in range(3)])

    def wire(w: int, t: int):
        if w < n:
            return ("c", (t >> w) & 1)
        return ("v", X[w - n][t])

    for g in range(k):
        for (s, a, b) in SEL[g]:
            for t in R:
                y = X[g][t]
                A = wire(a, t)
                B = wire(b, t)
                for p in (0, 1):
                    for q in (0, 1):
                        base = [-s]
                        skip = False
                        for (kind, val), want in ((A, p), (B, q)):
                            if kind == "c":
                                if val != want:
                                    skip = True
                                    break
                            else:
                                base.append(-val if want else val)
                        if skip:
                            continue
                        if p == 0 and q == 0:
                            cl.append(base + [-y])
                            continue
                        fi = F[g][0] if (p, q) == (0, 1) else F[g][1] if (p, q) == (1, 0) else F[g][2]
                        cl.append(base + [-fi, y])
                        cl.append(base + [fi, -y])
    return nv, cl, X, F, SEL, R


def _decode(model, k, F, SEL):
    gates = []
    for g in range(k):
        s = [o for o in SEL[g] if model[o[0]] == 1][0]
        op = tuple(model[F[g][i]] for i in range(3))
        gates.append((op, s[1], s[2]))
    return gates


def synthesize(
    n: int,
    tt: int,
    care: Optional[int] = None,
    basis: str = "aig",
    max_gates: int = 12,
    certify: bool = True,
    conflict_limit: Optional[int] = None,
) -> Dict[str, object]:
    _require(1 <= n <= 6, "n must be in 1..6")
    _require(basis in ("aig", "b2"), "basis must be aig or b2")
    full = (1 << (1 << n)) - 1
    care = full if care is None else care & full
    rows = {t: (tt >> t) & 1 for t in range(1 << n) if (care >> t) & 1}
    _require(len(rows) > 0, "empty specification")
    ops = AIG_OPS if basis == "aig" else B2_OPS
    pols = [rows[0]] if 0 in rows else [0, 1]
    stats = {"sat_calls": 0, "conflicts": 0, "unsat_proofs_checked": 0}

    def matches(gates, pol) -> bool:
        return all(simulate(n, gates, pol, t) == v for t, v in rows.items())

    # size 0: constant or a literal (free negation)
    for pol in (0, 1):
        if matches([], pol):
            return _result(n, basis, 0, [], pol, "trivial", stats, rows, input_wire=None)
    for j in range(n):
        for pol in (0, 1):
            if all(((t >> j) & 1) ^ pol == v for t, v in rows.items()):
                return _result(n, basis, 0, [], pol, "trivial", stats, rows, input_wire=j)
    minimality = "RUP-checked" if certify else "solver-reported"
    for k in range(1, max_gates + 1):
        best = None
        for pol in pols:
            target = {t: v ^ pol for t, v in rows.items()}
            nv, cl, X, F, SEL, R = _encode(n, target, k, ops)
            cl = cl + [[X[k - 1][t]] if target[t] else [-X[k - 1][t]] for t in R]
            if k > 1:
                for g in range(k - 1):
                    w = n + g
                    cl.append([o[0] for h in range(g + 1, k) for o in SEL[h] if o[1] == w or o[2] == w])
            s = CDCL(nv, cl, proof=certify)
            r = s.solve(conflict_limit=conflict_limit)
            stats["sat_calls"] += 1
            stats["conflicts"] += s.conflicts
            if r is None:
                minimality = "UNKNOWN(conflict_limit)"
                continue
            if r:
                _require(check_model(cl, s.model), "model fails CNF")
                gates = _decode(s.model, k, F, SEL)
                _require(matches(gates, pol), "decoded circuit fails the specification")
                best = (gates, pol)
                break
            if certify:
                _require(check_rup_proof(nv, cl, s.proof), f"RUP proof rejected at k={k}")
                stats["unsat_proofs_checked"] += 1
        if best is not None:
            return _result(n, basis, k, best[0], best[1], minimality, stats, rows)
    return {"n": n, "basis": basis, "size": None, "reason": f"no circuit with <= {max_gates} gates", "stats": stats}


def _result(n, basis, k, gates, pol, minimality, stats, rows, input_wire=None):
    return {
        "n": n,
        "basis": basis,
        "size": k,
        "gates": [[list(op), a, b] for op, a, b in gates],
        "output_polarity": pol,
        "input_wire": input_wire,
        "specified_rows": len(rows),
        "minimality": minimality,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# NPN orbit helpers for n = 3 tables
# ---------------------------------------------------------------------------
def npn_transforms(n: int):
    for perm in itertools.permutations(range(n)):
        for neg in range(1 << n):
            yield perm, neg


def apply_transform(n: int, tt: int, perm, neg: int, out_neg: int) -> int:
    out = 0
    for t in range(1 << n):
        src = 0
        for j in range(n):
            if ((t >> j) & 1) ^ ((neg >> j) & 1):
                src |= 1 << perm[j]
        if ((tt >> src) & 1) ^ out_neg:
            out |= 1 << t
    return out


def npn_canonical(n: int, tt: int) -> int:
    return min(apply_transform(n, tt, p, ng, o) for p, ng in npn_transforms(n) for o in (0, 1))


def full_table(n: int, basis: str, certify: bool = True) -> Dict[int, int]:
    reps: Dict[int, int] = {}
    table: Dict[int, int] = {}
    for tt in range(1 << (1 << n)):
        c = npn_canonical(n, tt)
        if c not in reps:
            reps[c] = int(synthesize(n, c, basis=basis, certify=certify)["size"])
        table[tt] = reps[c]
    return table


def bfs_b2_table3() -> Dict[int, int]:
    """Independent brute-force B2 sizes for all 256 3-input functions (free output
    negation): breadth-first over sets of wire tables, no SAT involved."""
    x = (0b10101010, 0b11001100, 0b11110000)
    M = 0xFF
    ops = [lambda a, b: a & b, lambda a, b: a & (~b & M), lambda a, b: (~a & M) & b,
           lambda a, b: a | b, lambda a, b: a ^ b]
    best: Dict[int, int] = {}

    def note(t: int, s: int) -> None:
        for u in (t, (~t) & M):
            if u not in best or best[u] > s:
                best[u] = s

    for t in (0,) + x:
        note(t, 0)
    frontier = {frozenset(x)}
    size = 0
    while len(best) < 256:
        size += 1
        _require(size <= 6, "B2 BFS exceeded 6 gates")
        nxt = set()
        last = len(best) >= 256
        for st in frontier:
            wires = sorted(st)
            for i in range(len(wires)):
                for j in range(i + 1, len(wires)):
                    for op in ops:
                        g = op(wires[i], wires[j])
                        if g not in best or best.get(g, 99) > size:
                            pass
                        note(g, size)
                        if g not in st:
                            nxt.add(st | {g})
        frontier = nxt
    return best
