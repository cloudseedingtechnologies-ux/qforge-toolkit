# Quickstart

## Install

Python 3.10 or newer. Use a project-local virtualenv; do not install into a
shared environment.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

Optional, if you want to load the export into a live PMLL graph:

```bash
pip install -e ".[pmll]"
```

## Everyday commands

```bash
# Over-claim wording
python -m qforge_toolkit claim-lint README.md samples/MEMORY.md --strict

# Speed-claim gate (spec JSON with cases[{name, exact, complete_task, threads, base_s, cand_s}])
python -m qforge_toolkit speedgate path/to/spec.json

# Task card
python -m qforge_toolkit card path/to/card.json --max-ceiling BOUNDED_CERTIFICATE

# Receipt ledger
python -m qforge_toolkit ledger --root path/to/receipts --ledger path/to/LEDGER.json

# Lab index
python -m qforge_toolkit index build --dir path/to/index
python -m qforge_toolkit index validate --dir path/to/index

# Journal
python -m qforge_toolkit journal --work path/to/work ADMISSION --data '{"run":"demo"}'
python -m qforge_toolkit journal --work path/to/work --resume

# GPU lease table (no CUDA is started by the status command)
python -m qforge_toolkit gpu-lease status

# PMLL export of the scrubbed samples
python -m pmll.pmll_export \
  --memory samples/MEMORY.md \
  --index samples/lab_index.json \
  --session-id qforge-toolkit-sample \
  --out samples/exported_graph.json
```

## Shell wrappers

`scripts/lean_check.sh` needs an isolated Lean 4.36 elan home in `ELAN436_HOME`
(it will not install one, and it will not touch `~/.elan`). Point
`LEAN436_DEFAULT_LAKE` at a Mathlib lake project if the file imports Mathlib.

`scripts/gpu_lease_run.sh` acquires one lease, runs the command, and always
releases. Set `QFORGE_GPU_LEASE_TABLE` if you do not want the default
`~/.cache/qforge/gpu/leases.json`. The default reserve margin is 1536 MiB.

## Importing a graph into PMLL

```python
import os
from pathlib import Path
from pmll_memory_mcp.memory_graph import configure_db, import_graph, get_graph_stats

configure_db("path/to/scratch/memory_graph.sqlite3")  # not a shared /tmp
graph = Path("samples/exported_graph.json").read_text()
import json
data = json.loads(graph)
# import_graph wants {nodes, edges} as lists or id-maps
import_graph("qforge-toolkit-sample", {"nodes": data["nodes"], "edges": data["edges"]})
print(get_graph_stats("qforge-toolkit-sample"))
```

If `pmll-memory-mcp` is not installed, `pmll.pmll_export` still validates the
JSON against the published schema.
