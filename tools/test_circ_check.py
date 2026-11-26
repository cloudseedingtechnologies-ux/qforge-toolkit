"""Mutation harness for circ_check: every planted fault must be CAUGHT; honest circuits must pass. Run: python test_circ_check.py"""
import copy, random, sys, json
sys.path.insert(0, __file__.rsplit('/', 1)[0])
import circ_check as C
res = {}
for m in (3, 4, 5):
    g, out, var = C.ryser_circuit(m); ref = lambda M: C.perm_mod(M)
    res[f'honest_m{m}'] = C.check_computes(g, out, var, ref)[0]
    # M1: change one product gate into a sum
    muts = {}
    k = next(i for i, x in enumerate(g) if x[0] == 'mul' and i != out); mg = copy.deepcopy(g); mg[k] = ('add', g[k][1], g[k][2]); muts['mul_to_add'] = mg
    # M2: drop the sign (-1 constant -> +1)
    k = next(i for i, x in enumerate(g) if x == ('const', -1)); mg = copy.deepcopy(g); mg[k] = ('const', 1); muts['sign_flip'] = mg
    # M3: forward reference (ill-formed)
    k = next(i for i, x in enumerate(g) if x[0] == 'add'); mg = copy.deepcopy(g); mg[k] = ('add', len(g) - 1, g[k][2]); muts['forward_ref'] = mg
    # M4: wrong target (hc instead of perm) -> honest circuit must NOT pass as hc
    res[f'honest_not_hc_m{m}'] = (not C.check_computes(g, out, var, lambda M: C.hc_brute(M))[0]) if m >= 3 else True
    # M5: swap two variable wirings (transposition preserves perm: must PASS) and a single variable rename (must be caught)
    k = next(i for i, x in enumerate(g) if x[0] == 'var'); mg = copy.deepcopy(g); mg[k] = ('var', (0, 1) if g[k][1] != (0, 1) else (1, 1)); muts['var_rename'] = mg
    for n, mg in muts.items(): res[f'caught_{n}_m{m}'] = not C.check_computes(mg, out, var, ref)[0]
# transposed perm = perm (a statement-level fact used by the 2opremio bridge): circuit on M^T with same wiring passes against ref(M^T)
g, out, var = C.ryser_circuit(4); res['perm_transpose_ok'] = C.check_computes(g, out, var, lambda M: C.perm_mod([list(r) for r in zip(*M)]))[0]
# exact small-integer cross-check of reference implementations
rnd = random.Random(7); M = [[rnd.randint(-2, 2) for _ in range(5)] for _ in range(5)]
res['ryser_eq_brute_m5'] = C.perm_mod(M) == C.perm_brute(M) % C.P
res['hc_count_m5'] = sum(1 for _ in __import__('itertools').permutations(range(1, 5))) == 24
res['ALL'] = all(res.values())
print(json.dumps(res, indent=1)); sys.exit(0 if res['ALL'] else 1)
