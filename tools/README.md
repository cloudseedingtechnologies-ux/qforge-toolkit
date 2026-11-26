# tools/

Staged lab utilities (Constellation crew / prior vpvnp intake), merged after
a safety read and a direct script run:

- `circ_check.py` — small Boolean/circuit identity checks. `test_circ_check.py` exits 0 on a cold start.
- `model_adapter.py` — statement/definition adapter used with the circuit checks. `test_model_adapter.py` exits 0 on a cold start.
- `r1_scan_and_stmt_eq.py` — Lean import-closure token scan (sorry/axiom/native_decide, …) plus statement equality. Invoke with a Lean root; it is not hard-wired to a private path.
- `guarded_run.py` — run a command under a host-memory/swap guard (`GUARD_V2=1` for the tolerant page-delta policy).

These files are stdlib-only. `guarded_run.py` uses `subprocess` to launch the
command you pass it; it does not touch the network.
