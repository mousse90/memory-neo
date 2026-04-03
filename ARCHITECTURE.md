# memory-neo — Architecture

## Folder Structure

```
memory-neo/                          ← root (pip-installable package)
│
├── memory_neo/                      ← Python package (CLI + client)
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                  ← CLI entrypoint (click group)
│   │   ├── push.py                  ← `memory-neo push` command
│   │   ├── query.py                 ← `memory-neo query "..."` command
│   │   ├── context.py               ← `memory-neo context <fn>` command
│   │   └── login.py                 ← `memory-neo login` command
│   ├── core/
│   │   ├── __init__.py
│   │   ├── scanner.py               ← directory walker + file parser
│   │   ├── extractor.py             ← AST function extractor (Python)
│   │   └── ignore.py                ← memIgnore pattern loader
│   ├── graph/
│   │   ├── __init__.py
│   │   └── client.py                ← HTTP client → FastAPI backend
│   ├── nlp/
│   │   ├── __init__.py
│   │   └── formatter.py             ← format query results for terminal
│   └── utils/
│       ├── __init__.py
│       ├── config.py                ← ~/.memoryneo/config.json manager
│       └── display.py               ← rich terminal output helpers
│
├── api/                             ← FastAPI backend (deployed on Fly.io)
│   ├── main.py                      ← FastAPI app entrypoint
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── push.py                  ← POST /push
│   │   ├── query.py                 ← POST /query
│   │   ├── context.py               ← GET /context/{fn_name}
│   │   └── auth.py                  ← POST /auth/token, POST /auth/register
│   ├── services/
│   │   ├── __init__.py
│   │   ├── graph.py                 ← Memgraph write/read (neo4j driver)
│   │   ├── nlp.py                   ← NLP → Cypher via Claude API
│   │   └── auth.py                  ← API key validation
│   └── db/
│       ├── __init__.py
│       ├── prisma.py                ← Prisma client wrapper
│       └── schema.prisma            ← Postgres schema (users, keys, logs)
│
├── deploy/
│   ├── api.Dockerfile               ← Dockerfile for FastAPI service
│   ├── memgraph.Dockerfile          ← Dockerfile for Memgraph service
│   ├── fly.api.toml                 ← Fly.io config for API
│   ├── fly.memgraph.toml            ← Fly.io config for Memgraph
│   └── init.cypher                  ← Memgraph schema init script
│
├── docs/
│   └── README.md                    ← full user-facing docs
│
├── setup.py                         ← pip package config
├── pyproject.toml                   ← build system config
├── requirements.txt                 ← package dependencies
├── requirements.api.txt             ← API-only dependencies
├── memIgnore                        ← default ignore patterns
└── .env.example                     ← environment variable template
```

## Service Map

```
USER MACHINE
  pip install memory-neo
  memory-neo login          → stores API key in ~/.memoryneo/config.json
  memory-neo push           → scans dir → POST /push → Memgraph
  memory-neo query "..."    → POST /query → Claude NLP → Cypher → Memgraph
  memory-neo context <fn>   → GET /context/{fn} → returns code snippet
        |
        | HTTPS + X-API-Key header
        ▼
Fly.io: memory-neo-api  (FastAPI)
  POST /push             → services/graph.py → Memgraph WRITE
  POST /query            → services/nlp.py (Claude) → Cypher → Memgraph READ
  GET  /context/:fn      → services/graph.py → Memgraph READ
  POST /auth/register    → services/auth.py → Postgres WRITE
  POST /auth/token       → services/auth.py → Postgres READ
        |              \
        ▼               ▼
Fly.io: Memgraph        Supabase: PostgreSQL
  (:Project)            users
    -[:CONTAINS]->      api_keys
  (:File)               projects
    -[:HAS_FUNCTION]->  query_logs
  (:Function)           push_logs
```

## Namespace Convention (Memgraph)

Every node carries a `namespace` property: `{userId}::{projectName}`
This isolates projects on a shared Memgraph instance.

Example:
  (:Project {namespace: "usr_abc123::my-app", name: "my-app"})
  (:File    {namespace: "usr_abc123::my-app", path: "src/auth.py"})
  (:Function {namespace: "usr_abc123::my-app", name: "login"})
