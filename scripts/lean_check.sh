#!/bin/bash
# lean_check.sh — compile a Lean file with an isolated Lean 4.36 toolchain,
# print axioms, and run nanoda_bin (second kernel) with positive and
# negative-control axiom sets.
#
# Does not install anything into ~/.elan. Does not use /tmp. Does not run sudo.
# Required: ELAN436_HOME (isolated elan home). Optional: LEAN436_DEFAULT_LAKE,
# LEAN436_TOOLCHAIN, LEAN436_MEMORY_MAX, LEAN436_NUM_THREADS, LEAN436_TIMEOUT,
# LEAN436_OUT, LEAN436_TMP, LEAN436_ALLOW_NANODA_SKIP.
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null; then
  SCRIPT_PATH="$(readlink -f "$SCRIPT_PATH" 2>/dev/null || echo "$SCRIPT_PATH")"
fi
ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
# Isolated toolchain: set ELAN436_HOME to a Lean 4.36.0 elan home that you
# already have. This script never installs into ~/.elan.
MEM_MAX="${LEAN436_MEMORY_MAX:-6G}"
LEAN_NUM_THREADS="${LEAN436_NUM_THREADS:-1}"
TIMEOUT_SEC="${LEAN436_TIMEOUT:-1800}"
DEFAULT_LAKE="${LEAN436_DEFAULT_LAKE:-}"

usage() {
  cat <<'EOF'
Usage: lean_check.sh [--dir LAKE_DIR] [--out OUT_DIR] FILE.lean [FILE.lean ...]

Runs the isolated Lean 4.36.0 toolchain (commit 611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9)
plus Mathlib fc4f59e577feb1a4956671bc04ac18aaaf8cd842 when --dir points at a lake
project (auto-detected if the file lives inside one).

For each file:
  1. systemd-run --user --scope MemoryMax (default 6G) MemorySwapMax=0
  2. `lake env lean FILE` if a lake project is selected, otherwise `lean FILE`
  3. captures `#print axioms` lines (add `#print axioms <decl>` in the file)
  4. leanexport + nanoda_bin with permitted axioms
     {propext, Classical.choice, Quot.sound} and two negative controls

Return codes (per run; last failing file wins):
  0 compiled, no sorry, axioms within {propext, Classical.choice, Quot.sound}, nanoda accepted
  1 nanoda rejected (pos) / bad args / missing file;  2 usage;  124 timeout;  other = Lean's own rc (compile error)
  3 sorry (Lean itself exits 0 on sorry);  4 non-standard axiom (e.g. sorryAx, Lean.ofReduceBool, user axiom)
  5 second kernel skipped (olean/export failed), unless LEAN436_ALLOW_NANODA_SKIP=1
Files outside any lake project that `import Mathlib` use LEAN436_DEFAULT_LAKE (set this to a Mathlib lake root).

Environment:
  ELAN436_HOME, LEAN436_MEMORY_MAX, LEAN436_NUM_THREADS, LEAN436_TIMEOUT, LEAN436_DEFAULT_LAKE, LEAN436_ALLOW_NANODA_SKIP
EOF
}

LAKE_DIR=""
OUT_DIR="${LEAN436_OUT:-$ROOT/work/lean-check}"

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dir) LAKE_DIR="${2:?}"; shift 2 ;;
    --out) OUT_DIR="${2:?}"; shift 2 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) break ;;
  esac
done

if [ $# -lt 1 ]; then usage >&2; exit 2; fi

if [ -z "${ELAN436_HOME:-}" ]; then
  echo "lean_check: set ELAN436_HOME to an isolated Lean 4.36 elan home" >&2
  echo "  (toolchains/leanprover--lean4---v4.36.0 must exist under it)." >&2
  exit 2
fi
ELAN_HOME="$ELAN436_HOME"
TC="${LEAN436_TOOLCHAIN:-$ELAN_HOME/toolchains/leanprover--lean4---v4.36.0}"


if [ ! -x "$TC/bin/lean" ] || [ ! -x "$TC/bin/lake" ] || [ ! -x "$TC/bin/nanoda_bin" ]; then
  echo "lean_check: isolated toolchain missing under $TC" >&2
  exit 1
fi

mkdir -p "$OUT_DIR" "${LEAN436_TMP:-$OUT_DIR/tmp}" "${LEAN436_LOGDIR:-$OUT_DIR/logs}"
# 2026-11-26 fix: make OUT_DIR absolute (the olean/export steps cd into the lake dir).
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
export ELAN_HOME
export ELAN_OFFLINE=1
export TMPDIR="${LEAN436_TMP:-$OUT_DIR/tmp}"
export LEAN_NUM_THREADS
export PATH="$TC/bin:$ELAN_HOME/bin:/usr/bin:/bin"

# Prefer isolated toolchain binaries, never the shared ~/.elan default
# (shared default resolves to 4.36.0 but that toolchain is not installed there).
LEAN="$TC/bin/lean"
LAKE="$TC/bin/lake"
LEANEXPORT="$TC/bin/leanexport"
NANODA="$TC/bin/nanoda_bin"

find_lake_dir() {
  local d
  d="$(cd "$(dirname "$1")" && pwd)"
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    if [ -f "$d/lakefile.toml" ] || [ -f "$d/lakefile.lean" ]; then
      echo "$d"
      return 0
    fi
    d="$(dirname "$d")"
  done
  return 1
}

scope_run() {
  systemd-run --user --scope -q \
    -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 \
    -- /usr/bin/env PATH="$PATH" ELAN_HOME="$ELAN_HOME" ELAN_OFFLINE=1 \
       TMPDIR="$TMPDIR" LEAN_NUM_THREADS="$LEAN_NUM_THREADS" \
       timeout --signal=TERM "$TIMEOUT_SEC" "$@"
}

run_one() {
  local src abs name stem log rc compile_cmd lake_used
  local t0 t1 workd olean_rc export_rc export_path neg AX cfg l nrc anyfail
  src="$1"
  if [ ! -f "$src" ]; then
    echo "lean_check: not a file: $src" >&2
    return 1
  fi
  abs="$(cd "$(dirname "$src")" && pwd)/$(basename "$src")"
  name="$(basename "$abs")"
  stem="${name%.lean}"
  log="$OUT_DIR/lean436_${stem}.log"
  : > "$log"

  lake_used=""
  if [ -n "$LAKE_DIR" ]; then
    lake_used="$(cd "$LAKE_DIR" && pwd)"
  else
    lake_used="$(find_lake_dir "$abs" || true)"
  fi
  # A file outside any lake project that imports Mathlib is compiled against LEAN436_DEFAULT_LAKE.
  if [ -z "$lake_used" ] && grep -qE '^[[:space:]]*import[[:space:]]+Mathlib' "$abs"; then
    if [ -z "$DEFAULT_LAKE" ]; then
      echo "lean_check: file imports Mathlib but LEAN436_DEFAULT_LAKE is unset" >&2
      return 2
    fi
    lake_used="$DEFAULT_LAKE"
    echo "lake_dir_source=DEFAULT (file outside any lake project)" >> "$log"
  fi

  {
    echo "file=$abs"
    echo "elan_home=$ELAN_HOME"
    echo "toolchain=$TC"
    echo "lean_version=$($LEAN --version)"
    echo "lake_dir=${lake_used:-NONE}"
    echo "started=$(date -Is)"
  } >> "$log"

  if grep -qE '^[[:space:]]*#print[[:space:]]+axioms' "$abs"; then
    echo "print_axioms_in_file=yes" >> "$log"
  else
    echo "print_axioms_in_file=no (add #print axioms <decl> to see axiom lists)" >> "$log"
  fi

  t0="$(date +%s)"
  set +e
  if [ -n "$lake_used" ]; then
    ( cd "$lake_used" && scope_run "$LAKE" env lean "$abs" ) >> "$log" 2>&1
    rc=$?
    compile_cmd="lake env lean"
  else
    scope_run "$LEAN" "$abs" >> "$log" 2>&1
    rc=$?
    compile_cmd="lean"
  fi
  set -e
  t1="$(date +%s)"
  echo "compile_cmd=$compile_cmd rc=$rc wall_s=$((t1-t0))" >> "$log"

  if grep -qE 'print axioms|depend.*axioms|axioms :' "$log"; then
    echo "axiom_lines=yes" >> "$log"
  else
    echo "axiom_lines=no (compile failed or file has no #print axioms)" >> "$log"
  fi

  if [ "$rc" -ne 0 ]; then
    echo "LEAN_FAIL $name rc=$rc log=$log"
    return "$rc"
  fi

  # 2026-11-26 fix: lean exits 0 on sorry; gate on sorry and on non-standard axioms.
  if grep -qE "declaration uses ['\`]sorry['\`]|sorryAx" "$log"; then
    echo "gate=SORRY" >> "$log"
    echo "LEAN_SORRY $name log=$log"
    return 3
  fi
  local badax
  badax="$(grep -oE 'depends on axioms: \[[^]]*\]' "$log" | sed -E 's/.*\[(.*)\]/\1/' | tr ',' '\n' | sed 's/^ *//;s/ *$//' | grep -vxE 'propext|Classical.choice|Quot.sound|' | sort -u | tr '\n' ' ' || true)"
  if [ -n "$badax" ]; then
    echo "gate=BAD_AXIOMS $badax" >> "$log"
    echo "LEAN_BAD_AXIOMS $name [$badax] log=$log"
    return 4
  fi
  echo "gate=OK (no sorry; axioms subset of propext,Classical.choice,Quot.sound)" >> "$log"

  workd="$OUT_DIR/${stem}_nanoda"
  mkdir -p "$workd"
  export_path="$workd/${stem}.export"
  t0="$(date +%s)"
  set +e
  local lp=""
  if [ -n "$lake_used" ]; then lp="$(cd "$lake_used" && "$LAKE" env printenv LEAN_PATH 2>/dev/null || true)"; fi
  if [ -n "$lake_used" ] && [ "${abs#"$lake_used"/}" != "$abs" ]; then
    ( cd "$lake_used" && scope_run "$LAKE" env "$LEAN" -o "$workd/${stem}.olean" "$abs" ) > "$workd/compile_olean.log" 2>&1
  elif [ -n "$lake_used" ]; then
    # 2026-11-26 (t265u): file outside the lake root. `lean -o` needs the file under its root dir, so compile from the
    # file's own directory with the lake project's LEAN_PATH (Mathlib oleans); module name = file stem.
    ( cd "$(dirname "$abs")" && export LEAN_PATH="$lp" && scope_run "$LEAN" -o "$workd/${stem}.olean" "$abs" ) > "$workd/compile_olean.log" 2>&1
  else
    scope_run "$LEAN" -o "$workd/${stem}.olean" "$abs" > "$workd/compile_olean.log" 2>&1
  fi
  olean_rc=$?
  if [ "$olean_rc" -eq 0 ]; then
    # leanexport searches LEAN_PATH for stem.olean; include the work dir.
    # Export only declarations from the source file so we do not dump the
    # entire prelude (that would declare sorryAx and fail nanoda hard-error).
    decls=$(awk '/^(theorem|lemma|def|axiom|example)[ \t]/{print $2}' "$abs" | tr -d ':')
    if [ -z "$decls" ]; then
      echo "no declarations parsed from $abs for leanexport" > "$workd/export.err"
      export_rc=1
    else
      echo "export_decls=$decls" >> "$log"
      # 2026-11-26 fix: give leanexport the lake project's LEAN_PATH (Mathlib), else export fails on 'Mathlib' imports.
      ( cd "$workd" && export LEAN_PATH="$workd${lp:+:$lp}${LEAN_PATH:+:$LEAN_PATH}" && scope_run "$LEANEXPORT" "$stem" -- $decls ) > "$export_path" 2>"$workd/export.err"
      export_rc=$?
    fi
  else
    export_rc=1
  fi
  set -e
  echo "olean_rc=$olean_rc export_rc=$export_rc export_bytes=$(wc -c < "$export_path" 2>/dev/null || echo 0)" >> "$log"

  if [ "$olean_rc" -ne 0 ] || [ "$export_rc" -ne 0 ] || [ ! -s "$export_path" ]; then
    echo "nanoda=SKIP" >> "$log"
    echo "LEAN_OK_NANODA_SKIP $name (export failed) log=$log"
    # 2026-11-26: a skipped second kernel is a failure unless explicitly allowed.
    if [ "${LEAN436_ALLOW_NANODA_SKIP:-0}" = 1 ]; then return 0; fi
    return 5
  fi

  anyfail=0
  for neg in pos neg_noClassical neg_noPropext; do
    case "$neg" in
      pos) AX='["propext","Classical.choice","Quot.sound"]' ;;
      neg_noClassical) AX='["propext","Quot.sound"]' ;;
      neg_noPropext) AX='["Classical.choice","Quot.sound"]' ;;
    esac
    cfg="$workd/nanoda_${neg}.json"
    l="$workd/nanoda_${neg}.log"
    printf '%s\n' "{\"use_stdin\":false,\"export_file_path\":\"$export_path\",\"permitted_axioms\":$AX,\"unpermitted_axiom_hard_error\":true,\"num_threads\":4,\"nat_extension\":true,\"string_extension\":true}" > "$cfg"
    set +e
    ( t2="$(date +%s)"; scope_run "$NANODA" "$cfg"; nrc=$?; echo "wall_s=$(( $(date +%s) - t2 ))"; exit "$nrc" ) > "$l" 2>&1
    nrc=$?
    set -e
    echo "nanoda_$neg rc=$nrc" >> "$log"
    if [ "$neg" = pos ] && [ "$nrc" -ne 0 ]; then
      anyfail=1
    fi
  done

  # 2026-11-26: negative controls must reject when the decls use the dropped axiom; record only.
  echo "finished=$(date -Is)" >> "$log"
  if [ "$anyfail" -ne 0 ]; then
    echo "NANODA_POS_FAIL $name log=$log"
    return 1
  fi
  echo "LEAN_OK_NANODA_OK $name log=$log"
  grep -E 'print axioms|depend.*axioms|axioms :' "$log" || true
  return 0
}

overall=0
for f in "$@"; do
  # 2026-11-26: propagate the per-file code (3 sorry, 4 bad axioms, 5 nanoda skip, 1 other).
  run_one "$f" && r=0 || r=$?
  if [ "$r" -ne 0 ]; then overall=$r; fi
done
exit "$overall"
