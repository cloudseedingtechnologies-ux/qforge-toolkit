"""Determinantal-representation certificate checker, Charmander V174.

A certificate for dc(f) <= m is an m x m matrix of AFFINE-LINEAR forms whose
determinant equals f exactly. This module checks such certificates with exact
sparse integer/rational polynomial arithmetic (subset-DP Laplace expansion),
and builds Grenet's (2^n - 1) x (2^n - 1) certificate for the permanent
per_n as a worked example (n = 2, 3, 4).

Hook for DC(3,q)-style upper-bound certificates: check_certificate_json()
takes {"matrix": [[[[coef, var_or_null], ...], ...], ...], "target": [[coef, [vars...]], ...]}.
Only upper bounds are checked here; lower bounds (e.g. dc >= 2d-1 from
arXiv:2611.03554 Thm 4.1) are NOT computed by this module.
"""
from __future__ import annotations

import itertools
from fractions import Fraction
from typing import Dict, List, Sequence, Tuple

Mono = Tuple[str, ...]
Poly = Dict[Mono, Fraction]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("DETCERT_INVARIANT: " + msg)


def p_const(c) -> Poly:
    return {(): Fraction(c)} if c else {}


def p_var(v: str, c=1) -> Poly:
    return {(v,): Fraction(c)}


def p_add(a: Poly, b: Poly, sign: int = 1) -> Poly:
    out = dict(a)
    for m, c in b.items():
        v = out.get(m, 0) + sign * c
        if v:
            out[m] = v
        else:
            out.pop(m, None)
    return out


def p_mul(a: Poly, b: Poly) -> Poly:
    out: Poly = {}
    for m1, c1 in a.items():
        for m2, c2 in b.items():
            m = tuple(sorted(m1 + m2))
            v = out.get(m, 0) + c1 * c2
            if v:
                out[m] = v
            else:
                out.pop(m, None)
    return out


def degree(p: Poly) -> int:
    return max((len(m) for m in p), default=0)


def det(M: Sequence[Sequence[Poly]]) -> Poly:
    m = len(M)
    _require(all(len(r) == m for r in M), "matrix not square")
    memo: Dict[int, Poly] = {}

    def rec(row: int, used: int) -> Poly:
        if row == m:
            return p_const(1)
        if used in memo:
            return memo[used]
        acc: Poly = {}
        free_idx = 0
        for col in range(m):
            if used >> col & 1:
                continue
            e = M[row][col]
            if e:
                sub = rec(row + 1, used | (1 << col))
                if sub:
                    term = p_mul(e, sub)
                    acc = p_add(acc, term, -1 if free_idx % 2 else 1)
            free_idx += 1
        memo[used] = acc
        return acc

    return rec(0, 0)


def check_certificate(M: Sequence[Sequence[Poly]], f: Poly) -> Dict[str, object]:
    maxdeg = max((degree(e) for r in M for e in r), default=0)
    if maxdeg > 1:
        return {"ok": False, "reason": "entry is not affine-linear", "max_entry_degree": maxdeg}
    D = det(M)
    ok = D == {k: Fraction(v) for k, v in f.items() if v}
    return {"ok": ok, "size": len(M), "max_entry_degree": maxdeg, "det_terms": len(D),
            "reason": "det(M) == f exactly" if ok else "det(M) != f"}


def check_certificate_json(obj) -> Dict[str, object]:
    M = []
    for row in obj["matrix"]:
        r = []
        for entry in row:
            p: Poly = {}
            for coef, var in entry:
                p = p_add(p, p_const(Fraction(coef)) if var is None else p_var(var, Fraction(coef)))
            r.append(p)
        M.append(r)
    f: Poly = {}
    for coef, vars_ in obj["target"]:
        f = p_add(f, {tuple(sorted(vars_)): Fraction(coef)})
    return check_certificate(M, f)


def permanent_poly(n: int) -> Poly:
    f: Poly = {}
    for s in itertools.permutations(range(n)):
        f = p_add(f, {tuple(sorted(f"x{i}{s[i]}" for i in range(n))): Fraction(1)})
    return f


def determinant_poly(n: int) -> Poly:
    f: Poly = {}
    for s in itertools.permutations(range(n)):
        inv = sum(1 for i in range(n) for j in range(i + 1, n) if s[i] > s[j])
        f = p_add(f, {tuple(sorted(f"x{i}{s[i]}" for i in range(n))): Fraction(-1 if inv % 2 else 1)})
    return f


def grenet_matrix(n: int) -> List[List[Poly]]:
    """Grenet (2011): ABP on subsets of [n]; source {} and sink [n] merged."""
    full = (1 << n) - 1
    verts = [0] + [S for S in range(1, full)]  # index 0 = merged {} / [n]
    idx = {S: i for i, S in enumerate(verts)}
    m = len(verts)
    M: List[List[Poly]] = [[{} for _ in range(m)] for _ in range(m)]
    for i in range(1, m):
        M[i][i] = p_const(1)
    for S in range(0, full):
        row = bin(S).count("1")  # next row of the matrix X to use
        for j in range(n):
            if S >> j & 1:
                continue
            T = S | (1 << j)
            u = idx[S] if S != 0 else 0
            v = 0 if T == full else idx[T]
            # entry (v,u) so that cycles read rows in order; sign fixed below
            M[v][u] = p_add(M[v][u], p_var(f"x{row}{j}"))
    D = det(M)
    target = permanent_poly(n)
    if D != target:
        neg = {k: -c for k, c in D.items()}
        _require(neg == target, "Grenet construction does not give +-per_n")
        M[0] = [{k: -c for k, c in e.items()} for e in M[0]]
    return M


def run_suite() -> Dict[str, object]:
    rows = []
    for n in (2, 3, 4):
        M = grenet_matrix(n)
        res = check_certificate(M, permanent_poly(n))
        _require(res["ok"], f"Grenet per_{n} certificate rejected")
        rows.append({"target": f"per_{n}", "certificate_size": res["size"], "det_terms": res["det_terms"], "ok": True})
    M3 = grenet_matrix(3)
    traps = {}
    bad = [list(r) for r in M3]
    bad[1] = list(bad[1])
    bad[1][1] = p_const(2)
    traps["T1_tampered_entry_rejected"] = not check_certificate(bad, permanent_poly(3))["ok"]
    sq = [list(r) for r in M3]
    sq[2] = list(sq[2])
    sq[2][2] = p_mul(p_var("x00"), p_var("x11"))
    traps["T2_nonaffine_entry_rejected"] = not check_certificate(sq, permanent_poly(3))["ok"]
    traps["T3_det_vs_per_confusion_rejected"] = not check_certificate(M3, determinant_poly(3))["ok"]
    js = {"matrix": [[[[1, "a"]], [[1, "b"]]], [[[-1, "c"]], [[1, "d"]]]], "target": [[1, ["a", "d"]], [1, ["b", "c"]]]}
    traps["T4_json_hook_accepts_per2"] = check_certificate_json(js)["ok"]
    _require(all(traps.values()), f"trap not caught: {traps}")
    return {"kernel": "CHARM-V174-DETCERT", "grenet_rows": rows, "traps": traps,
            "claim": "Exact checks of Grenet upper-bound certificates dc(per_n) <= 2^n - 1 for n = 2, 3, 4; a known construction, replayed."}
