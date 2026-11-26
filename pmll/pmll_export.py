"""Turn a MEMORY.md file and a lab_index.json into a PMLL long-term graph.

The output matches the SQLite tables used by pmll-memory-mcp
(drQedwards/PPM, module pmll_memory_mcp.memory_graph):

    nodes(session_id, id, type, label, content, embedding, created_at,
          last_accessed, access_count, metadata)
    edges(session_id, id, source, target, relation, weight, created_at, metadata)

Node types: concept, file, symbol, note.
Relation types: relates_to, depends_on, implements, references, similar_to, contains.

The JSON also includes the tool-call shapes used by the Python MCP server:

    upsert_memory_node(session_id, type, label, content, metadata?)
    create_memory_relation(session_id, source_id, target_id, relation, weight=1.0)
    set(session_id, key, value)   # short-term silo

create_memory_node is accepted as an alias of upsert_memory_node on import.
Embeddings are left empty so the MCP server (or import_graph) can fill them.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

NODE_TYPES = {"concept", "file", "symbol", "note"}
RELATIONS = {"relates_to", "depends_on", "implements", "references", "similar_to", "contains"}

ENTRY_RE = re.compile(
    r"^##\s+(?:\[(?P<date>[^\]]+)\]\s*)?(?P<title>.+?)\s*$",
    re.M,
)
META_RE = re.compile(r"^(type|tags|id)\s*:\s*(.+)$", re.I)


def parse_memory_md(text: str) -> list[dict[str, Any]]:
    """Parse simple MEMORY.md entries of the form:

        ## [YYYY-MM-DD] short-id
        type: note
        tags: a, b

        Body text...
    """
    lines = text.splitlines()
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    body: list[str] = []
    for line in lines:
        m = re.match(r"^##\s+(?:\[(?P<date>[^\]]+)\]\s*)?(?P<title>.+?)\s*$", line)
        if m:
            if current is not None:
                current["content"] = "\n".join(body).strip()
                entries.append(current)
            current = {
                "id": m.group("title").strip(),
                "label": m.group("title").strip(),
                "date": (m.group("date") or "").strip(),
                "type": "note",
                "tags": [],
            }
            body = []
            continue
        if current is None:
            continue
        meta = META_RE.match(line.strip())
        if meta:
            key = meta.group(1).lower()
            val = meta.group(2).strip()
            if key == "type":
                current["type"] = val if val in NODE_TYPES else "note"
            elif key == "tags":
                current["tags"] = [t.strip() for t in val.split(",") if t.strip()]
            elif key == "id":
                current["id"] = val
            continue
        body.append(line)
    if current is not None:
        current["content"] = "\n".join(body).strip()
        entries.append(current)
    return entries


def _node(node_id: str, typ: str, label: str, content: str, metadata: dict | None = None) -> dict:
    now = time.time()
    return {
        "id": node_id,
        "type": typ if typ in NODE_TYPES else "note",
        "label": label,
        "content": content,
        "embedding": [],
        "created_at": now,
        "last_accessed": now,
        "access_count": 1,
        "metadata": {k: str(v) for k, v in (metadata or {}).items()},
    }


def _edge(edge_id: str, source: str, target: str, relation: str, weight: float = 1.0) -> dict:
    if relation not in RELATIONS:
        raise ValueError("unsupported relation: " + relation)
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "relation": relation,
        "weight": float(weight),
        "created_at": time.time(),
        "metadata": {},
    }


def export(
    memory_md: str | None = None,
    lab_index: dict[str, Any] | None = None,
    session_id: str = "qforge-toolkit-sample",
) -> dict[str, Any]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    short_term: list[dict] = []
    nseq = 0
    eseq = 0

    def nid(prefix: str, slug: str) -> str:
        nonlocal nseq
        nseq += 1
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-")[:48] or "item"
        return f"mn-{prefix}-{safe}-{nseq}"

    def eid() -> str:
        nonlocal eseq
        eseq += 1
        return f"me-{eseq}"

    def add_node(*args, **kwargs):
        node = _node(*args, **kwargs)
        nodes[node["id"]] = node
        return node["id"]

    def add_edge(source, target, relation, weight=1.0):
        if source in nodes and target in nodes:
            edges.append(_edge(eid(), source, target, relation, weight))

    # Root concept for the toolkit itself.
    root = add_node(
        nid("root", "qforge-toolkit"),
        "concept",
        "qforge-toolkit",
        "Reusable lab infrastructure: receipts, ledgers, certified checkers, seals, and a PMLL bridge.",
        {"kind": "toolkit"},
    )
    short_term.append({
        "key": "toolkit:qforge",
        "value": "qforge-toolkit: receipts, ledgers, checkers, seals, PMLL export",
    })

    if memory_md:
        for entry in parse_memory_md(memory_md):
            node_id = add_node(
                nid("mem", entry["id"]),
                entry.get("type") or "note",
                entry["label"],
                entry.get("content") or entry["label"],
                {"date": entry.get("date", ""), "tags": ",".join(entry.get("tags") or [])},
            )
            add_edge(root, node_id, "contains")
            short_term.append({"key": f"memory:{entry['id']}", "value": (entry.get("content") or entry["label"])[:500]})

    if lab_index:
        for seal in lab_index.get("seals") or []:
            name = seal.get("name") or "seal"
            sid = add_node(
                nid("seal", name),
                "file",
                name,
                f"Sealed archive {name}. sha256={seal.get('sha256', '')}",
                {"kind": "seal", "sha256": seal.get("sha256", "")},
            )
            add_edge(root, sid, "contains")
        for card in lab_index.get("cards") or []:
            cid = card.get("id") or "card"
            node_id = add_node(
                nid("card", cid),
                "concept",
                cid,
                card.get("question") or card.get("title") or cid,
                {"kind": "card", "ceiling": card.get("ceiling", ""), "status": card.get("status", "")},
            )
            add_edge(root, node_id, "contains")
        for problem in lab_index.get("open_problems") or []:
            pid = problem.get("id") or "problem"
            node_id = add_node(
                nid("prob", pid),
                "concept",
                pid,
                problem.get("title") or problem.get("question") or pid,
                {"kind": "open_problem", "status": problem.get("status", "open")},
            )
            add_edge(root, node_id, "relates_to")
        for item in lab_index.get("guardrails") or []:
            gid = add_node(
                nid("guard", str(item)[:32]),
                "note",
                "guardrail",
                str(item),
                {"kind": "guardrail"},
            )
            add_edge(root, gid, "contains")

    upsert = [
        {
            "session_id": session_id,
            "type": n["type"],
            "label": n["label"],
            "content": n["content"],
            "metadata": n["metadata"],
            "node_id": n["id"],
        }
        for n in nodes.values()
    ]
    relations = [
        {
            "session_id": session_id,
            "source_id": e["source"],
            "target_id": e["target"],
            "relation": e["relation"],
            "weight": e["weight"],
            "edge_id": e["id"],
        }
        for e in edges
    ]
    sets = [{"session_id": session_id, "key": s["key"], "value": s["value"]} for s in short_term]
    # PyPI pmll-memory-mcp 2.0.4 import_graph expects id-maps (the shape
    # export_graph returns). Later git revisions also accept lists.
    graph = {
        "schema": "pmll-memory-mcp.graph.v1",
        "session_id": session_id,
        "nodes": nodes,
        "edges": {e["id"]: e for e in edges},
        "short_term": short_term,
        "upsert_memory_node": upsert,
        "create_memory_node": upsert,  # alias used in some docs
        "create_memory_relation": relations,
        "create_relation": relations,  # TypeScript / README name
        "set": sets,
    }
    return graph


def _records(field) -> list[dict]:
    if field is None:
        return []
    if isinstance(field, dict):
        return list(field.values())
    return list(field)


def validate_graph(graph: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if graph.get("schema") != "pmll-memory-mcp.graph.v1":
        problems.append("missing or unknown schema")
    ids = set()
    for node in _records(graph.get("nodes")):
        for key in ("id", "type", "label", "content"):
            if key not in node:
                problems.append(f"node missing {key}")
        if node.get("type") not in NODE_TYPES:
            problems.append(f"bad node type {node.get('type')}")
        if node.get("id") in ids:
            problems.append("duplicate node id " + str(node.get("id")))
        ids.add(node.get("id"))
    for edge in _records(graph.get("edges")):
        if edge.get("relation") not in RELATIONS:
            problems.append("bad relation " + str(edge.get("relation")))
        if edge.get("source") not in ids or edge.get("target") not in ids:
            problems.append("edge endpoint not in nodes: " + str(edge.get("id")))
    return problems


def load_and_export(
    memory_path: Path | None,
    index_path: Path | None,
    session_id: str,
) -> dict[str, Any]:
    memory = memory_path.read_text(encoding="utf-8") if memory_path else None
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path else None
    return export(memory, index, session_id=session_id)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export MEMORY.md + lab_index.json to a PMLL graph JSON.")
    ap.add_argument("--memory", default=None, help="path to MEMORY.md")
    ap.add_argument("--index", default=None, help="path to lab_index.json")
    ap.add_argument("--session-id", default="qforge-toolkit-sample")
    ap.add_argument("--out", default=None, help="write JSON to this path")
    a = ap.parse_args(argv)
    graph = load_and_export(
        Path(a.memory) if a.memory else None,
        Path(a.index) if a.index else None,
        a.session_id,
    )
    problems = validate_graph(graph)
    if problems:
        print(json.dumps({"status": "FAIL", "problems": problems}, indent=1))
        return 1
    text = json.dumps(graph, indent=2, sort_keys=True) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(json.dumps({"status": "OK", "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "out": a.out}))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
