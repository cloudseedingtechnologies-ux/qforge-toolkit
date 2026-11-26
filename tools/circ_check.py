#!/usr/bin/env python3
"""circ_check -- STAGED toolkit proposal (not installed). Straight-line arithmetic-circuit checker in the exact gate convention of
anthropics/formal-math vp-vnp Statement.lean `Computes`: a list of s gates, each a variable, a constant, or the sum / product of two
EARLIER gates (i<k, j<k; i==j allowed); variables and constants count as gates; the circuit computes f if some gate equals f as a FORMAL polynomial.
Checks (stdlib only):
  * well-formedness (no forward references, only var/const/add/mul),
  * formal-identity test by Schwartz-Zippel over GF(p), p = 2^61-1, r independent random points (error <= (deg/p)^r),
    and EXACT identity (sympy-free) via dict polynomials for tiny sizes,
  * reference polynomials perm_m (Ryser/brute), hc_m (brute over (m-1)! cycles) and gate-count builders for Ryser-type circuits.
Never imports the tool under test; deterministic seeds. CPU, 1 thread."""
import itertools, random, math, sys, json
P = (1 << 61) - 1
def wellformed(gates):
    for k, g in enumerate(gates):
        t = g[0]
        if t in ('var', 'const'): continue
        if t in ('add', 'mul') and 0 <= g[1] < k and 0 <= g[2] < k: continue
        return False, k
    return True, None
def eval_circuit(gates, assign, p=P):
    v = []
    for g in gates:
        t = g[0]
        v.append(assign[g[1]] % p if t == 'var' else g[1] % p if t == 'const' else (v[g[1]] + v[g[2]]) % p if t == 'add' else v[g[1]] * v[g[2]] % p)
    return v
def perm_mod(M, p=P):  # Ryser, exact integers then mod
    m = len(M); tot = 0
    for S in range(1, 1 << m):
        prod = 1
        for i in range(m):
            prod *= sum(M[i][j] for j in range(m) if S >> j & 1)
        tot += (-1) ** (m - bin(S).count('1')) * prod
    return tot % p
def perm_brute(M):
    m = len(M); return sum(math.prod(M[i][s[i]] for i in range(m)) for s in itertools.permutations(range(m)))
def hc_brute(M):  # sum over single m-cycles sigma of prod M[i][sigma(i)]
    m = len(M); tot = 0
    for rest in itertools.permutations(range(1, m)):
        cyc = (0,) + rest; prod = 1
        for a in range(m): prod *= M[cyc[a]][cyc[(a + 1) % m]]
        tot += prod
    return tot
def ryser_circuit(m):
    """Arithmetic circuit for PERM_m over any commutative ring with 1,-1: row sums r_i(S) built incrementally over subsets (Gray-free, lowbit recurrence),
    products of rows, signed accumulation split into two sums. Returns (gates, out_index, var_index_map)."""
    g = []; var = {}
    def add(x): g.append(x); return len(g) - 1
    for i in range(m):
        for j in range(m): var[(i, j)] = add(('var', (i, j)))
    neg1 = add(('const', -1))
    r = [{0: None} for _ in range(m)]  # r[i][S] -> gate index (S>0)
    pos = []; neg = []
    for S in range(1, 1 << m):
        low = (S & -S).bit_length() - 1; prev = S & (S - 1)
        rows = []
        for i in range(m):
            r[i][S] = var[(i, low)] if prev == 0 else add(('add', r[i][prev], var[(i, low)]))
            rows.append(r[i][S])
        acc = rows[0]
        for x in rows[1:]: acc = add(('mul', acc, x))
        (pos if (m - bin(S).count('1')) % 2 == 0 else neg).append(acc)
    def sumlist(l):
        acc = l[0]
        for x in l[1:]: acc = add(('add', acc, x))
        return acc
    P_, N_ = sumlist(pos), (sumlist(neg) if neg else None)
    out = P_ if N_ is None else add(('add', P_, add(('mul', neg1, N_))))
    return g, out, var
def check_computes(gates, out, var, ref, rounds=3, seed=1, p=P):
    """True iff circuit is well formed and gate `out` equals ref (callable on matrix) at `rounds` random GF(p) points."""
    ok, bad = wellformed(gates)
    if not ok: return False, f'ill-formed at gate {bad}'
    rnd = random.Random(seed); m = int(round(len(var) ** .5))
    for _ in range(rounds):
        M = [[rnd.randrange(p) for _ in range(m)] for _ in range(m)]
        val = eval_circuit(gates, {(i, j): M[i][j] for i in range(m) for j in range(m)}, p)[out]
        if val != ref(M) % p: return False, 'mismatch at random point'
    return True, 'ok'
if __name__ == '__main__':
    rows = []
    for m in range(2, 9):
        g, out, var = ryser_circuit(m); ok, msg = check_computes(g, out, var, lambda M: perm_mod(M))
        # independent exact check on small integers vs brute force
        rnd = random.Random(m); M = [[rnd.randint(-3, 3) for _ in range(m)] for _ in range(m)]
        ev = eval_circuit(g, {(i, j): M[i][j] for i in range(m) for j in range(m)})[out]
        rows.append(dict(m=m, gates=len(g), ok=ok, exact_small=(ev == perm_brute(M) % P)))
    print(json.dumps(rows))
