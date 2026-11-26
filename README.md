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

## License

MIT, to match Dr. Q's PMLL repositories.
