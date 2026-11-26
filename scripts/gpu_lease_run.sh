#!/bin/bash
# gpu_lease_run.sh — acquire one VRAM lease, run a command under a systemd
# --user scope with MemorySwapMax=0, a CPU cap, and a swap/RAM guard, then
# always release the lease.
#
# No CUDA outside a lease. No nested leases. No /tmp. No sudo. No clock,
# power, or driver changes. Does not kill processes it did not start.
#
# Env: QFORGE_GPU_LEASE_PY, QFORGE_GPU_LEASE_TABLE, GPU_LEASE_MIN_MEM_GIB,
# GPU_LEASE_SWAP_PAGES, GPU_LEASE_MEMORY_MAX, GPU_LEASE_CPUS.
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null; then
  SCRIPT_PATH="$(readlink -f "$SCRIPT_PATH" 2>/dev/null || echo "$SCRIPT_PATH")"
fi
ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
# Prefer the toolkit's portable lease module when the caller has not set one.
if [ -z "${QFORGE_GPU_LEASE_PY:-}" ]; then
  if [ -f "$ROOT/qforge_toolkit/gpu_lease.py" ]; then
    QFORGE_GPU_LEASE_PY="$ROOT/qforge_toolkit/gpu_lease.py"
  fi
fi
LEASE_PY="${QFORGE_GPU_LEASE_PY:-}"
if [ -z "$LEASE_PY" ] || [ ! -f "$LEASE_PY" ]; then
  echo "gpu_lease_run: set QFORGE_GPU_LEASE_PY to gpu_lease.py" >&2
  exit 2
fi
MARGIN_DEFAULT=1536
MIB=""
MARGIN="$MARGIN_DEFAULT"
TIMEOUT=600
CPUS="${GPU_LEASE_CPUS:-8}"
MEM_MAX="${GPU_LEASE_MEMORY_MAX:-8G}"
NICE_N="${GPU_LEASE_NICE:-10}"
OWNER=""
TASKSET_CPUS=""

usage() {
  cat <<'EOF'
Usage:
  gpu_lease_run.sh status
  gpu_lease_run.sh --mib MIB [--margin 1536] [--timeout 600] [--cpus 8]
                   [--mem 8G] [--owner NAME] [--] COMMAND [ARGS...]

Acquires exactly one lease from $QFORGE_GPU_LEASE_TABLE or
~/.cache/qforge/gpu/leases.json (flocked by qforge_toolkit/gpu_lease.py). The reserve ("margin") is at least 1536 MiB.

The command runs in: systemd-run --user --scope -p MemoryMax -p MemorySwapMax=0
plus nice and taskset, with OMP/OpenBLAS/MKL threads capped to --cpus (default 8
of the host). CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}.

Tolerant swap guard (lab behaviour):
  refuse to start if MemAvailable < 9 GiB, or pswpin+pswpout >= 2000 pages
  in a 3 s window; during the run, stop our child if those trip; kill our
  child only if our own VmSwap is above 0. Never touches other users' jobs.

Refuse nesting if QFORGE_GPU_IN_LEASE is already set.
EOF
}

sample_swap() {
  awk '/^pswpin /{p=$2} /^pswpout /{o=$2} END{print p+0, o+0}' /proc/vmstat
}

mem_avail_kib() {
  awk '/^MemAvailable:/{print $2+0}' /proc/meminfo
}

swap_window_ok() {
  local p1 o1 p2 o2 dp do tot
  read -r p1 o1 < <(sample_swap)
  sleep 3
  read -r p2 o2 < <(sample_swap)
  dp=$((p2-p1)); do=$((o2-o1)); tot=$((dp+do))
  if [ "$tot" -ge "${GPU_LEASE_SWAP_PAGES:-2000}" ]; then
    echo "swap_guard: pswpin+pswpout=$tot pages / 3s (>= ${GPU_LEASE_SWAP_PAGES:-2000}) — pause" >&2
    return 1
  fi
  return 0
}

host_ram_ok() {
  local k
  k="$(mem_avail_kib)"
  if [ "$k" -lt $((9 * 1024 * 1024)) ]; then
    echo "swap_guard: MemAvailable=${k} KiB (< ${GPU_LEASE_MIN_MEM_GIB:-9} GiB) — pause" >&2
    return 1
  fi
  return 0
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then usage; exit 0; fi
if [ "${1:-}" = "status" ]; then
  /usr/bin/python3 "$LEASE_PY" status
  exit $?
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --mib) MIB="${2:?}"; shift 2 ;;
    --margin) MARGIN="${2:?}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?}"; shift 2 ;;
    --cpus) CPUS="${2:?}"; shift 2 ;;
    --mem) MEM_MAX="${2:?}"; shift 2 ;;
    --owner) OWNER="${2:?}"; shift 2 ;;
    --taskset) TASKSET_CPUS="${2:?}"; shift 2 ;;
    --) shift; break ;;
    --*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) break ;;
  esac
done

if [ -z "$MIB" ] || [ $# -lt 1 ]; then usage >&2; exit 2; fi
if [ "$MARGIN" -lt 1536 ]; then
  echo "gpu-lease-run: margin must be >= 1536 MiB (got $MARGIN)" >&2
  exit 2
fi
if [ -n "${QFORGE_GPU_IN_LEASE:-}" ]; then
  echo "gpu-lease-run: refused nested lease (QFORGE_GPU_IN_LEASE=${QFORGE_GPU_IN_LEASE})" >&2
  exit 3
fi
if [ ! -f "$LEASE_PY" ]; then
  echo "gpu-lease-run: missing $LEASE_PY" >&2
  exit 1
fi

if [ -z "$TASKSET_CPUS" ]; then
  last=$((CPUS-1))
  if [ "$last" -lt 0 ]; then last=0; fi
  if [ "$last" -gt 19 ]; then last=19; fi
  TASKSET_CPUS="0-${last}"
fi

mkdir -p "$ROOT/work/tmp" "$ROOT/logs"
export TMPDIR="$ROOT/work/tmp"
LOG="$ROOT/logs/gpu-lease-run.$(date +%Y%m%d-%H%M%S).$$.log"

{
  echo "started=$(date -Is)"
  echo "mib=$MIB margin=$MARGIN cpus=$CPUS mem=$MEM_MAX taskset=$TASKSET_CPUS"
  echo "cmd=$*"
} | tee -a "$LOG"

# Retry the 3 s swap window a few times so a single burst does not block a
# job; the threshold is unchanged. Never start during a hot window.
SWAP_RETRIES="${GPU_LEASE_SWAP_RETRIES:-5}"
ok=0
i=1
while [ "$i" -le "$SWAP_RETRIES" ]; do
  if host_ram_ok && swap_window_ok; then
    ok=1
    break
  fi
  echo "swap_guard: admission window $i/$SWAP_RETRIES failed; waiting 5 s" | tee -a "$LOG"
  sleep 5
  i=$((i+1))
done
if [ "$ok" -ne 1 ]; then
  echo "gpu-lease-run: paused by swap/RAM guard after $SWAP_RETRIES windows" | tee -a "$LOG"
  exit 76
fi

ACQ_JSON="$ROOT/work/tmp/lease_acq.$$.json"
/usr/bin/python3 - "$LEASE_PY" "$MIB" "$MARGIN" "$TIMEOUT" "${OWNER:-gpu-lease-run}" "$ACQ_JSON" <<'PY'
import json, sys, importlib.util
lease_py, mib, margin, timeout, owner, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5], sys.argv[6]
spec = importlib.util.spec_from_file_location("gpu_lease", lease_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
info = mod.acquire(mib, owner=owner[:80], margin=margin, timeout=timeout)
open(out, "w").write(json.dumps(info, indent=1))
sys.exit(0 if info.get("admitted") else 75)
PY
acq_rc=$?
tee -a "$LOG" < "$ACQ_JSON"
echo | tee -a "$LOG"
if [ "$acq_rc" -ne 0 ]; then
  echo "gpu-lease-run: lease refused rc=$acq_rc" | tee -a "$LOG"
  exit "$acq_rc"
fi

LEASE_ID="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["lease_id"])' "$ACQ_JSON")"
export QFORGE_GPU_IN_LEASE=1
export QFORGE_GPU_LEASE_ID="$LEASE_ID"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export OMP_NUM_THREADS="$CPUS"
export OPENBLAS_NUM_THREADS="$CPUS"
export MKL_NUM_THREADS="$CPUS"
export NUMEXPR_NUM_THREADS="$CPUS"
export VECLIB_MAXIMUM_THREADS="$CPUS"

release_lease() {
  /usr/bin/python3 - "$LEASE_PY" "$LEASE_ID" <<'PY'
import sys, importlib.util
lease_py, lid = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("gpu_lease", lease_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.release(lid)
PY
}

SCOPE_PID=""
cleanup() {
  local rc=$?
  if [ -n "${SCOPE_PID:-}" ] && kill -0 "$SCOPE_PID" 2>/dev/null; then
    kill -TERM "$SCOPE_PID" 2>/dev/null || true
    sleep 1
    kill -KILL "$SCOPE_PID" 2>/dev/null || true
  fi
  release_lease || true
  echo "released=$LEASE_ID finished=$(date -Is) rc=$rc" | tee -a "$LOG"
}
trap cleanup EXIT INT TERM

PATH="/usr/bin:/bin:$PATH"
set +e
systemd-run --user --scope -q \
  -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 \
  -- /usr/bin/nice -n "$NICE_N" /usr/bin/taskset -c "$TASKSET_CPUS" \
     /usr/bin/env \
       QFORGE_GPU_IN_LEASE=1 \
       QFORGE_GPU_LEASE_ID="$LEASE_ID" \
       CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES" \
       OMP_NUM_THREADS="$CPUS" \
       OPENBLAS_NUM_THREADS="$CPUS" \
       MKL_NUM_THREADS="$CPUS" \
       NUMEXPR_NUM_THREADS="$CPUS" \
       VECLIB_MAXIMUM_THREADS="$CPUS" \
       TMPDIR="$TMPDIR" \
       PATH="$PATH" \
       "$@" &
SCOPE_PID=$!
set -e

/usr/bin/python3 - "$LEASE_PY" "$LEASE_ID" "$SCOPE_PID" <<'PY'
import sys, importlib.util
lease_py, lid, pid = sys.argv[1], sys.argv[2], int(sys.argv[3])
spec = importlib.util.spec_from_file_location("gpu_lease", lease_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.set_cuda_pid(lid, pid)
PY

mon_p=$(awk '/^pswpin /{print $2}' /proc/vmstat)
mon_o=$(awk '/^pswpout /{print $2}' /proc/vmstat)
mon_t=$(date +%s)
cmd_rc=0
while kill -0 "$SCOPE_PID" 2>/dev/null; do
  sleep 3
  if ! kill -0 "$SCOPE_PID" 2>/dev/null; then
    break
  fi
  vmswap_kib="$(awk '/^VmSwap:/{print $2+0}' /proc/$SCOPE_PID/status 2>/dev/null || echo 0)"
  if [ "${vmswap_kib:-0}" -gt 0 ]; then
    echo "swap_guard: our VmSwap=${vmswap_kib} KiB — killing our child only" | tee -a "$LOG"
    kill -TERM "$SCOPE_PID" 2>/dev/null || true
    sleep 2
    kill -KILL "$SCOPE_PID" 2>/dev/null || true
    cmd_rc=77
    break
  fi
  k="$(mem_avail_kib)"
  if [ "$k" -lt $((9 * 1024 * 1024)) ]; then
    echo "swap_guard: MemAvailable=${k} KiB (< 9 GiB) during run — stopping our child" | tee -a "$LOG"
    kill -TERM "$SCOPE_PID" 2>/dev/null || true
    sleep 2
    kill -KILL "$SCOPE_PID" 2>/dev/null || true
    cmd_rc=78
    break
  fi
  now=$(date +%s)
  p=$(awk '/^pswpin /{print $2}' /proc/vmstat)
  o=$(awk '/^pswpout /{print $2}' /proc/vmstat)
  dt=$((now-mon_t))
  if [ "$dt" -ge 3 ]; then
    tot=$(( (p-mon_p) + (o-mon_o) ))
    scaled=$(( tot * 3 / dt ))
    if [ "$scaled" -ge 2000 ]; then
      echo "swap_guard: swap activity ${scaled} pages/3s during run — stopping our child" | tee -a "$LOG"
      kill -TERM "$SCOPE_PID" 2>/dev/null || true
      sleep 2
      kill -KILL "$SCOPE_PID" 2>/dev/null || true
      cmd_rc=79
      break
    fi
    mon_p=$p; mon_o=$o; mon_t=$now
  fi
done

if [ "$cmd_rc" -eq 0 ]; then
  set +e
  wait "$SCOPE_PID"
  cmd_rc=$?
  set -e
fi
SCOPE_PID=""
echo "command_rc=$cmd_rc log=$LOG" | tee -a "$LOG"
exit "$cmd_rc"
