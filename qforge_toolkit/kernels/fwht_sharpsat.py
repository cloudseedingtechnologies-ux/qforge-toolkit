"""Exact integer Walsh-Hadamard #SAT for THR o XOR circuits, Charmander V174.

C(x) = [ sum_j ( <mask_j, x> xor flip_j ) >= k ]  over x in {0,1}^n.
S(x) = (m - W[x]) / 2 where W = FWHT of the signed spike vector
spec[mask_j] += (-1)^flip_j. One transform gives the whole histogram of S, so
the count for EVERY threshold (and =, <=) comes out at once.

Improvements over the V174 overlay version (same identity):
  * slice-based butterflies (fewer interpreter steps) and a full histogram;
  * explicit sign-rule and bit-order controls (MEMORY #41: Parseval alone
    does not pin a transform), checked against brute force;
  * masks outside n bits are refused instead of silently truncated.
This is the standard character-sum identity; it is not a new #SAT algorithm
and says nothing about general CNF #SAT.
"""
from __future__ import annotations

from typing import Dict, List, Sequence


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("FWHT_SHARPSAT_INVARIANT: " + msg)


def fwht_int(a: List[int]) -> List[int]:
    """Exact integer FWHT (natural/Hadamard order), returns a new list."""
    n = len(a)
    _require(n > 0 and (n & (n - 1)) == 0, "length must be a power of two")
    a = list(a)
    h = 1
    while h < n:
        step = h << 1
        for i in range(0, n, step):
            lo = a[i:i + h]
            hi = a[i + h:i + step]
            a[i:i + h] = [x + y for x, y in zip(lo, hi)]
            a[i + h:i + step] = [x - y for x, y in zip(lo, hi)]
        h = step
    return a


def parity_sum_histogram(n: int, masks: Sequence[int], flips: Sequence[int]) -> Dict[int, int]:
    _require(1 <= n <= 22, "n must be in 1..22")
    _require(len(masks) == len(flips), "masks/flips length mismatch")
    N = 1 << n
    spec = [0] * N
    for mk, fl in zip(masks, flips):
        _require(0 <= mk < N, f"mask {mk} has bits beyond n={n}")
        spec[mk] += -1 if (fl & 1) else 1
    W = fwht_int(spec)
    m = len(masks)
    hist: Dict[int, int] = {}
    for w in W:
        num = m - w
        _require(num % 2 == 0 and 0 <= num // 2 <= m, "Walsh parity identity violated")
        s = num // 2
        hist[s] = hist.get(s, 0) + 1
    _require(sum(hist.values()) == N, "histogram does not cover all inputs")
    return hist


def count_threshold(n: int, masks, flips, k: int) -> int:
    hist = parity_sum_histogram(n, masks, flips)
    return sum(c for s, c in hist.items() if s >= k)


def brute_histogram(n: int, masks, flips) -> Dict[int, int]:
    hist: Dict[int, int] = {}
    for x in range(1 << n):
        s = 0
        for mk, fl in zip(masks, flips):
            s += (bin(x & mk).count("1") ^ fl) & 1
        hist[s] = hist.get(s, 0) + 1
    return hist


def _mutant_hist(n, masks, flips, mode):
    N = 1 << n
    spec = [0] * N
    for mk, fl in zip(masks, flips):
        sign = -1 if (fl & 1) else 1
        if mode == "sign":
            sign = -sign
        spec[mk] += sign
    if mode == "or_order":
        # wrong transform: chi(i|j) style mixing (crew Walsh mutant)
        W = [sum(spec[j] * (-1 if bin(i | j).count("1") & 1 else 1) for j in range(N)) for i in range(N)]
    else:
        W = fwht_int(spec)
    m = len(masks)
    hist: Dict[int, int] = {}
    for w in W:
        s = (m - w) // 2
        hist[s] = hist.get(s, 0) + 1
    return hist


def demo_instance(n: int = 12, m: int = 64):
    masks = [((37 * (j + 1) * (j + 3) + 19) & ((1 << n) - 1)) | 1 for j in range(m)]
    flips = [(j * 7 + 3) & 1 for j in range(m)]
    return masks, flips


def run_suite() -> Dict[str, object]:
    n, m = 12, 64
    masks, flips = demo_instance(n, m)
    hist = parity_sum_histogram(n, masks, flips)
    brute = brute_histogram(n, masks, flips)
    _require(hist == brute, "FWHT histogram != brute force")
    k = 36
    count = sum(c for s, c in hist.items() if s >= k)
    # controls on a small instance (the OR-order mutant is O(N^2))
    n2, m2 = 6, 9
    mk2 = [5, 9, 17, 33, 3, 60, 1, 12, 41]
    fl2 = [0, 1, 0, 1, 1, 0, 0, 1, 0]
    ref = brute_histogram(n2, mk2, fl2)
    traps = {
        "T1_sign_rule_flip": _mutant_hist(n2, mk2, fl2, "sign") != ref,
        "T2_or_bit_order": _mutant_hist(n2, mk2, fl2, "or_order") != ref,
        "T3_count_tamper": (count + 1) != sum(c for s, c in brute.items() if s >= k),
    }
    try:
        parity_sum_histogram(4, [16], [0])
        traps["T4_out_of_range_mask_refused"] = False
    except RuntimeError:
        traps["T4_out_of_range_mask_refused"] = True
    _require(all(traps.values()), f"trap not caught: {traps}")
    return {
        "kernel": "CHARM-V174-FWHT-THR-XOR-SHARPSAT",
        "n_vars": n,
        "xor_gates": m,
        "threshold": k,
        "count_ge_threshold": count,
        "histogram": {str(s): c for s, c in sorted(hist.items())},
        "brute_force_match": True,
        "traps": traps,
        "claim": "Exact count for one THR o XOR instance, cross-checked by brute force; standard Walsh identity only.",
    }
