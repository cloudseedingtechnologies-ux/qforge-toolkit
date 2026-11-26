#!/usr/bin/env python3
"""Run a command in its own process group pinned to 4 CPUs (taskset), niced, under a host guard.
Policy (binding, from the intake brief): pause (SIGSTOP) the whole group whenever machine-wide pswpin/pswpout change or MemAvailable < PAUSE_GIB;
resume after QUIET_S seconds of quiet; SIGKILL if MemAvailable < KILL_GIB. Logs every event to the journal file. stdlib only.
V2 (env GUARD_V2=1): swap trigger is a >=TOL_PAGES change per 3 s sample (default 2000 pages = 8 MiB) instead of ANY change; also aborts if own group VmSwap>0.
usage: guarded_run.py LOGFILE -- cmd ...   (env: PAUSE_GIB default 9, KILL_GIB default 5, QUIET_S default 20)"""
import os, sys, time, signal, subprocess, json
G = 1 << 30
log = sys.argv[1]; cmd = sys.argv[sys.argv.index('--') + 1:]
PAUSE = float(os.environ.get('PAUSE_GIB', 9)) * G; KILL = float(os.environ.get('KILL_GIB', 5)) * G; QUIET = float(os.environ.get('QUIET_S', 20))
def avail():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1]) * 1024
def pswp():
    d = {}
    for l in open('/proc/vmstat'):
        a, b = l.split()
        if a in ('pswpin', 'pswpout'): d[a] = int(b)
    return d['pswpin'], d['pswpout']
def own_vmswap(pgid):
    tot = 0
    for d in os.listdir('/proc'):
        if d.isdigit():
            try:
                if os.getpgid(int(d)) != pgid: continue
                for l in open(f'/proc/{d}/status'):
                    if l.startswith('VmSwap'): tot += int(l.split()[1])
            except Exception: pass
    return tot
def jl(m):
    open(log, 'a').write(time.strftime('%Y-%m-%dT%H:%M:%S%z') + ' ' + m + '\n')
V2 = os.environ.get('GUARD_V2') == '1'; TOL = int(os.environ.get('TOL_PAGES', 2000))
env = dict(os.environ, LEAN_NUM_THREADS='4', OMP_NUM_THREADS='1')
p = subprocess.Popen(['taskset', '-c', '0-3', 'nice', '-n', '10'] + cmd, env=env, start_new_session=True)
jl(f'START pid={p.pid} cmd={cmd} avail={avail()/G:.1f}GiB pswp={pswp()}')
base = pswp(); paused = False; last_change = 0.0; minavail = 1e18; npause = 0; t0 = time.time()
while p.poll() is None:
    time.sleep(3)
    a = avail(); minavail = min(minavail, a); s = pswp(); now = time.time()
    changed = (abs(s[0]-base[0]) >= TOL or abs(s[1]-base[1]) >= TOL) if V2 else (s != base); base = s
    if changed: last_change = now
    if V2 and own_vmswap(p.pid) > 0:
        jl('KILL own VmSwap>0'); os.killpg(p.pid, signal.SIGKILL); break
    if a < KILL and not paused or a < KILL * 0.8:
        jl(f'KILL avail={a/G:.1f}GiB < {KILL/G}'); os.killpg(p.pid, signal.SIGKILL); break
    if not paused and (changed or a < PAUSE):
        os.killpg(p.pid, signal.SIGSTOP); paused = True; npause += 1; jl(f'PAUSE swap_changed={changed} avail={a/G:.1f}GiB pswp={s}')
    elif paused and not changed and a >= PAUSE and now - last_change >= QUIET:
        os.killpg(p.pid, signal.SIGCONT); paused = False; jl(f'RESUME avail={a/G:.1f}GiB')
rc = p.wait()
jl(f'END rc={rc} elapsed={time.time()-t0:.0f}s min_avail={minavail/G:.1f}GiB pauses={npause}')
sys.exit(rc)
