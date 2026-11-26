"""Small pure-Python CDCL SAT solver with an optional RUP proof log, plus an
independent forward RUP checker.

Charmander V174 (2026-11-26). Research code: fine for the few-thousand-variable
instances used by the exact-synthesis engine; not a competition solver.

Literals are non-zero ints (DIMACS style). solve() returns True (SAT, model in
.model), False (UNSAT), or None (conflict budget exhausted).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence


class CDCL:
    def __init__(self, nvars: int, clauses: Sequence[Sequence[int]], proof: bool = False):
        self.n = nvars
        self.val = [0] * (nvars + 1)          # 0 unassigned, 1 true, -1 false
        self.level = [0] * (nvars + 1)
        self.reason: List[Optional[int]] = [None] * (nvars + 1)
        self.activity = [0.0] * (nvars + 1)
        self.phase = [-1] * (nvars + 1)
        self.inc = 1.0
        self.trail: List[int] = []
        self.lim: List[int] = []
        self.qhead = 0
        self.clauses: List[List[int]] = []
        self.watches: Dict[int, List[int]] = {}
        self.proof: Optional[List[List[int]]] = [] if proof else None
        self.model: List[int] = []
        self.conflicts = 0
        self.decisions = 0
        self.propagations = 0
        self.unsat = False
        for c in clauses:
            self._add_input(list(c))

    # -- helpers -----------------------------------------------------------
    def _value(self, lit: int) -> int:
        v = self.val[abs(lit)]
        return v if lit > 0 else -v

    def _enqueue(self, lit: int, reason: Optional[int]) -> bool:
        cur = self._value(lit)
        if cur != 0:
            return cur == 1
        v = abs(lit)
        self.val[v] = 1 if lit > 0 else -1
        self.level[v] = len(self.lim)
        self.reason[v] = reason
        self.trail.append(lit)
        return True

    def _watch(self, lit: int, ci: int) -> None:
        self.watches.setdefault(lit, []).append(ci)

    def _add_input(self, c: List[int]) -> None:
        if self.unsat:
            return
        seen = set()
        out = []
        for lit in c:
            if lit == 0 or abs(lit) > self.n:
                raise ValueError(f"bad literal {lit}")
            if -lit in seen:
                return  # tautology
            if lit not in seen:
                seen.add(lit)
                out.append(lit)
        if not out:
            self.unsat = True
            return
        if len(out) == 1:
            if not self._enqueue(out[0], None):
                self.unsat = True
            return
        ci = len(self.clauses)
        self.clauses.append(out)
        self._watch(out[0], ci)
        self._watch(out[1], ci)

    # -- propagation ---------------------------------------------------------
    def _propagate(self) -> Optional[int]:
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.propagations += 1
            false_lit = -p
            ws = self.watches.get(false_lit)
            if not ws:
                continue
            i = 0
            j = 0
            n = len(ws)
            conflict = None
            while i < n:
                ci = ws[i]
                i += 1
                c = self.clauses[ci]
                if c[0] == false_lit:
                    c[0], c[1] = c[1], c[0]
                first = c[0]
                if self._value(first) == 1:
                    ws[j] = ci
                    j += 1
                    continue
                found = False
                for k in range(2, len(c)):
                    if self._value(c[k]) != -1:
                        c[1], c[k] = c[k], c[1]
                        self._watch(c[1], ci)
                        found = True
                        break
                if found:
                    continue
                ws[j] = ci
                j += 1
                if self._value(first) == -1:
                    conflict = ci
                    while i < n:
                        ws[j] = ws[i]
                        j += 1
                        i += 1
                else:
                    self._enqueue(first, ci)
            del ws[j:]
            if conflict is not None:
                return conflict
        return None

    # -- conflict analysis ----------------------------------------------------
    def _bump(self, v: int) -> None:
        self.activity[v] += self.inc
        if self.activity[v] > 1e100:
            self.activity = [a * 1e-100 for a in self.activity]
            self.inc *= 1e-100

    def _analyze(self, confl: int):
        seen = [False] * (self.n + 1)
        learnt = [0]
        counter = 0
        p = 0
        idx = len(self.trail) - 1
        cur_level = len(self.lim)
        reason_c = self.clauses[confl]
        while True:
            for q in (reason_c if p == 0 else reason_c[1:]):
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    seen[v] = True
                    self._bump(v)
                    if self.level[v] >= cur_level:
                        counter += 1
                    else:
                        learnt.append(q)
            while not seen[abs(self.trail[idx])]:
                idx -= 1
            p = self.trail[idx]
            idx -= 1
            v = abs(p)
            seen[v] = False
            counter -= 1
            if counter == 0:
                break
            r = self.reason[v]
            reason_c = self.clauses[r]
            # make sure the implied literal is first
            if reason_c[0] != p:
                k = reason_c.index(p)
                reason_c[0], reason_c[k] = reason_c[k], reason_c[0]
        learnt[0] = -p
        if len(learnt) == 1:
            bt = 0
        else:
            mi = max(range(1, len(learnt)), key=lambda t: self.level[abs(learnt[t])])
            learnt[1], learnt[mi] = learnt[mi], learnt[1]
            bt = self.level[abs(learnt[1])]
        self.inc *= 1.0 / 0.95
        return learnt, bt

    def _cancel_until(self, lvl: int) -> None:
        if len(self.lim) > lvl:
            for k in range(len(self.trail) - 1, self.lim[lvl] - 1, -1):
                v = abs(self.trail[k])
                self.phase[v] = self.val[v]
                self.val[v] = 0
                self.reason[v] = None
            del self.trail[self.lim[lvl]:]
            del self.lim[lvl:]
            self.qhead = len(self.trail)

    def _pick(self) -> int:
        best = 0
        ba = -1.0
        act = self.activity
        val = self.val
        for v in range(1, self.n + 1):
            if val[v] == 0 and act[v] > ba:
                ba = act[v]
                best = v
        if best == 0:
            return 0
        return best if self.phase[best] == 1 else -best

    @staticmethod
    def _luby(i: int) -> int:
        k = 1
        while (1 << k) - 1 < i:
            k += 1
        while (1 << k) - 1 != i:
            if (1 << (k - 1)) <= i:
                i -= (1 << (k - 1)) - 1
            k = 1
            while (1 << k) - 1 < i:
                k += 1
        return 1 << (k - 1)

    # -- main loop ------------------------------------------------------------
    def solve(self, conflict_limit: Optional[int] = None) -> Optional[bool]:
        if self.unsat:
            if self.proof is not None:
                self.proof.append([])
            return False
        if self._propagate() is not None:
            if self.proof is not None:
                self.proof.append([])
            return False
        restart_no = 1
        budget = 64 * self._luby(restart_no)
        since = 0
        while True:
            confl = self._propagate()
            if confl is not None:
                self.conflicts += 1
                since += 1
                if not self.lim:
                    if self.proof is not None:
                        self.proof.append([])
                    return False
                learnt, bt = self._analyze(confl)
                self._cancel_until(bt)
                if self.proof is not None:
                    self.proof.append(list(learnt))
                if len(learnt) == 1:
                    self._enqueue(learnt[0], None)
                else:
                    ci = len(self.clauses)
                    self.clauses.append(learnt)
                    self._watch(learnt[0], ci)
                    self._watch(learnt[1], ci)
                    self._enqueue(learnt[0], ci)
                if conflict_limit is not None and self.conflicts >= conflict_limit:
                    return None
            else:
                if since >= budget:
                    since = 0
                    restart_no += 1
                    budget = 64 * self._luby(restart_no)
                    self._cancel_until(0)
                    continue
                lit = self._pick()
                if lit == 0:
                    self.model = [0] + [1 if self.val[v] == 1 else 0 for v in range(1, self.n + 1)]
                    return True
                self.decisions += 1
                self.lim.append(len(self.trail))
                self._enqueue(lit, None)


def check_model(clauses: Sequence[Sequence[int]], model: Sequence[int]) -> bool:
    for c in clauses:
        if not any((model[abs(l)] == 1) == (l > 0) for l in c):
            return False
    return True


def check_rup_proof(nvars: int, clauses: Sequence[Sequence[int]], proof: Sequence[Sequence[int]]) -> bool:
    """Independent forward RUP check: every lemma must follow by unit propagation
    from the formula plus earlier lemmas, and the proof must end with []."""
    if not proof or list(proof[-1]) != []:
        return False
    db: List[List[int]] = []
    for c in clauses:
        uniq = list(dict.fromkeys(c))
        if any(-l in uniq for l in uniq):
            continue  # tautology
        db.append(uniq)

    def unit_refutes(assume: List[int]) -> bool:
        val = {}
        for a in assume:
            if val.get(-a):
                return True
            val[a] = True
        changed = True
        while changed:
            changed = False
            for c in db:
                unassigned = None
                n_un = 0
                sat = False
                for l in c:
                    if val.get(l):
                        sat = True
                        break
                    if not val.get(-l):
                        n_un += 1
                        unassigned = l
                        if n_un > 1:
                            break
                if sat or n_un > 1:
                    continue
                if n_un == 0:
                    return True
                val[unassigned] = True
                changed = True
        return False

    for lemma in proof:
        if not unit_refutes([-l for l in lemma]):
            return False
        if lemma:
            db.append(list(dict.fromkeys(lemma)))
    return True
