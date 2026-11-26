"""
RFC 6962 Domain-Separated SHA-256 Merkle Proof Manifest & Public GitHub Hygiene Scanner
=======================================================================================
Implements:
  1. `drQedwards/pmll` (`docs/SAT-PROOF-MANIFEST.md` & `pmll-anchor`) 32-byte Merkle root
     commitment (`SHA256(0x00 || leaf)` and `SHA256(0x01 || left || right)`) with O(log N)
     audit-path generation and tamper/second-preimage verification.
  2. Pre-push GitHub repository hygiene scanner enforcing zero leaked machine paths,
     zero forbidden binary blobs, zero bare `assert`s in verifier scripts, and honest
     `clay_proof == 0` / `FINITE_EXPERIMENT == True` receipt metadata.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(f"Merkle/Hygiene invariant violation: {msg}")


def rfc6962_leaf_hash(data: bytes) -> bytes:
    """RFC 6962 §2.1 Leaf Hash: `SHA-256(0x00 || data)`."""
    return hashlib.sha256(b"\x00" + data).digest()


def rfc6962_node_hash(left: bytes, right: bytes) -> bytes:
    """RFC 6962 §2.1 Interior Node Hash: `SHA-256(0x01 || left || right)`."""
    return hashlib.sha256(b"\x01" + left + right).digest()


def rfc6962_root_and_audit_path(
    leaves: Sequence[bytes], target_idx: int
) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Computes the 32-byte RFC 6962 Merkle Tree Hash (hex) and the O(log N) inclusion
    audit path `[(side, sibling_hex), ...]` bottom-up for `leaves[target_idx]`.
    """
    n = len(leaves)
    require(n >= 1 and 0 <= target_idx < n, "Invalid leaf count or target_idx")

    def _build(lo: int, hi: int, idx: Optional[int]) -> Tuple[bytes, List[Tuple[str, str]]]:
        m = hi - lo
        if m == 1:
            return rfc6962_leaf_hash(leaves[lo]), []
        k = 1 << ((m - 1).bit_length() - 1)
        if idx is None:
            lh, _ = _build(lo, lo + k, None)
            rh, _ = _build(lo + k, hi, None)
            return rfc6962_node_hash(lh, rh), []
        if idx < lo + k:
            lh, path = _build(lo, lo + k, idx)
            rh, _ = _build(lo + k, hi, None)
            return rfc6962_node_hash(lh, rh), path + [("R", rh.hex())]
        lh, _ = _build(lo, lo + k, None)
        rh, path = _build(lo + k, hi, idx)
        return rfc6962_node_hash(lh, rh), path + [("L", lh.hex())]

    root_bytes, audit_path = _build(0, n, target_idx)
    return root_bytes.hex(), audit_path


def verify_rfc6962_inclusion(
    leaf_data: bytes,
    audit_path: Sequence[Tuple[str, str]],
    expected_root_hex: str,
) -> bool:
    """Verifies an RFC 6962 audit path against `expected_root_hex`."""
    if len(expected_root_hex) != 64:
        return False
    cur = rfc6962_leaf_hash(leaf_data)
    for side, sib_hex in audit_path:
        if len(sib_hex) != 64 or side not in ("L", "R"):
            return False
        try:
            sib = bytes.fromhex(sib_hex)
        except ValueError:
            return False
        cur = rfc6962_node_hash(cur, sib) if side == "R" else rfc6962_node_hash(sib, cur)
    return cur.hex() == expected_root_hex.lower()


def build_directory_merkle_manifest(
    target_dir: Path,
    glob_pattern: str = "**/*",
    exclude_names: Sequence[str] = (".__pycache__", "__pycache__", ".git", ".pytest_cache", ".build_tmp"),
) -> Dict[str, object]:
    """
    Anchors all regular files under `target_dir` into a deterministic RFC 6962 Merkle manifest
    ready for 32-byte `CodeworkPayload` commitment (`drQedwards/pmll-anchor` compatible).
    """
    files: List[Path] = []
    for p in sorted(target_dir.glob(glob_pattern)):
        if not p.is_file():
            continue
        if any(part in exclude_names for part in p.parts):
            continue
        files.append(p)
    require(len(files) > 0, f"No files matched under {target_dir}")

    rel_entries: List[Dict[str, object]] = []
    leaf_payloads: List[bytes] = []
    for p in files:
        rel = p.relative_to(target_dir).as_posix()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        leaf_bytes = f"{rel}:{digest}".encode("utf-8")
        leaf_payloads.append(leaf_bytes)
        rel_entries.append({"path": rel, "sha256": digest, "bytes": p.stat().st_size})

    root_hex, sample_proof = rfc6962_root_and_audit_path(leaf_payloads, target_idx=0)
    ok_sample = verify_rfc6962_inclusion(leaf_payloads[0], sample_proof, root_hex)
    require(ok_sample, "Sample inclusion proof failed self-check")

    return {
        "protocol": "RFC-6962-SHA256",
        "anchor_compatibility": "drQedwards/pmll-anchor CodeworkPayload (32-byte root)",
        "file_count": len(files),
        "merkle_root_hex": root_hex,
        "sample_leaf_0": rel_entries[0]["path"],
        "sample_proof_0": sample_proof,
        "entries": rel_entries,
    }


# ===========================================================================
# Pre-Push Public GitHub Hygiene Scanner
# ===========================================================================
_PRIVATE_PATH_PATTERNS = (
    # Concatenated prefixes so this file itself never triggers literal self-match if scanned naively
    re.compile(r"/" + r"working_dir/[A-Za-z0-9_-]+"),
    re.compile(r"/" + r"home/[A-Za-z0-9_.-]+/"),
    re.compile(r"/" + r"Users/[A-Za-z0-9_.-]+/"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)

_FORBIDDEN_BINARY_SUFFIXES = {
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".olean",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".cubin",
    ".fatbin",
}


def scan_repo_hygiene(
    repo_root: Path,
    max_file_bytes: int = 1_000_000,
) -> Dict[str, object]:
    """
    Audits `repo_root` before `git push`:
      1. Rejects leaked private paths (`/working_dir/<id>`, `/home/<user>/`, `/Users/<user>/`) or API tokens.
      2. Rejects forbidden binary/cache extensions (`.so`, `.olean`, `.npy`, etc.) or files > `max_file_bytes`.
      3. Rejects bare `assert` statements inside `verify_*.py` / `*verifier*.py` scripts (`python3 -O` hazard).
      4. Checks `*RECEIPT*.json` files for `"FINITE_EXPERIMENT": true` and `"clay_proof": 0`.
    """
    violations: List[str] = []
    scanned_files = 0

    for p in sorted(repo_root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in (".git", "__pycache__", ".pytest_cache", ".build_tmp") for part in p.parts):
            continue
        scanned_files += 1
        rel = p.relative_to(repo_root).as_posix()
        sz = p.stat().st_size

        if sz > max_file_bytes:
            violations.append(f"{rel}: size {sz} B exceeds {max_file_bytes} B cap")
        if p.suffix.lower() in _FORBIDDEN_BINARY_SUFFIXES:
            violations.append(f"{rel}: forbidden binary/cache suffix '{p.suffix}'")

        # Text inspection for source/docs/json files
        if p.suffix.lower() in {".py", ".c", ".h", ".cu", ".cpp", ".lean", ".md", ".json", ".yml", ".yaml", ".toml"}:
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                violations.append(f"{rel}: non-UTF-8 text file")
                continue

            for pat in _PRIVATE_PATH_PATTERNS:
                m = pat.search(text)
                if m:
                    violations.append(f"{rel}: leaked private path or token pattern '{m.group(0)}'")

            # Check verifier Python scripts for bare `assert` statements
            if p.suffix.lower() == ".py" and ("verify_" in p.name or "verifier" in p.name):
                try:
                    tree = ast.parse(text, filename=rel)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Assert):
                            violations.append(
                                f"{rel}:{node.lineno}: bare `assert` in verifier (stripped under `python3 -O`)"
                            )
                except SyntaxError as exc:
                    violations.append(f"{rel}: Python syntax error: {exc}")

            # Check receipt JSONs for honest scope metadata
            if p.suffix.lower() == ".json" and "RECEIPT" in p.name.upper():
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        if obj.get("FINITE_EXPERIMENT") is not True:
                            violations.append(f"{rel}: missing `FINITE_EXPERIMENT: true`")
                        if obj.get("clay_proof") != 0:
                            violations.append(f"{rel}: `clay_proof` must equal `0`")
                except json.JSONDecodeError as exc:
                    violations.append(f"{rel}: invalid JSON: {exc}")

    return {
        "clean": len(violations) == 0,
        "scanned_files": scanned_files,
        "violation_count": len(violations),
        "violations": violations,
    }
