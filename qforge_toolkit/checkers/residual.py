"""Exact residual checks for a claimed eigenpair of a rational matrix.

The residual ratio is ||(A - λI)x|| / ||x||, returned as a square
(exact Fraction) so comparisons need no floating point. For a normal
or Hermitian matrix the residual disk theorem says at least one
eigenvalue lies in [λ - r, λ + r] where r is that ratio.
"""
from __future__ import annotations

from fractions import Fraction as Q
from typing import Iterable, Sequence


def _entry(value) -> Q:
    if type(value) is int or type(value) is Q:
        return Q(value)
    raise ValueError("not rational: " + type(value).__name__)


def _mat(matrix: Sequence[Sequence]) -> list[list[Q]]:
    work = [[_entry(v) for v in row] for row in matrix]
    if not work or any(len(row) != len(work) for row in work):
        raise ValueError("matrix must be square")
    return work


def _vec(vector: Iterable) -> list[Q]:
    out = [_entry(v) for v in vector]
    if not out:
        raise ValueError("vector must be nonempty")
    return out


def residual_vector(matrix, vector, eigenvalue) -> list[Q]:
    """Return (A - λI)x as a list of exact fractions."""
    A = _mat(matrix)
    x = _vec(vector)
    if len(x) != len(A):
        raise ValueError("dimension mismatch")
    lam = _entry(eigenvalue)
    out = []
    for i, row in enumerate(A):
        acc = -lam * x[i]
        for a, xi in zip(row, x):
            acc += a * xi
        out.append(acc)
    return out


def residual_ratio_sq(matrix, vector, eigenvalue) -> Q:
    """Return ||(A-λI)x||^2 / ||x||^2 as an exact Fraction."""
    x = _vec(vector)
    norm_sq = sum(xi * xi for xi in x)
    if norm_sq == 0:
        raise ValueError("zero vector")
    r = residual_vector(matrix, vector, eigenvalue)
    return sum(ri * ri for ri in r) / norm_sq


def residual_ratio(matrix, vector, eigenvalue) -> float:
    """Euclidean residual ratio, for display only. Comparisons should use residual_ratio_sq."""
    return float(residual_ratio_sq(matrix, vector, eigenvalue)) ** 0.5


def check_eigenpair(matrix, vector, eigenvalue, max_ratio_sq: Q | int = 0) -> dict:
    """Accept a claimed eigenpair when residual_ratio_sq <= max_ratio_sq (default: exact)."""
    cap = _entry(max_ratio_sq)
    if cap < 0:
        raise ValueError("max_ratio_sq must be nonnegative")
    ratio_sq = residual_ratio_sq(matrix, vector, eigenvalue)
    ok = ratio_sq <= cap
    return {
        "accepted": ok,
        "residual_ratio_sq": str(ratio_sq),
        "max_ratio_sq": str(cap),
        "reason": None if ok else "residual exceeds the allowed bound",
    }


def residual_disk(matrix, vector, eigenvalue) -> dict:
    """Return the residual disk [λ - r, λ + r] with r^2 exact.

    This is a genuine enclosure of some eigenvalue only for normal
    (including real-symmetric / Hermitian) matrices. The ``normal``
    flag is True when A A^T = A^T A over the rationals; otherwise the
    disk is reported as a residual measure, not a spectral enclosure.
    """
    A = _mat(matrix)
    n = len(A)
    AT = [[A[j][i] for j in range(n)] for i in range(n)]

    def mul(X, Y):
        return [
            [sum(X[i][k] * Y[k][j] for k in range(n)) for j in range(n)]
            for i in range(n)
        ]

    normal = mul(A, AT) == mul(AT, A)
    ratio_sq = residual_ratio_sq(matrix, vector, eigenvalue)
    lam = _entry(eigenvalue)
    return {
        "center": str(lam),
        "radius_sq": str(ratio_sq),
        "normal": normal,
        "encloses_an_eigenvalue": normal,
        "note": (
            "For a normal matrix, at least one eigenvalue lies in the disk "
            "of squared radius radius_sq about the claimed value."
            if normal
            else "Matrix is not normal; the disk is not a spectral enclosure."
        ),
    }
