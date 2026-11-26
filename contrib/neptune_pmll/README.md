# contrib/neptune_pmll

Reference copies of two stdlib engines taken from the 2026-11-26 Neptune
Elysium Prime archive after an independent cold start:

- `pmll_drq_audit_engine.py` — five-pillar audit (signed silo, CDCL+XOR,
  Q-promise single-flight, a *host-side model* of IEEE-754 packed atomic
  argmin, HRR fusion). Self-test: 5/5 pillars, same receipt under
  `python3` and `python3 -O`.
- `qforge_pmll_sync.py` — schema/sync helper with a 6-trap fail-closed
  battery. Self-test: 6/6 traps, same receipt under normal and `-O`.

Both print JSON with a claim ceiling and `FINITE_EXPERIMENT` where present.
They are not drop-in replacements for `qforge_pmll/` (the v173 modules are
the primary merge). Historical agent callsigns inside the source were left
intact so the engines' own receipts stay reproducible.

Not included from that zip: the Vite/React cockpit, Baofeng/SDR/AFSK
paths, sudo installers, or anything marketed as a Clay Millennium solver.
Radio transmit and device flashing are out of scope.

```bash
python3 contrib/neptune_pmll/pmll_drq_audit_engine.py
python3 -O contrib/neptune_pmll/qforge_pmll_sync.py
```
