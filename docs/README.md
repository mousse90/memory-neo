# memory-neo/docs/README.md

# Path: docs/README.md

# Purpose: User-facing documentation — install, usage, deployment

# 🧠 memory-neo

Push your codebase to a graph database. Query it with natural language.

```bash
pip install memory-neo
cd your-project/
memory-neo push
memory-neo query "show all auth functions"
memory-neo context parse_directory
```

---

## How it works

1. **Push** — `memory-neo push` scans your project, extracts files and Python functions via AST, and sends the structure to a hosted Memgraph graph database.
2. **Query** — `memory-neo query "..."` converts your question to Cypher via Claude, runs it against your graph, and prints results with code highlighting.
3. **Context** — `memory-neo context <name>` fetches a function or file as prompt-ready code you can paste into any LLM.

---

## Install

```bash
pip install memory-neo
```

Python 3.9+ required.

---

## Authentication

Get an API key at [memory-neo.dev](https://memory-neo.dev), then:

```bash
memory-neo login
# Paste your API key when prompted
# Saved to ~/.memoryneo/config.json
```

---

## Commands

### `memory-neo push`

Scan the current directory and push its structure to Memgraph.

```bash
memory-neo push                        # use directory name as project name
memory-neo push my-project             # explicit project name
memory-neo push --dir ./src            # scan a subdirectory
memory-neo push --dry-run              # scan only, don't push
```

What gets indexed:

- Files: `.py` `.js` `.jsx` `.ts` `.tsx` `.html` `.md` `.txt`
- Python: full AST extraction — function names, line numbers, args, docstrings, code
- Other: file name, path, content, line count

Ignored by default (via `memIgnore`):

- `.venv/`, `node_modules/`, `__pycache__/`, `.git/`, `*.pyc`, `.env`, and more

Custom ignore: place a `memIgnore` file in your project root (same syntax as `.gitignore`).

---

### `memory-neo query`

Ask a natural language question about your indexed codebase.

```bash
memory-neo query "show all auth functions"
memory-neo query "which files import httpx"
memory-neo query "list all Python files"
memory-neo query "how many functions are in each file"
memory-neo query "show the parse_directory function"
memory-neo query --project my-project "show all classes"
memory-neo query --raw "..."           # print raw JSON
memory-neo query --context "..."       # dump results as prompt-ready context block
memory-neo query                       # interactive mode
```

---

### `memory-neo context`

Fetch the raw code of a function or file — ready to paste into a prompt.

```bash
memory-neo context parse_directory           # fetch function by name
memory-neo context memory_neo/main.py        # fetch file by path
memory-neo context login --type function     # force function lookup
memory-neo context main.py --copy            # copy to clipboard
```

---

## Context API (RePTiLS multimodal recall)

In addition to the code-as-graph CLI, the API exposes two endpoints that
index and query a *parallel* multimodal graph (Episode + Activity /
Topic / ActivityObject / Where / TimeSlot). See
[`CONTEXT-API-SPEC.md`](./CONTEXT-API-SPEC.md) for the wire format and
[`CONTEXT-ENDPOINTS-IMPLEMENTATION.md`](./CONTEXT-ENDPOINTS-IMPLEMENTATION.md)
for the schema + semantics.

```bash
# Index a multimodal signature
curl -X POST https://memory-neo-api.fly.dev/context/index \
  -H "X-API-Key: $MN_KEY" -H "Content-Type: application/json" \
  -d '{
    "episode_id": "ep-001",
    "signature": {
      "when": "2026-05-20T10:23:00Z",
      "when_relative": "morning",
      "activity": "coding",
      "activity_object": "RePTiLS",
      "topic_tags": ["evanescence", "compression"],
      "where_label": "domicile"
    }
  }'

# Query the parallel graph
curl -X POST https://memory-neo-api.fly.dev/context/query \
  -H "X-API-Key: $MN_KEY" -H "Content-Type: application/json" \
  -d '{
    "filters": {
      "activity": ["coding"],
      "topic_tags": ["evanescence"]
    },
    "mode": "intersection",
    "limit": 20
  }'
```

Both `/context/*` endpoints (and the node-read endpoints below) accept
**either** `X-API-Key: <key>` **or** `Authorization: Bearer <jwt>` (laboria
M2M). The identity is derived from the credential — see
[`NODE-HANDSHAKE-RECONCILIATION.md`](./NODE-HANDSHAKE-RECONCILIATION.md).

---

## Node read API (lazy-load consumers)

Memory nodes (written by memwar / dogydoc) are read back **scoped to the
caller's own identity** — derived from the credential, never from a
`user_id` parameter. A key holder reads only its own nodes.

```bash
# Read a batch of YOUR nodes by id (the canonical read-by-id path).
# Owner is derived from the key/token; ids you don't own are filtered out.
curl "https://memory-neo-api.fly.dev/nodes/by-ids?ids=mem-1,mem-2,mem-3" \
  -H "X-API-Key: $MN_KEY"
# → { "nodes": [ … only the ids you own … ], "count": N }

# List ALL your nodes. The path id must be your own, else 403.
curl "https://memory-neo-api.fly.dev/nodes/$MY_USER_ID" \
  -H "X-API-Key: $MN_KEY"
```

| Endpoint                       | Status | Notes |
| ------------------------------ | ------ | ----- |
| `GET /nodes/by-ids?ids=a,b`    | ✅     | Canonical read-by-id. Owner from credential. `user_id` param removed (a stray one is ignored). Missing `ids` → 422. |
| `GET /nodes/{user_id}`         | ✅     | List all your nodes. `user_id` must equal your derived identity, else `403`. |
| `GET /node/{id}` (singular)    | ⛔️     | **Retired.** Use `GET /nodes/by-ids?ids=<id>`. One read-by-id contract. |
| `POST /nodes`                  | ✅     | Ingestion (memwar/dogydoc). Intentionally open — separate sprint. |

Service principals (Bearer M2M) additionally need the
`memory-neo:nodes:read` scope; humans and legacy keys auto-pass.

---

## Ignore patterns (`memIgnore`)

Place a `memIgnore` file in your project root to control what gets scanned.
Uses the same syntax as `.gitignore`:

```
# Folders
.venv/
node_modules/
dist/

# Wildcards
*.log
*.tmp
*.pyc

# Files
.env
secrets.json
```

If no `memIgnore` is found in your project, the package default is used (covers most common cases).

---
