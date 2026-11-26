"""Seal a directory into a tamper-evident archive, then independently receipt it.

Steps: copy into staging (never seal the live tree) -> replace home prefixes
with `~` in text files -> leak-scan for private-key headers and common token
shapes -> MANIFEST and SHA256SUMS -> tar.gz under a size cap -> retained
extract -> optional delivery (refuse overwrite) -> a fresh-extract receipt
and optional replay command. Scratch lives under the output directory, never
in a shared temporary filesystem. Nothing is deleted with rm.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import time
from pathlib import Path
from typing import Iterable

TEXT_SUFFIX = {".json", ".jsonl", ".log", ".md", ".txt", ".sh", ".py", ".c", ".cu",
               ".h", ".cc", ".toml", ".cfg", ".csv", ".yml", ".yaml", ".lean"}
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_SUFFIX = {".so", ".pyc", ".o"}
LEAK_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abps]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
]
# emails are optional extras the caller can add; default leak scan stays
# on tokens and keys so example docs can mention public no-reply addresses.


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skip(rel: Path) -> bool:
    return any(part in SKIP_DIRS for part in rel.parts) or rel.suffix in SKIP_SUFFIX


def copy_tree(src: Path, dst: Path, exclude: Iterable[str] = ()) -> int:
    n = 0
    exclude = tuple(exclude)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if _skip(rel) or any(rel.as_posix().startswith(e) for e in exclude):
            continue
        if path.is_file():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            n += 1
    return n


def scrub_home_paths(root: Path, home: str | None = None) -> int:
    home = home or str(Path.home())
    replaced = 0
    if not home:
        return 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIX:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if home in text:
            path.write_text(text.replace(home, "~"), encoding="utf-8")
            replaced += text.count(home)
    return replaced


def leak_scan(root: Path, extra_patterns: Iterable[str] = ()) -> list[dict]:
    pats = list(LEAK_PATTERNS) + [re.compile(p) for p in extra_patterns]
    hits = []
    for path in root.rglob("*"):
        if not path.is_file() or _skip(path.relative_to(root)):
            continue
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        for pat in pats:
            if pat.search(text):
                hits.append({"path": str(path.relative_to(root)), "pattern": pat.pattern})
    return hits


def _write_manifest(root: Path) -> None:
    files = [p for p in sorted(root.rglob("*")) if p.is_file() and p.name not in {"MANIFEST.json", "SHA256SUMS"}]
    manifest = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": sha_file(p)} for p in files]
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    lines = [f"{sha_file(p)}  {p.relative_to(root).as_posix()}" for p in files]
    (root / "SHA256SUMS").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _pack(src: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz") as tar:
        # The archive contains a top-level directory named after the seal.
        tar.add(src, arcname=src.name, filter=lambda info: info)


def _verify_sums(root: Path) -> list[str]:
    bad = []
    sums = root / "SHA256SUMS"
    if not sums.exists():
        return ["missing SHA256SUMS"]
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        path = root / rel
        if not path.is_file() or sha_file(path) != digest:
            bad.append(rel)
    return bad


def seal(
    name: str,
    src: Path,
    outdir: Path,
    *,
    max_bytes: int = 50_000_000,
    deliver_to: Iterable[Path] = (),
    exclude: Iterable[str] = (),
    extra_leak_patterns: Iterable[str] = (),
    provenance: dict | None = None,
    work_home: str | None = None,
) -> dict:
    src = Path(src)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    staging = outdir / "staging" / name
    archive = outdir / (name + ".tgz")
    if staging.exists() or archive.exists():
        raise FileExistsError("refuse: staging or archive already exists")
    staging.mkdir(parents=True)
    copy_tree(src, staging, exclude=exclude)
    (staging / "PROVENANCE.json").write_text(
        json.dumps({
            "name": name,
            "sealed_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "source_name": src.name,
            **(provenance or {}),
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    replaced = scrub_home_paths(staging, home=work_home)
    hits = leak_scan(staging, extra_patterns=extra_leak_patterns)
    if hits:
        raise ValueError("leak scan failed: " + json.dumps(hits))
    _write_manifest(staging)
    raw = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
    if raw >= max_bytes:
        raise ValueError(f"staged size {raw} exceeds cap {max_bytes}")
    _pack(staging, archive)
    digest = sha_file(archive)
    (outdir / (name + ".tgz.sha256")).write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    retained = outdir / f"retained-clean-extract-{name}"
    retained.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(retained, filter="data")
    inner_bad = _verify_sums(retained / name)
    if inner_bad:
        raise ValueError("retained extract hash mismatch: " + ",".join(inner_bad))
    deliveries = {}
    for dest in deliver_to:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / archive.name
        if target.exists():
            raise FileExistsError("refuse overwrite: " + str(target))
        shutil.copy2(archive, target)
        shutil.copy2(outdir / (name + ".tgz.sha256"), dest / (name + ".tgz.sha256"))
        deliveries[str(dest)] = sha_file(target) == digest
    result = {
        "name": name,
        "archive": str(archive),
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "home_paths_replaced": replaced,
        "deliveries": deliveries,
        "retained": str(retained / name),
    }
    (outdir / f"DELIVERY_{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def receipt(
    name: str,
    outdir: Path,
    *,
    replay: list[str] | None = None,
    hide_cuda: bool = True,
) -> dict:
    outdir = Path(outdir)
    archive = outdir / (name + ".tgz")
    want = (outdir / (name + ".tgz.sha256")).read_text(encoding="utf-8").split()[0]
    scratch = outdir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    extract = scratch / f"{name}_receipt"
    extract.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(extract / "x", filter="data")
    root = extract / "x" / name
    bad = _verify_sums(root)
    replay_status = None
    if replay:
        env = os.environ.copy()
        if hide_cuda:
            env["CUDA_VISIBLE_DEVICES"] = ""
        import subprocess
        proc = subprocess.run(replay, cwd=root, env=env, capture_output=True, text=True)
        replay_status = {"rc": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    rec = {
        "schema": "qforge.seal-receipt.v1",
        "archive": archive.name,
        "archive_sha256": want,
        "work_copy_ok": sha_file(archive) == want,
        "inner_hashes": "OK" if not bad else "FAIL " + ",".join(bad),
        "replay": replay_status,
        "status": "PASS" if (not bad and sha_file(archive) == want and (replay_status is None or replay_status["rc"] == 0)) else "FAIL",
    }
    rec_path = outdir / f"{name}_REPLAY_RECEIPT.json"
    rec_path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (outdir / f"{name}_REPLAY_RECEIPT.json.sha256").write_text(
        sha_file(rec_path) + "  " + rec_path.name + "\n", encoding="utf-8"
    )
    (outdir / f"{name}.RECEIPT_DONE").write_text(rec["status"] + "\n", encoding="utf-8")
    return rec
