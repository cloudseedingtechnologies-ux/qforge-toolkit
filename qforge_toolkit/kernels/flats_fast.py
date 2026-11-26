"""Fast exact enumeration of affine flats of F_2^n and the IP_2 monochromatic
flat audit, Charmander V174 improvement of the V174 overlay's pillar 5.

The overlay tests every subset of size 1,2,4,8,16 of F_2^4 for closure
(~13k subsets x up to 512 triple checks). Here flats are generated directly
as cosets v + span(B) of subspaces; results are identical (checked against
the slow method in tests) and the trap is a real checker rejection
(a planted non-flat 8-set and a planted monochromatic claim), not a constant.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List, Set


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError("FLATS_INVARIANT: " + msg)


def subspaces(n: int) -> List[FrozenSet[int]]:
    seen: Set[FrozenSet[int]] = {frozenset([0])}
    frontier = [frozenset([0])]
    while frontier:
        nxt = []
        for S in frontier:
            for v in range(1, 1 << n):
                if v in S:
                    continue
                T = frozenset(S | {s ^ v for s in S})
                if T not in seen:
                    seen.add(T)
                    nxt.append(T)
        frontier = nxt
    return sorted(seen, key=lambda s: (len(s), sorted(s)))


def affine_flats(n: int) -> List[FrozenSet[int]]:
    out: Set[FrozenSet[int]] = set()
    for S in subspaces(n):
        for v in range(1 << n):
            out.add(frozenset(s ^ v for s in S))
    return sorted(out, key=lambda s: (len(s), sorted(s)))


def is_flat(points) -> bool:
    P = set(points)
    if not P or (len(P) & (len(P) - 1)):
        return False
    return all((a ^ b ^ c) in P for a in P for b in P for c in P)


def ip2(v: int) -> int:
    return ((v & 1) & ((v >> 2) & 1)) ^ (((v >> 1) & 1) & ((v >> 3) & 1))


def audit_ip2() -> Dict[str, object]:
    subs = subspaces(4)
    flats = affine_flats(4)
    _require(len(subs) == 67 and len(flats) == 307, "F_2^4 flat counts wrong")
    _require(all(is_flat(f) for f in flats), "generated set is not a flat")
    max0 = max1 = tight4 = 0
    for f in flats:
        vals = {ip2(v) for v in f}
        if len(vals) == 1:
            if 0 in vals:
                max0 = max(max0, len(f))
                tight4 += len(f) == 4
            else:
                max1 = max(max1, len(f))
    return {
        "valid": max0 == 4 and max1 == 2,
        "f2_4_linear_subspaces": len(subs),
        "f2_4_nonempty_affine_flats": len(flats),
        "ip2_max_constant_0_flat_size": max0,
        "ip2_max_constant_1_flat_size": max1,
        "tight_size4_lagrangian_0_flats": tight4,
    }


def run_suite() -> Dict[str, object]:
    res = audit_ip2()
    _require(res["valid"], "IP_2 audit failed")
    zeros = [v for v in range(16) if ip2(v) == 0]
    traps = {
        "T1_planted_nonflat_8set_rejected": not is_flat(zeros[:8]),
        "T2_planted_size8_monochromatic_claim_rejected": not any(
            len(f) == 8 and len({ip2(v) for v in f}) == 1 for f in affine_flats(4)),
        "T3_size3_set_rejected": not is_flat([0, 1, 2]),
    }
    _require(all(traps.values()), f"trap not caught: {traps}")
    return {"kernel": "CHARM-V174-FLATS-IP2", **res, "traps": traps,
            "claim": "Exhaustive finite check on F_2^4 only."}
