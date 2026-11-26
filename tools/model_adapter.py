#!/usr/bin/env python3
"""model_adapter -- STAGED. Converts between the two gate conventions seen in the two VP!=VNP intakes and checks they compute the same formal polynomial.
 Anthropic vp-vnp Statement.lean `Computes`: s gates, each a var, a constant, or add/mul of two EARLIER gates; variables and constants COUNT as gates.
 OpenAI ComparatorChallenges/VPVNP.lean `Computes`: s gates, each add/sub/mul of two AVAILABLE values; available = a variable, a scalar, or an EARLIER gate value
   (j.val < i); variables/scalars are FREE; the output is any available value. (Lean reads availability by value-equality, so reuse is free.)
Operand encodings in the OpenAI table: ('v', j) variable, ('c', a) scalar, ('g', k) earlier table entry (k < i).  Table entries: (op, a, b), op in add/sub/mul.
Checks are Schwartz-Zippel over GF(2^61-1) via circ_check. stdlib only."""
import random, sys, json
sys.path.insert(0, __file__.rsplit('/', 1)[0])
import circ_check as C
P = C.P
def anth_to_openai(gates, out):
    """Drop var/const gates (free in the OpenAI model), keep add/mul. Returns (table, outref)."""
    ref = {}; table = []
    for k, g in enumerate(gates):
        if g[0] == 'var': ref[k] = ('v', g[1])
        elif g[0] == 'const': ref[k] = ('c', g[1])
        else:
            table.append((g[0], ref[g[1]], ref[g[2]])); ref[k] = ('g', len(table) - 1)
    return table, ref[out]
def wellformed_openai(table, outref):
    for i, (op, a, b) in enumerate(table):
        if op not in ('add', 'sub', 'mul'): return False, i
        for x in (a, b):
            if x[0] == 'g' and not (0 <= x[1] < i): return False, i
            if x[0] not in ('v', 'c', 'g'): return False, i
    if outref[0] == 'g' and not (0 <= outref[1] < len(table)): return False, -1
    return True, None
def eval_openai(table, outref, assign, p=P):
    vals = []
    def get(x): return assign[x[1]] % p if x[0] == 'v' else x[1] % p if x[0] == 'c' else vals[x[1]]
    for op, a, b in table:
        x, y = get(a), get(b)
        vals.append((x + y) % p if op == 'add' else (x - y) % p if op == 'sub' else x * y % p)
    return get(outref)
def openai_to_anth(table, outref):
    """Rebuild an Anthropic-convention circuit: variables/constants become gates (deduplicated), sub a-b -> a + (-1)*b (adds one const -1 and 2 gates)."""
    g = []; idx = {}
    def node(x):
        if x[0] == 'g': return idx[('g', x[1])]
        if x not in idx: g.append(('var', x[1]) if x[0] == 'v' else ('const', x[1])); idx[x] = len(g) - 1
        return idx[x]
    for i, (op, a, b) in enumerate(table):
        A, B = node(a), node(b)
        if op == 'sub':
            m1 = node(('c', -1)); g.append(('mul', m1, B)); nb = len(g) - 1; g.append(('add', A, nb))
        else: g.append((op, A, B))
        idx[('g', i)] = len(g) - 1
    return g, node(outref)
def same_polynomial(table, outref, gates, out, var, rounds=3, seed=5, p=P):
    ok1, _ = wellformed_openai(table, outref); ok2, _ = C.wellformed(gates)
    if not (ok1 and ok2): return False
    rnd = random.Random(seed); keys = list(var)
    for _ in range(rounds):
        a = {k: rnd.randrange(p) for k in keys}
        if eval_openai(table, outref, a, p) != C.eval_circuit(gates, a, p)[out]: return False
    return True
def counts(gates, table):
    nv = sum(1 for g in gates if g[0] in ('var', 'const'))
    return dict(anthropic_total=len(gates), free_nonops=nv, openai_ops=len(table))
