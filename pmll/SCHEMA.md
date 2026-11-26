# PMLL graph schema used by this exporter

Grounded in the Python server at `mcp/pmll_memory_mcp/` in [drQedwards/PPM](https://github.com/drQedwards/PPM)
(and the `pmll-memory-mcp` package). The TypeScript server uses slightly shorter tool names; both are emitted.

## SQLite tables

```
nodes (
    session_id    TEXT NOT NULL,
    id            TEXT NOT NULL,
    type          TEXT NOT NULL,   -- concept | file | symbol | note
    label         TEXT NOT NULL,
    content       TEXT NOT NULL,
    embedding     TEXT NOT NULL,   -- JSON list of floats
    created_at    REAL NOT NULL,
    last_accessed REAL NOT NULL,
    access_count  INTEGER NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (session_id, id)
);

edges (
    session_id TEXT NOT NULL,
    id         TEXT NOT NULL,
    source     TEXT NOT NULL,
    target     TEXT NOT NULL,
    relation   TEXT NOT NULL,      -- relates_to | depends_on | implements
                                   -- | references | similar_to | contains
    weight     REAL NOT NULL,
    created_at REAL NOT NULL,
    metadata   TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (session_id, id)
);
```

## Long-term MCP tools (Python names)

- `upsert_memory_node(session_id, type, label, content, metadata?)`
- `create_memory_relation(session_id, source_id, target_id, relation, weight=1.0)`

README / TypeScript aliases: `create_memory_node` (treated as upsert), `create_relation`.

## Short-term silo

- `set(session_id, key, value)` stores a key/content pair, mirroring `memory_silo_t`.

The exporter writes a JSON object that `memory_graph.import_graph(session_id, data)` can load
(the `nodes` and `edges` fields are id-maps, the shape PyPI 2.0.4 `export_graph` / `import_graph` uses). Embeddings may be
empty; `import_graph` will fill them from label+content when they are missing.
