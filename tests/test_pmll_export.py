
import json
from pathlib import Path

from pmll.pmll_export import export, load_and_export, parse_memory_md, validate_graph

ROOT = Path(__file__).resolve().parents[1]


def test_sample_export_validates():
    graph = load_and_export(ROOT / "samples" / "MEMORY.md", ROOT / "samples" / "lab_index.json", "sample")
    problems = validate_graph(graph)
    assert problems == [], problems
    assert graph["nodes"]
    assert graph["edges"]
    assert isinstance(graph["nodes"], dict) and isinstance(graph["edges"], dict)
    assert graph["upsert_memory_node"]
    assert graph["create_memory_relation"]
    assert graph["set"]
    types = {n["type"] for n in graph["nodes"].values()}
    assert types <= {"concept", "file", "symbol", "note"}
    rels = {e["relation"] for e in graph["edges"].values()}
    assert rels <= {"relates_to", "depends_on", "implements", "references", "similar_to", "contains"}


def test_parse_memory_and_empty_inputs():
    entries = parse_memory_md((ROOT / "samples" / "MEMORY.md").read_text())
    assert any(e["id"] == "speedgate-rule" for e in entries)
    graph = export(None, None, session_id="empty")
    assert validate_graph(graph) == []
    # at least the root concept
    assert any(n["label"] == "qforge-toolkit" for n in graph["nodes"].values())


def test_import_into_pmll_memory_mcp(tmp_path: Path):
    pytest = __import__("pytest")
    try:
        from pmll_memory_mcp.memory_graph import (
            configure_db,
            import_graph,
            get_graph_stats,
            clear_graph,
        )
    except ImportError:
        pytest.skip("pmll-memory-mcp is not installed")
    graph = load_and_export(ROOT / "samples" / "MEMORY.md", ROOT / "samples" / "lab_index.json", "sample")
    db = tmp_path / "memory_graph.sqlite3"
    configure_db(str(db))
    import_graph("sample", {"nodes": graph["nodes"], "edges": graph["edges"]})
    stats = get_graph_stats("sample")
    assert stats["nodes"] == len(graph["nodes"])
    assert stats["edges"] == len(graph["edges"])
    # Also exercise the tool-shaped upsert/relation path is consistent
    assert len(graph["upsert_memory_node"]) == stats["nodes"]
    clear_graph("sample")
