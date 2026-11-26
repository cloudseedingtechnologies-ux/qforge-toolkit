# qforge-toolkit

A small, reusable toolkit for keeping research claims honest and for handing
those claims to a persistent-memory loop.

It is meant to be easy to drop next to [Dr. Q Edwards' PMLL](https://github.com/drQedwards/PPM)
(`pmll-memory-mcp`). Nothing here talks to a network on its own. Nothing here
is a proof of an open problem.

## What is in the box

| Tool | What it does |
| --- | --- |
| **Claim linter** | Flags unbounded strength words ("proves", "certified", "quantum advantage") in prose or in a receipt's `claim` field, unless the same sentence limits the claim. |
| **Task cards + receipts + ledger** | A card states a question, a ceiling, a falsifier and at least one planted error. A receipt hashes the deterministic body (timings and host names live in an unhashed `runtime` section). The ledger re-checks hashes and sidecars and marks receipts SAME, NEW, REFRESHED, STALE or INVALID. |
| **Speed gate** | ADOPT only if the candidate is exact, the timings cover the complete task, both sides used the same thread count, there are at least three paired repeats, and the median is at least 10% faster. Otherwise STAGE, or REJECT if it is not exact. |
| **Exact residual checker** | `||(A-λI)x||^2 / ||x||^2` as a rational. Residual disks enclose an eigenvalue only when the matrix is normal. |
| **Temple checker** | Given a Rayleigh quotient μ, residual r, and a lower bound ζ > μ on the next eigenvalue, the Temple lower bound is μ − r²/(ζ − μ). A tighter claimed bound is refused. |
| **Inertia checker** | Exact Sylvester inertia of a symmetric rational matrix, via LDL with 1-by-1 and 2-by-2 pivots. Both pivot orders must agree before a claimed count is accepted. |
| **Lab index** | Builds and validates a small index of seals, cards and open problems, with flocked writes and re-hashed seal files. |
| **Seal and receipt** | Copies a tree, replaces home prefixes with `~`, leak-scans for private keys and common token shapes, writes MANIFEST and SHA256SUMS, packs a size-capped archive, and receipts a *fresh* extract. Deliveries refuse to overwrite. No `rm`, no shared `/tmp`. |
| **Journal** | One flocked, fsync'd JSON line per event, plus a short resume report. |
| **Host guard** | Pause when MemAvailable is low or swap activity is high. Thresholds are configurable. A caller may only kill its own process if that process is swapping. |
| **GPU lease** | One registered VRAM lease at a time, in a flocked table, with a reserve margin (default 1536 MiB). Nested leases are refused. The wrapper script also applies a memory scope and the host guard. |
| **Lean check script** | Compiles a Lean file with an *isolated* 4.36 toolchain that you already have (never installs into `~/.elan`), prints axioms, and runs a second kernel (`nanoda_bin`) with positive and negative controls. |
| **PMLL export** | Turns a `MEMORY.md` file and a `lab_index.json` into long-term graph nodes and relations, plus short-term key/content pairs, in the schema `pmll-memory-mcp` uses. |

A larger in-house algorithm catalog exists behind this toolkit and is not
shipped here. This repository is the portable infrastructure layer.

## Quick start

See [QUICKSTART.md](QUICKSTART.md). In short:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
python -m qforge_toolkit claim-lint samples/MEMORY.md
python -m pmll.pmll_export --memory samples/MEMORY.md --index samples/lab_index.json --out samples/exported_graph.json
```

## PMLL bridge

`pmll/pmll_export.py` reads the sample memory file and lab index (or your own
scrubbed copies) and writes a graph that matches the SQLite tables and tool
arguments in [`pmll_memory_mcp`](https://github.com/drQedwards/PPM/tree/main/mcp/pmll_memory_mcp):

- long-term: `upsert_memory_node` / `create_memory_relation`
  (aliases: `create_memory_node`, `create_relation`)
- short-term silo: `set(session_id, key, value)`
- `nodes` / `edges` lists are the shape `memory_graph.import_graph` expects

The sample export is generic on purpose: it describes the tools, not anyone's
private lab notes. See [pmll/SCHEMA.md](pmll/SCHEMA.md).


## Exact kernels K1–K7 (`qforge_toolkit.kernels`)

Pure standard-library Python. Every kernel checks itself against an independent
reference and ships planted-error traps; the suite receipt hashes only
deterministic fields, so it is identical under `python` and `python -O`
(tested in `tests/test_kernels.py` and in CI).

| Kernel | Module | Independent check |
| --- | --- | --- |
| K1 exact circuit synthesis (MCSP and partial-function MCSP*) | `exact_synth`, `cdcl` | SAT answers re-simulated; every smaller size refuted by a RUP proof checked by `cdcl.check_rup_proof`; full 3-input B2 table equals a separate BFS |
| K2 exact #SAT for THR∘XOR by integer Walsh–Hadamard | `fwht_sharpsat` | brute force; sign-rule and bit-order traps |
| K3 conjugate gradient with certified error bound ‖x−x*‖ ≤ ‖r‖/σ | `certified_residual` | σ certified by an exact LDLᵀ of A−σI; exact symmetry check |
| K4 light-cone closure for Z / ZZ | `lightcone` | exact equality with a dense simulator (rational orthogonal gates) |
| K5 determinantal-representation certificates | `detcert` | Grenet per₂–per₄ checked by exact Laplace expansion of the determinant |
| K6 random 3-SAT sweep | `sat_phase` | models checked, UNSAT answers RUP-checked |
| K7 affine flats in GF(2)ⁿ | `flats_fast` | slow subset enumeration |

```bash
python -m qforge_toolkit kernels suite   # full receipt JSON (~10 s)
python -m qforge_toolkit kernels quick   # skip the full 256-function tables
python -m qforge_toolkit speedgate spec.json   # ADOPT / STAGE / REJECT a paired timing spec
```

Single-thread races recorded at intake (median of 3 pairs, complete task):
SAT+RUP table vs BFS 0.758 (ADOPT), FWHT vs brute force 0.033 (ADOPT), flats 0.276 (ADOPT),
light cone vs full simulation 0.005 (ADOPT); a slice-FWHT variant was 1.61× slower (STAGE, kept for record only).
These are finite experiments; nothing here is a hardness or P vs NP statement.

## PMLL modules (v173 merge)

After an independent replay of a Constellation-crew kit (and a review of a
same-day Neptune Elysium Prime archive), the following were folded in. Full
credits and honesty labels: [ATTRIBUTION.md](ATTRIBUTION.md). Pinned hashes:
[ORIGIN_PINNED.json](ORIGIN_PINNED.json).

| Path | What it is | What it is not |
| --- | --- | --- |
| `qforge_pmll/` | Stdlib helpers: FWHT SimHash silo, contract-bound Q-promises, GF(2) Farkas duals, certificate-gated ERS reconsider, RFC 6962 Merkle + a pre-push hygiene scan | Not a proof of an open problem. Farkas duals are an *extension* of upstream `xor_sat.py`, not a function already in `drQedwards/pmll`. |
| `c_core/` | C11 silo tokenizer / VSIDS+LBD+DRUP SAT upgrades, Woodbury–Rump helper. Compile with `gcc -std=c11`; ASan/UBSan is a separate target. | The C self-test banner may mention ASan even on a non-sanitized build — believe the compiler flags, not the banner. |
| `cuda/cuda_pmll_v2.cu` | `sm_86` tiered Hot/Warm/Cold salience kernel. Compile with `nvcc -O3 -arch=sm_86 --fmad=false`. Run only under a registered GPU lease. | A successful self-print is not an independent numerical audit of every kernel path. |
| `cuda/v168_shor_cyclic_kickmix_sm86.cu` | Classical Shor-phase *simulator* | Not a QPU result. No quantum credit. |
| `tools/` | `circ_check`, `model_adapter`, a Lean token scan, and `guarded_run` | Not a substitute for `lean436-check.sh` (`rc=0` only). |
| `contrib/neptune_pmll/` | Earlier V166/V170 audit/sync engines whose own self-tests passed under `python3` and `python3 -O` | The rest of the Neptune zip (cockpit, radio, "millennium solver" artifacts) is not shipped. |
| `scripts/verify_pmll_gates.py` | Crew 10-gate / 8-mutant verifier, plus C compile when `gcc` is present | Independent tests in `tests/test_qforge_pmll.py` are the second check. |

`"FINITE_EXPERIMENT": true` and `"clay_proof": 0` are mandatory on receipts.
The 8.0× figure for the FWHT silo is a *size ratio* (128 B / 16 B), not a
runtime speedup. Collision-bias numbers are fixture-dependent experiments.

```bash
PYTHONPATH=. python3 scripts/verify_pmll_gates.py
PYTHONPATH=. python3 -O scripts/verify_pmll_gates.py
PYTHONPATH=. python3 -m qforge_pmll.cli hygiene-scan --root .
# C11 (writes .build_tmp/, gitignored)
make -f Makefile.pmll asan-check
```


CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (mirrored at [ci/github-ci.yml](ci/github-ci.yml)) runs pytest, the PMLL gates under `python` and `python -O`, the kernel receipt parity check, the C11 sanitizer build and the hygiene scan.

## License

MIT, to match Dr. Q's PMLL repositories.
