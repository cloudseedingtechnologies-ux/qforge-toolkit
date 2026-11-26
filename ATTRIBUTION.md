# Attribution

This repository includes portable lab infrastructure written for the Q-Forge
toolkit, plus independently replayed modules contributed by the
**Constellation crew** (generic credit; individual operator names are not
recorded here) and work that builds on the public science of
**Dr. Josef "Q" Edwards (`@drQedwards`)**.

## Upstream projects (read, cited, not vendored)

1. [`drQedwards/pmll`](https://github.com/drQedwards/pmll) — Persistent Memory
   Logic Loop (`PMLL.c`, `PMLL.h`), Q-promise continuations
   (`Q_promise_lib/Q_promises.h`), native SAT (`SAT.c`), GPU salience notes
   (`cuda_pmll.cu`, `Tiered_topk.patch`), GF(2) XOR-SAT (`xor_sat.py`,
   `docs/XOR_SAT.md`), and RFC 6962 proof-manifest design
   (`docs/SAT-PROOF-MANIFEST.md`, `pmll-anchor`).
   **Note:** the Farkas dual certificate helper in `qforge_pmll` is a toolkit
   *extension*; it is not already present in upstream `pmll` (which does ship
   `xor_sat.py`).
2. [`drQedwards/ERS`](https://github.com/drQedwards/ERS) — Enhanced
   Reconsideration System (`MemoryBlock`, `ERSPromise`, `reconsider_memory`,
   `detect_contradiction`, `PMLLLattice`). The certificate-gated reconsider
   helper in `qforge_pmll` wraps those ideas with exact, finite checks; it is
   not a claim that upstream ERS already emits machine-checked proofs.
3. [`drQedwards/PPM`](https://github.com/drQedwards/PPM) and
   [`pmll-memory-mcp`](https://pypi.org/project/pmll-memory-mcp/) — memory
   graph + decay routing (`upsert_memory_node`, `create_memory_relation`).
   Optional credit also to Context+ (`@ForLoopCodes`) as listed in the crew
   kit's own attribution.

## Constellation crew modules merged after independent replay

See `ORIGIN_PINNED.json` for per-file SHA-256 pins. In summary:

- `qforge_pmll/` — FWHT SimHash silo, contract-bound Q-promises, GF(2) Farkas
  decoder, ERS certificate-gated reconsider, RFC 6962 Merkle + hygiene scan.
- `c_core/` — C11 silo tokenizer / VSIDS+LBD+DRUP SAT upgrades, Woodbury–Rump
  numeric helper.
- `cuda/cuda_pmll_v2.cu` — `sm_86` tiered-salience kernel. Compiled and run
  under one registered GPU lease during intake; the kernel's self-report is
  not an independent numerical proof.
- `cuda/j1j2_otf_prefix_kernels.cu` and
  `cuda/v168_shor_cyclic_kickmix_sm86.cu` — research kernels. The V168 file is
  a *classical Shor-phase simulator* (`QPU=false`); no quantum credit.
- `scripts/verify_pmll_gates.py` — crew 10-gate / 8-mutant verifier, path-
  adjusted. Independently re-run (normal and `python -O`) plus a second
  checker with freshly planted mutants.
- `tools/` — `circ_check.py`, `model_adapter.py`, `r1_scan_and_stmt_eq.py`,
  `guarded_run.py`, from earlier Constellation-crew / lab staging (not from
  the v173 zip itself).
- `contrib/neptune_pmll/` — earlier V166/V170 audit and sync engines taken
  from the 2026-11-26 Neptune Elysium Prime zip after their own stdlib
  self-tests passed under normal and `-O`. They are historical reference
  implementations, not a second source of truth. The rest of that zip (UI
  cockpit, radio/SDR, install scripts, "millennium solver" artifacts) was
  **not** merged.

## Honesty labels

Every receipt in this tree must keep `"FINITE_EXPERIMENT": true` and
`"clay_proof": 0`. Size ratios (for example 128 B / 16 B = 8.0× RAM) are not
runtime speedups. Collision-bias figures are fixture-dependent finite
experiments; directional improvement of the FWHT silo versus the unsigned
legacy embed was independently confirmed, exact published factors were not
treated as ADOPT. Lean 4.36 input shipped in the v173 kit did **not** pass
`lean436-check.sh` (official `rc=0` only): eight earlier identities compiled
with standard axioms, the last declaration failed `ring` and depended on
`sorryAx`. That Lean file is not shipped here.

Nothing in this repository is a proof of an open problem, a physical QPU
result, or an RSA-breaking claim.
