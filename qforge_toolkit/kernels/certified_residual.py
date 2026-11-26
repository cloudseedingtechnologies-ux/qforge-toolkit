"""Certified-residual linear solver (V151/V152 idea), Charmander V174.

Solve A x = b for a symmetric positive-definite rational matrix A:
  1. fast float conjugate gradient gives x_f;
  2. x_f is converted EXACTLY to rationals (Fraction(float) is exact);
  3. r = b - A x_f is computed in exact rational arithmetic;
  4. a lower bound sigma <= lambda_min(A) is certified by an exact LDL^T of
     A - sigma*I with all pivots > 0 (Sylvester's law of inertia);
  5. then ||x_f - x*||_2 <= ||r||_2 / sigma, an exact rational bound.
The symmetry check is exact (MEMORY #40: a residual disk needs the right
adjoint/symmetry test). Mixed-precision refinement repeats steps 1-3 on r.
Everything is exact except step 1, whose error is what gets bounded.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, List, Sequence

Matrix = List[List[Fraction]]


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("CERT_RESIDUAL_INVARIANT: " + msg)


def as_fraction_matrix(A: Sequence[Sequence]) -> Matrix:
    return [[Fraction(v) for v in row] for row in A]


def is_symmetric(A: Matrix) -> bool:
    n = len(A)
    return all(len(r) == n for r in A) and all(A[i][j] == A[j][i] for i in range(n) for j in range(i + 1, n))


def ldl_pivots(A: Matrix, shift: Fraction) -> List[Fraction]:
    """Exact LDL^T pivots of A - shift*I (no pivoting); stops at the first pivot <= 0."""
    n = len(A)
    M = [[A[i][j] - (shift if i == j else 0) for j in range(n)] for i in range(n)]
    piv: List[Fraction] = []
    for k in range(n):
        d = M[k][k]
        piv.append(d)
        if d <= 0:
            return piv
        for i in range(k + 1, n):
            if M[i][k] == 0:
                continue
            f = M[i][k] / d
            row_k = M[k]
            row_i = M[i]
            for j in range(k + 1, n):
                if row_k[j]:
                    row_i[j] -= f * row_k[j]
    return piv


def certify_lambda_min_lower(A: Matrix, sigma: Fraction) -> bool:
    piv = ldl_pivots(A, sigma)
    return len(piv) == len(A) and all(p > 0 for p in piv)


def cg_float(A: Sequence[Sequence[float]], b: Sequence[float], tol: float = 1e-13, maxit: int = 10000) -> List[float]:
    n = len(b)
    x = [0.0] * n
    r = list(b)
    p = list(r)
    rr = sum(v * v for v in r)
    bnorm = max(rr ** 0.5, 1e-300)
    for _ in range(maxit):
        if rr ** 0.5 <= tol * bnorm:
            break
        Ap = [sum(A[i][j] * p[j] for j in range(n)) for i in range(n)]
        pAp = sum(p[i] * Ap[i] for i in range(n))
        if pAp <= 0:
            break
        alpha = rr / pAp
        x = [x[i] + alpha * p[i] for i in range(n)]
        r = [r[i] - alpha * Ap[i] for i in range(n)]
        rr_new = sum(v * v for v in r)
        p = [r[i] + (rr_new / rr) * p[i] for i in range(n)]
        rr = rr_new
    return x


def exact_residual(A: Matrix, b: Sequence[Fraction], x: Sequence[Fraction]) -> List[Fraction]:
    n = len(A)
    return [b[i] - sum(A[i][j] * x[j] for j in range(n) if A[i][j]) for i in range(n)]


def solve_certified(A_in, b_in, sigma=None, refinements: int = 2) -> Dict[str, object]:
    A = as_fraction_matrix(A_in)
    b = [Fraction(v) for v in b_in]
    n = len(A)
    _require(n >= 1 and len(b) == n, "shape mismatch")
    _require(is_symmetric(A), "matrix is not exactly symmetric (refusing a symmetric-only bound)")
    Af = [[float(v) for v in row] for row in A]
    if sigma is None:
        # cheap guess: Gershgorin lower edge if positive, else halve until certified
        g = min(A[i][i] - sum(abs(A[i][j]) for j in range(n) if j != i) for i in range(n))
        sigma = g if g > 0 else Fraction(1, 2) * min(A[i][i] for i in range(n))
        tries = 0
        while not certify_lambda_min_lower(A, sigma):
            sigma /= 4
            tries += 1
            _require(tries < 60, "could not certify a positive lambda_min lower bound (not SPD?)")
    sigma = Fraction(sigma)
    _require(sigma > 0, "sigma must be positive")
    _require(certify_lambda_min_lower(A, sigma), "sigma is not a certified lambda_min lower bound")
    x = [Fraction(v) for v in cg_float(Af, [float(v) for v in b])]
    history = []
    for it in range(refinements + 1):
        r = exact_residual(A, b, x)
        rn2 = sum(v * v for v in r)
        bound2 = rn2 / (sigma * sigma)
        history.append(float(bound2) ** 0.5)
        if it == refinements or rn2 == 0:
            break
        d = cg_float(Af, [float(v) for v in r])
        x = [x[i] + Fraction(d[i]) for i in range(n)]
    return {
        "n": n,
        "sigma_certified": str(sigma),
        "residual_norm2_sq": rn2,
        "error_bound_sq": bound2,
        "error_bound_float_upper": _float_up(bound2) ** 0.5 * (1 + 2 ** -50),
        "bound_history": history,
        "x": x,
    }


def _float_up(q: Fraction) -> float:
    f = float(q)
    while Fraction(f) < q:
        f = f + abs(f) * 2 ** -52 + 5e-324
    return f


def laplacian_1d(n: int) -> Matrix:
    return [[Fraction(2) if i == j else Fraction(-1) if abs(i - j) == 1 else Fraction(0) for j in range(n)] for i in range(n)]


def hilbert_shifted(n: int) -> Matrix:
    return [[Fraction(1, i + j + 1) + (Fraction(1) if i == j else 0) for j in range(n)] for i in range(n)]


def exact_solve(A: Matrix, b: Sequence[Fraction]) -> List[Fraction]:
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        p = next(r for r in range(c, n) if M[r][c] != 0)
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c and M[r][c] != 0:
                f = M[r][c] / M[c][c]
                M[r] = [M[r][j] - f * M[c][j] for j in range(n + 1)]
    return [M[i][n] / M[i][i] for i in range(n)]


def run_suite() -> Dict[str, object]:
    cases = []
    for name, A in (("laplacian_1d_24", laplacian_1d(24)), ("hilbert_plus_I_12", hilbert_shifted(12))):
        n = len(A)
        b = [Fraction((7 * i + 3) % 11 - 5, 1 + (i % 3)) for i in range(n)]
        res = solve_certified(A, b)
        xs = exact_solve(A, b)
        err2 = sum((res["x"][i] - xs[i]) ** 2 for i in range(n))
        _require(err2 <= res["error_bound_sq"], f"{name}: true error exceeds certified bound")
        cases.append({
            "case": name,
            "sigma_certified": res["sigma_certified"],
            "certified_error_bound": res["error_bound_float_upper"],
            "true_error_exact_check": float(err2) ** 0.5,
            "bound_holds_exactly": True,
            "bound_history": res["bound_history"],
        })
    A = laplacian_1d(10)
    b = [Fraction(1)] * 10
    traps = {}
    # T1: non-symmetric matrix refused
    An = [row[:] for row in A]
    An[0][1] = Fraction(-2)
    try:
        solve_certified(An, b)
        traps["T1_nonsymmetric_refused"] = False
    except RuntimeError:
        traps["T1_nonsymmetric_refused"] = True
    # T2: overstated sigma (above lambda_min) refused
    lam_min_true = 2 - 2 * __import__("math").cos(__import__("math").pi / 11)
    try:
        solve_certified(A, b, sigma=Fraction(lam_min_true) * Fraction(11, 10))
        traps["T2_overstated_sigma_refused"] = False
    except RuntimeError:
        traps["T2_overstated_sigma_refused"] = True
    # T3: tampered solution breaks the bound against the exact solution
    res = solve_certified(A, b)
    xs = exact_solve(A, b)
    xt = list(res["x"])
    xt[3] += Fraction(1, 1000)
    rt = exact_residual(A, b, xt)
    bound_t = sum(v * v for v in rt) / (Fraction(res["sigma_certified"]) ** 2)
    err_t = sum((xt[i] - xs[i]) ** 2 for i in range(10))
    traps["T3_tamper_detected_by_residual"] = bound_t > res["error_bound_sq"] and err_t <= bound_t
    # T4: indefinite matrix refused
    Ai = [row[:] for row in A]
    Ai[5][5] = Fraction(-3)
    try:
        solve_certified(Ai, b)
        traps["T4_indefinite_refused"] = False
    except RuntimeError:
        traps["T4_indefinite_refused"] = True
    _require(all(traps.values()), f"trap not caught: {traps}")
    return {
        "kernel": "CHARM-V174-CERTIFIED-RESIDUAL-CG",
        "cases": cases,
        "traps": traps,
        "claim": "Exact rational error bounds for float CG solutions on two SPD test matrices; each bound was checked against an exact solve.",
    }
