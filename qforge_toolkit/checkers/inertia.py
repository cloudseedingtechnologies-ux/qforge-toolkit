"""Exact inertia (n_plus, n_minus, n_zero) of a symmetric rational matrix.

Uses LDL-style elimination with 1-by-1 diagonal pivots, or a 2-by-2 block
[[0, a], [a, 0]] when every remaining diagonal is zero. Sylvester's law of
inertia makes the signature independent of pivot order. Callers that seal a
count should require the "first" and "last" policies to agree.

Only exact ints and fractions are accepted. Floats, decimals, bools and
non-symmetric inputs are refused.
"""
from __future__ import annotations

from fractions import Fraction as Q


def _entry(value) -> Q:
    if type(value) is int or type(value) is Q:
        return Q(value)
    raise ValueError("not rational: " + type(value).__name__)


def inertia(matrix, shift=0, policy: str = "first") -> tuple[int, int, int]:
    """Return (n_plus, n_minus, n_zero) of matrix - shift * I."""
    if policy not in ("first", "last"):
        raise ValueError("policy")
    shift = _entry(shift)
    work = [[_entry(value) for value in row] for row in matrix]
    size = len(work)
    if any(len(row) != size for row in work):
        raise ValueError("not symmetric")
    if any(work[i][j] != work[j][i] for i in range(size) for j in range(size)):
        raise ValueError("not symmetric")
    for i in range(size):
        work[i][i] -= shift
    positive = negative = 0
    pending = list(range(size))
    while pending:
        diagonal = [i for i in pending if work[i][i] != 0]
        if policy == "last":
            diagonal.reverse()
        if diagonal:
            pivot = diagonal[0]
            scale = work[pivot][pivot]
            positive += scale > 0
            negative += scale < 0
            rest = [i for i in pending if i != pivot]
            for i in rest:
                factor = work[i][pivot] / scale
                if factor:
                    for j in rest:
                        work[i][j] -= factor * work[pivot][j]
            pending = rest
            continue
        pairs = [(i, j) for i in pending for j in pending if i < j and work[i][j] != 0]
        if policy == "last":
            pairs.reverse()
        if not pairs:
            break
        i, j = pairs[0]
        off = work[i][j]
        positive += 1
        negative += 1
        rest = [k for k in pending if k not in (i, j)]
        for k in rest:
            for col in rest:
                work[k][col] -= (work[k][i] * work[j][col] + work[k][j] * work[i][col]) / off
        pending = rest
    return int(positive), int(negative), int(size - positive - negative)


def check_inertia(matrix, claimed, shift=0) -> dict:
    """Accept a claimed (n_plus, n_minus, n_zero) only if both pivot policies agree and match."""
    first = inertia(matrix, shift=shift, policy="first")
    last = inertia(matrix, shift=shift, policy="last")
    claimed_t = tuple(int(x) for x in claimed)
    ok = first == last == claimed_t
    return {
        "accepted": ok,
        "first": first,
        "last": last,
        "claimed": claimed_t,
        "reason": None if ok else "claimed inertia does not match both pivot policies",
    }
