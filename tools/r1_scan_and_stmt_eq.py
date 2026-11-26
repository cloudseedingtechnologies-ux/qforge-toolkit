#!/usr/bin/env python3
"""R1: token scan over the import closure of OAI.Computability.VPVNP.ClassSeparation + Challenge/Solution statement and definition text equality.
Usage: r1_scan_and_stmt_eq.py LEANROOT OUT.json   (LEANROOT = openai/math lean/ directory)"""
import re,sys,json,os
R=sys.argv[1].rstrip('/')+'/'
def closure():
    seen=set(); st=['OAI.Computability.VPVNP.ClassSeparation']
    while st:
        m=st.pop()
        if m in seen: continue
        seen.add(m); p=R+m.replace('.','/')+'.lean'
        if not os.path.exists(p): continue
        for i in re.findall(r'^(?:public )?import ([\w.]+)',open(p,encoding='utf8').read(),re.M):
            if i.startswith('OAI'): st.append(i)
    return sorted(seen)
mods=closure(); allf=[R+m.replace('.','/')+'.lean' for m in mods]; files=[f for f in allf if os.path.exists(f)]; missing=len(allf)-len(files)
toks=['sorry','admit','axiom','native_decide','implemented_by','extern','unsafe','opaque','ofReduceBool','reduceBool','run_cmd','initialize','elab','syntax','decide +kernel','decide +native','allowUnsafeReducibility','debug.skipKernelTC','Classical.choice']
cnt={t:[0,0] for t in toks}; lines=0; hits={}
for f in files:
    t=open(f,encoding='utf8').read(); lines+=t.count('\n')
    # strip comments crudely for token counting
    s=re.sub(r'/-.*?-/','',t,flags=re.S); s=re.sub(r'--.*','',s)
    for k in toks:
        n=len(re.findall(r'(?<![A-Za-z_.])'+re.escape(k)+r'(?![A-Za-z_])',s))
        if n: cnt[k][0]+=n; cnt[k][1]+=1; hits.setdefault(k,[]).append(os.path.relpath(f,R))
setopt={}
for f in files:
    for m in re.findall(r'set_option\s+([\w.]+)',open(f,encoding='utf8').read()): setopt[m]=setopt.get(m,0)+1
def defs(path,names):
    t=open(path,encoding='utf8').read(); out={}
    for n in names:
        m=re.search(r'((?:noncomputable )?(?:def|abbrev|theorem) '+re.escape(n)+r'\b.*?)(?=\n\n|\nend |\n/--|\nnamespace)',t,re.S)
        out[n]=' '.join(re.sub(r'/-.*?-/','',m.group(1),flags=re.S).split()) if m else None
    return out
names=['Computes','PolynomiallyBounded','Family','PFamily','IsVP','IsVNP']
ch=defs(R+'ComparatorChallenges/VPVNP.lean',names); sol=defs(R+'OAI/Computability/VPVNP/Valiant/ProjectModel.lean',names)
eq={n:(ch[n] is not None and ch[n]==sol[n]) for n in names}
def thm(path):
    t=open(path,encoding='utf8').read(); m=re.search(r'theorem vp_ne_vnp\s*(.*?):= by',t,re.S); return ' '.join(m.group(1).split())
ts=thm(R+'ComparatorChallenges/VPVNP.lean'); tc=thm(R+'OAI/Computability/VPVNP/ClassSeparation.lean')
cj=json.load(open(R+'ComparatorChallenges/VPVNP.json'))
out=dict(modules=len(files),missing_modules=missing,lines=lines,token_counts_noncomment={k:{'occurrences':v[0],'files':v[1]} for k,v in cnt.items()},token_files={k:v[:5] for k,v in hits.items()},
 set_option=dict(sorted(setopt.items(),key=lambda x:-x[1])),definition_text_equal_challenge_vs_ProjectModel=eq,theorem_statement_equal=ts==tc,theorem_statement=ts,comparator_json=cj)
json.dump(out,open(sys.argv[2],'w'),indent=1)
print(json.dumps({k:out[k] for k in ['modules','lines','definition_text_equal_challenge_vs_ProjectModel','theorem_statement_equal']}),'\nnonzero tokens:',{k:v for k,v in out['token_counts_noncomment'].items() if v['occurrences']})
