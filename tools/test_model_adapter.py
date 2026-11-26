"""Mutation harness for model_adapter (checker hardening for the NEW OpenAI-convention checker). Every planted fault must be CAUGHT, honest cases must pass.
Run: python3 test_model_adapter.py   (exit 0 iff ALL)"""
import copy, sys, json, random
sys.path.insert(0, __file__.rsplit('/', 1)[0])
import circ_check as C, model_adapter as A
res = {}
for m in (2, 3, 4, 5):
    g, out, var = C.ryser_circuit(m); t, o = A.anth_to_openai(g, out)
    res[f'honest_m{m}'] = A.same_polynomial(t, o, g, out, var)
    cn = A.counts(g, t); res[f'count_rel_m{m}'] = cn['openai_ops'] == cn['anthropic_total'] - cn['free_nonops'] and cn['openai_ops'] <= cn['anthropic_total']
    g2, out2 = A.openai_to_anth(t, o); res[f'roundtrip_m{m}'] = A.same_polynomial(t, o, g2, out2, var)
    res[f'roundtrip_size_m{m}'] = len(g2) <= len(g)   # no sub gates here, so identical or smaller (dedup)
    ref = lambda M: C.perm_mod(M)
    # honest table really is the permanent (independent of the converter)
    rnd = random.Random(m); a = {(i, j): rnd.randrange(C.P) for i in range(m) for j in range(m)}
    res[f'is_perm_m{m}'] = A.eval_openai(t, o, a) == C.perm_mod([[a[(i, j)] for j in range(m)] for i in range(m)]) % C.P
    muts = {}
    k = next(i for i, x in enumerate(t) if x[0] == 'mul' and ('g', i) != o); mt = copy.deepcopy(t); mt[k] = ('add',) + t[k][1:]; muts['mul_to_add'] = mt
    k = next(i for i, x in enumerate(t) if x[0] == 'add'); mt = copy.deepcopy(t); mt[k] = ('sub',) + t[k][1:]; muts['add_to_sub'] = mt
    k = next(i for i, x in enumerate(t) if x[0] == 'add' and x[1][0] == 'g'); mt = copy.deepcopy(t); mt[k] = (t[k][0], ('g', k), t[k][2]); muts['self_reference'] = mt
    k = next(i for i, x in enumerate(t) if x[0] == 'add'); mt = copy.deepcopy(t); mt[k] = (t[k][0], t[k][1], ('g', len(t) - 1)); muts['forward_ref'] = mt
    k = next(i for i, x in enumerate(t) if x[1][0] == 'c'); mt = copy.deepcopy(t); mt[k] = (t[k][0], ('c', 1), t[k][2]); muts['scalar_flip'] = mt
    k = next(i for i, x in enumerate(t) if x[1][0] == 'v'); mt = copy.deepcopy(t); mt[k] = (t[k][0], ('v', (0, 1) if t[k][1][1] != (0, 1) else (1, 1)), t[k][2]); muts['var_rename'] = mt
    muts['wrong_output'] = None
    for n, mt in muts.items():
        if n == 'wrong_output': res[f'caught_{n}_m{m}'] = not A.same_polynomial(t, ('g', len(t) - 2), g, out, var); continue
        res[f'caught_{n}_m{m}'] = not A.same_polynomial(mt, o, g, out, var)
# subtraction semantics: x - y over a 2-variable ring, both directions of the adapter
tab = [('sub', ('v', 'x'), ('v', 'y')), ('mul', ('g', 0), ('g', 0))]
g2, o2 = A.openai_to_anth(tab, ('g', 1)); var = {'x': 0, 'y': 1}
rnd = random.Random(3); a = {'x': rnd.randrange(C.P), 'y': rnd.randrange(C.P)}
res['sub_semantics'] = A.eval_openai(tab, ('g', 1), a) == (a['x'] - a['y']) ** 2 % C.P == C.eval_circuit(g2, a)[o2]
res['sub_cost'] = len(g2) <= 3 * len(tab) + 3   # <= 3 gates per OpenAI op plus var/const gates
# order-sensitivity: sub is NOT commutative (a swap mutant must change the value)
tab2 = [('sub', ('v', 'y'), ('v', 'x')), ('mul', ('g', 0), ('g', 0))]; res['sub_swap_square_equal'] = A.eval_openai(tab2, ('g', 1), a) == A.eval_openai(tab, ('g', 1), a)
tab3 = [('sub', ('v', 'y'), ('v', 'x'))]; tab4 = [('sub', ('v', 'x'), ('v', 'y'))]; res['sub_swap_caught'] = A.eval_openai(tab3, ('g', 0), a) != A.eval_openai(tab4, ('g', 0), a)
res['ALL'] = all(res.values())
print(json.dumps(res, indent=1)); sys.exit(0 if res['ALL'] else 1)
