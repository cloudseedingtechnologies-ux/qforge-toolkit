"""Temple's inequality for a certified lower bound on an isolated eigenvalue.

If μ is the Rayleigh quotient of a nonzero vector x, r = ||(A-μI)x|| / ||x||,
and ζ > μ is a lower bound on the next eigenvalue above μ, then the
eigenvalue λ in (-∞, ζ) nearest to μ satisfies

    λ  >=  μ - r^2 / (ζ - μ).

All inputs are exact rationals. The bound is refused when ζ <= μ, when x is
zero, or when a claimed lower bound is tighter than Temple allows.
"""
from __future__ import annotations

from fractions import Fraction as Q

from .residual import _entry, _mat, _vec, residual_ratio_sq


def rayleigh(matrix, vector) -> Q:
    """Return x^T A x / x^T x as an exact Fraction."""
    A = _mat(matrix)
    x = _vec(vector)
    if len(x) != len(A):
        raise ValueError("dimension mismatch")
    num = Q(0)
    den = Q(0)
    for i, xi in enumerate(x):
        den += xi * xi
        acc = Q(0)
        for a, xj in zip(A[i], x):
            acc += a * xj
        num += xi * acc
    if den == 0:
        raise ValueError("zero vector")
    return num / den


def temple_lower_bound(mu, residual_sq, zeta) -> Q:
    """Return μ - r^2 / (ζ - μ). residual_sq is r^2, already squared."""
    mu = _entry(mu)
    residual_sq = _entry(residual_sq)
    zeta = _entry(zeta)
    if residual_sq < 0:
        raise ValueError("residual_sq must be nonnegative")
    if zeta <= mu:
        raise ValueError("Temple bound requires zeta > mu")
    return mu - residual_sq / (zeta - mu)


def check_temple_enclosure(matrix, vector, zeta, claimed_lo) -> dict:
    """Accept claimed_lo only if it is <= the Temple lower bound for (A, x, ζ).

    The Rayleigh quotient μ is computed from (A, x). ζ must be strictly
    larger than μ. A claimed lower bound above the Temple value is refused.
    """
    mu = rayleigh(matrix, vector)
    rsq = residual_ratio_sq(matrix, vector, mu)
    try:
        lo = temple_lower_bound(mu, rsq, zeta)
    except ValueError as exc:
        return {"accepted": False, "reason": str(exc), "mu": str(mu), "residual_sq": str(rsq)}
    claimed = _entry(claimed_lo)
    ok = claimed <= lo
    return {
        "accepted": ok,
        "mu": str(mu),
        "residual_sq": str(rsq),
        "zeta": str(_entry(zeta)),
        "temple_lo": str(lo),
        "claimed_lo": str(claimed),
        "reason": None if ok else "claimed lower bound is tighter than Temple allows",
    }
