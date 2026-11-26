"""
Upgraded PMLL Semantic Silo + Hot/Warm/Cold Tiering + Starlight Contract-Bound Q-Promises
=========================================================================================
Bridges `drQedwards/pmll` (`PMLL.c`, `Q_promise_lib/Q_promises.h`, `cuda_pmll.cu`,
`pmll-memory-mcp`) with Q-Forge's Fast Walsh-Hadamard Transform (`FWHT` FastJL) 128-bit
SimHash projection and Starlight/HAL contract-bound memoization.

Pure Python 3 stdlib implementation (zero external dependencies required; deterministic
across platforms and `-O` optimization levels).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from typing import Callable, Dict, Generic, List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")

TIER_COLD: int = 0
TIER_WARM: int = 1
TIER_HOT: int = 2

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")


def require(cond: bool, msg: str) -> None:
    """Optimizer-safe invariant check (never stripped under `python3 -O`)."""
    if not cond:
        raise RuntimeError(f"Invariant violation: {msg}")


def djb2_streaming_u32(token: str) -> int:
    """
    Continuous streaming djb2 hash over an arbitrary-length token (fixes `PMLL.c`'s
    63-character stack-buffer token-splitting bug).
    """
    h = 5381
    for b in token.lower().encode("utf-8"):
        h = (((h << 5) + h) + b) & 0xFFFFFFFF
    return h


def pmll_legacy_embed_32f(text: str) -> List[float]:
    """
    Faithful reference of original `PMLL.c::silo_embed_text`:
      - Splits tokens > 63 chars into separate chunks
      - Accumulates unsigned +1.0 counts into 32 float32 buckets (128 bytes/slot)
    Included strictly for regression and head-to-head collision benchmarking.
    """
    vec = [0.0] * 32
    for tok in TOKEN_RE.findall(text):
        for start in range(0, len(tok), 63):
            sub = tok[start : start + 63]
            vec[djb2_streaming_u32(sub) % 32] += 1.0
    norm2 = sum(v * v for v in vec)
    if norm2 > 1e-24:
        inv = 1.0 / math.sqrt(norm2)
        vec = [v * inv for v in vec]
    return vec


def fwht_inplace_pow2(buf: List[float]) -> None:
    """In-place Fast Walsh-Hadamard Transform in O(D log D) over len(buf) = 2^k."""
    n = len(buf)
    require(n > 0 and (n & (n - 1)) == 0, "FWHT length must be a positive power of two")
    h = 1
    while h < n:
        step = h << 1
        for i in range(0, n, step):
            for j in range(i, i + h):
                x = buf[j]
                y = buf[j + h]
                buf[j] = x + y
                buf[j + h] = x - y
        h = step


# Precomputed deterministic Rademacher diagonal D_r (256) and symmetric zero-tie dither (128)
_RADEMACHER_256: Tuple[float, ...] = tuple(
    -1.0 if (((i * 2654435761) & 0xFFFFFFFF) & 0x80000000) else 1.0
    for i in range(256)
)
_DITHER_128: Tuple[float, ...] = tuple(
    -1e-7 if (((i * 2246822519) & 0xFFFFFFFF) & 0x80000000) else 1e-7
    for i in range(128)
)


def qforge_fwht_simhash_128b(text: str) -> Tuple[int, int]:
    """
    Q-Forge Upgraded Semantic Sketch (`16 bytes` = `2 x uint64` vs `128 bytes` in `PMLL.c`):
      1. Streams full-length tokens into a 256-D Signed CountSketch (+/-1, zero positive bias).
      2. Applies deterministic Rademacher sign flip D_r + 256-point FWHT (FastJL).
      3. Quantizes top 128 coordinates into `(w0, w1)` 64-bit words.
    """
    sketch = [0.0] * 256
    for tok in TOKEN_RE.findall(text):
        h = djb2_streaming_u32(tok)
        bkt = h & 255
        sgn = -1.0 if ((h >> 8) & 1) else 1.0
        sketch[bkt] += sgn

    buf = [sketch[i] * _RADEMACHER_256[i] for i in range(256)]
    fwht_inplace_pow2(buf)

    w0 = 0
    w1 = 0
    for i in range(64):
        if buf[i] + _DITHER_128[i] > 0.0:
            w0 |= 1 << i
        if buf[64 + i] + _DITHER_128[64 + i] > 0.0:
            w1 |= 1 << i
    return w0, w1


def simhash_angular_cosine(sig_a: Tuple[int, int], sig_b: Tuple[int, int]) -> float:
    """Charikar angular similarity estimate via two `XOR + POPCNT` operations."""
    ham = (sig_a[0] ^ sig_b[0]).bit_count() + (sig_a[1] ^ sig_b[1]).bit_count()
    return math.cos(math.pi * ham / 128.0)


@dataclasses.dataclass
class SiloSlot:
    slot_idx: int
    key: str
    payload: str
    simhash_128: Tuple[int, int]
    salience: float = 0.5
    tier: int = TIER_WARM
    locked_hot: bool = False
    hits: int = 0
    resolved: bool = True


class UpgradedPMLLSilo:
    """
    Memory-safe, transactional Python counterpart to `PMLL.c` + `cuda_pmll_v2.cu`:
      - 16-byte FWHT SimHash semantic signatures (`8.0x` smaller than 32x float32)
      - 0-indexed segment-tree priority spine propagating cleanly all the way to `tree[0]`
      - Hot / Warm / Cold salience tiering with immediate `TIER_WARM` write promotion
        (preventing back-to-back double eviction in multi-insert batches)
    """

    def __init__(
        self,
        capacity: int = 256,
        k_hot: int = 32,
        k_warm: int = 96,
        decay_rate: float = 0.97,
        psi_alpha: float = 0.10,
    ) -> None:
        require(capacity > 0, "capacity must be positive")
        self.capacity = capacity
        self.k_hot = min(max(k_hot, 0), capacity)
        self.k_warm = min(max(k_warm, 0), max(0, capacity - self.k_hot))
        self.decay_rate = decay_rate
        self.psi_alpha = psi_alpha
        self.slots: List[Optional[SiloSlot]] = [None] * capacity
        self.key_to_slot: Dict[str, int] = {}
        self.tree: List[int] = [0] * (2 * capacity)
        self.slot_count: int = 0

    def propagate_backward(self, tree_idx: int, delta: int) -> None:
        """0-indexed parent `(idx - 1) // 2` propagation updating all ancestors including `tree[0]`."""
        require(0 <= tree_idx < len(self.tree), "tree_idx out of bounds")
        idx = tree_idx
        self.tree[idx] += delta
        while idx > 0:
            idx = (idx - 1) // 2
            self.tree[idx] += delta

    def _choose_victim_slot(self) -> int:
        # First prefer empty slots
        for idx, slot in enumerate(self.slots):
            if slot is None:
                return idx
        # Next prefer minimum-salience TIER_COLD unlocked slot (deterministic lowest-idx tie-break)
        best_cold: Optional[Tuple[float, int]] = None
        best_any: Optional[Tuple[float, int]] = None
        for idx, slot in enumerate(self.slots):
            assert slot is not None
            if slot.locked_hot:
                continue
            cand = (slot.salience, idx)
            if slot.tier == TIER_COLD:
                if best_cold is None or cand < best_cold:
                    best_cold = cand
            if best_any is None or cand < best_any:
                best_any = cand
        if best_cold is not None:
            return best_cold[1]
        if best_any is not None:
            return best_any[1]
        raise RuntimeError("All silo slots are locked TIER_HOT; cannot evict")

    def set(
        self,
        key: str,
        payload: str,
        reward: float = 0.6,
        lock_hot: bool = False,
    ) -> int:
        """Transactional insert/update with immediate TIER_WARM (or TIER_HOT) promotion."""
        require(bool(key), "key must be non-empty")
        sig = qforge_fwht_simhash_128b(f"{key} {payload}")
        init_sal = 1.0 if lock_hot else (0.25 + 0.75 * max(0.0, min(1.0, reward)))
        init_tier = TIER_HOT if lock_hot else TIER_WARM

        if key in self.key_to_slot:
            idx = self.key_to_slot[key]
            prev = self.slots[idx]
            require(prev is not None, "key_to_slot pointed to empty slot")
            self.slots[idx] = SiloSlot(
                slot_idx=idx,
                key=key,
                payload=payload,
                simhash_128=sig,
                salience=max(prev.salience, init_sal) if prev is not None else init_sal,
                tier=TIER_HOT if (lock_hot or (prev and prev.locked_hot)) else init_tier,
                locked_hot=bool(lock_hot or (prev and prev.locked_hot)),
                hits=(prev.hits + 1) if prev else 0,
                resolved=True,
            )
            self.propagate_backward(self.capacity - 1 + idx, 1)
            return idx

        idx = self._choose_victim_slot()
        old = self.slots[idx]
        if old is not None:
            self.key_to_slot.pop(old.key, None)
        else:
            self.slot_count += 1

        self.slots[idx] = SiloSlot(
            slot_idx=idx,
            key=key,
            payload=payload,
            simhash_128=sig,
            salience=init_sal,
            tier=init_tier,
            locked_hot=lock_hot,
            hits=0,
            resolved=True,
        )
        self.key_to_slot[key] = idx
        self.propagate_backward(self.capacity - 1 + idx, 1)
        return idx

    def peek(self, key: str) -> Optional[str]:
        """Exact O(1) key peek with salience reinforcement."""
        idx = self.key_to_slot.get(key)
        if idx is None:
            return None
        slot = self.slots[idx]
        if slot is None:
            return None
        slot.hits += 1
        if not slot.locked_hot:
            slot.salience = (1.0 - self.psi_alpha) * slot.salience + self.psi_alpha * 1.0
        self.propagate_backward(self.capacity - 1 + idx, 1)
        return slot.payload

    def peek_semantic(self, query: str, min_cosine: float = 0.20) -> Optional[Tuple[str, str, float]]:
        """Fast `XOR + POPCNT` semantic Top-1 retrieval across active slots."""
        q_sig = qforge_fwht_simhash_128b(query)
        best_score = -2.0
        best_slot: Optional[SiloSlot] = None
        for slot in self.slots:
            if slot is None:
                continue
            sim = simhash_angular_cosine(q_sig, slot.simhash_128)
            if sim > best_score:
                best_score = sim
                best_slot = slot
        if best_slot is not None and best_score >= min_cosine:
            best_slot.hits += 1
            return best_slot.key, best_slot.payload, best_score
        return None

    def step_decay_and_reclassify(self, rewards: Optional[Dict[str, float]] = None) -> Dict[str, int]:
        """Applies exponential salience decay + optional rewards and reclassifies Hot/Warm/Cold."""
        rewards = rewards or {}
        active: List[SiloSlot] = []
        for slot in self.slots:
            if slot is None:
                continue
            if slot.locked_hot:
                slot.salience = 1.0
                slot.tier = TIER_HOT
            else:
                r = rewards.get(slot.key, 0.0)
                s = slot.salience * self.decay_rate
                s = (1.0 - self.psi_alpha) * s + self.psi_alpha * r
                slot.salience = 0.0 if s < 0.001 else s
            active.append(slot)

        # Rank descending by salience, tie-broken by lowest slot_idx (matches `cuda_pmll_v2.cu`)
        ranked = sorted(active, key=lambda sl: (-sl.salience, sl.slot_idx))
        counts = {"hot": 0, "warm": 0, "cold": 0}
        for rank_idx, sl in enumerate(ranked):
            if sl.locked_hot or rank_idx < self.k_hot:
                sl.tier = TIER_HOT
                counts["hot"] += 1
            elif rank_idx < self.k_hot + self.k_warm:
                sl.tier = TIER_WARM
                counts["warm"] += 1
            else:
                sl.tier = TIER_COLD
                counts["cold"] += 1
        return counts


# ===========================================================================
# Starlight / HAL Contract-Bound Q-Promise Deduplication (`Q_promises.h` Bridge)
# ===========================================================================
@dataclasses.dataclass(frozen=True)
class StarlightContractKey:
    """
    Prevents the Q-Forge V119 wire-order / precision cache-collision bug by binding
    every execution contract attribute into the content-addressed Q-promise key.
    """

    domain: str
    canonical_payload: str
    wire_order: Tuple[int, ...] = ()
    symmetry_sector: str = "full"
    precision_mode: str = "exact_fraction"
    free_vram_reserve_mib: int = 1536

    def digest_hex(self) -> str:
        blob = json.dumps(
            {
                "domain": self.domain,
                "canonical_payload": self.canonical_payload,
                "wire_order": list(self.wire_order),
                "symmetry_sector": self.symmetry_sector,
                "precision_mode": self.precision_mode,
                "free_vram_reserve_mib": self.free_vram_reserve_mib,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def canonicalize_3xq_chart_orbit(mask_rows_3xq: Sequence[Sequence[int]]) -> str:
    """
    Canonicalizes a 3 x q binary chart mask under S_3 row permutations x S_q column
    permutations so symmetry-equivalent Grassmannian/Macaulay charts (`V170`-`V172`)
    deduplicate to a single Q-promise!
    """
    require(len(mask_rows_3xq) == 3, "Expected 3 rows for 3 x q chart")
    q = len(mask_rows_3xq[0])
    require(all(len(r) == q for r in mask_rows_3xq), "Inconsistent row widths in 3 x q chart")
    row_perms = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
    best: Optional[Tuple[Tuple[int, ...], ...]] = None
    for rp in row_perms:
        cols = sorted(
            (mask_rows_3xq[rp[0]][c], mask_rows_3xq[rp[1]][c], mask_rows_3xq[rp[2]][c])
            for c in range(q)
        )
        cand = tuple(cols)
        if best is None or cand < best:
            best = cand
    assert best is not None
    return json.dumps(best, separators=(",", ":"))


@dataclasses.dataclass
class QPromiseNode(Generic[T]):
    promise_id: str
    contract: StarlightContractKey
    resolved: bool = False
    value: Optional[T] = None
    dedup_hits: int = 0


class ContractBoundQPromiseRegistry:
    """
    Mirrors `Q_promise_lib/Q_promises.h` (`QMemNode` / `q_then`) backed by `UpgradedPMLLSilo`.
    """

    def __init__(self, silo: Optional[UpgradedPMLLSilo] = None) -> None:
        self.silo = silo or UpgradedPMLLSilo()
        self.nodes: Dict[str, QPromiseNode[object]] = {}
        self.compute_calls: int = 0
        self.cache_hits: int = 0

    def resolve_or_compute(
        self,
        contract: StarlightContractKey,
        compute_fn: Callable[[], T],
        lock_certified: bool = False,
    ) -> Tuple[T, bool]:
        """
        Returns `(result, was_cache_hit)`. Identical contracts reuse the resolved `QPromiseNode`
        without re-invoking `compute_fn`; mismatched wire_order or precision never collide.
        """
        pid = contract.digest_hex()
        existing = self.nodes.get(pid)
        if existing is not None and existing.resolved:
            existing.dedup_hits += 1
            self.cache_hits += 1
            self.silo.peek(pid)
            return existing.value, True  # type: ignore[return-value]

        self.compute_calls += 1
        val = compute_fn()
        node: QPromiseNode[object] = QPromiseNode(
            promise_id=pid,
            contract=contract,
            resolved=True,
            value=val,
            dedup_hits=0,
        )
        self.nodes[pid] = node
        self.silo.set(
            key=pid,
            payload=json.dumps({"domain": contract.domain, "summary": str(val)[:160]}),
            reward=1.0 if lock_certified else 0.7,
            lock_hot=lock_certified,
        )
        return val, False
