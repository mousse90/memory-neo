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

## Self-hosting

You can run the entire backend yourself.

### Requirements
- Fly.io account
- Supabase (or any PostgreSQL) account
- Anthropic API key

### Deploy

```bash
# 1. Deploy Memgraph
fly deploy --config deploy/fly.memgraph.toml

# 2. Create persistent volume
fly volumes create memgraph_data --size 20 --region cdg --app memory-neo-graph

# 3. Init Memgraph schema
fly ssh console --app memory-neo-graph
# Inside pod:
cat /init.cypher | mgconsole

# 4. Set API secrets
fly secrets set \
  ANTHROPIC_API_KEY=sk-ant-... \
  DATABASE_URL=postgresql://... \
  API_SECRET_SALT=$(openssl rand -base64 32) \
  --app memory-neo-api

# 5. Deploy API
fly deploy --config deploy/fly.api.toml

# 6. Run Prisma migrations
fly ssh console --app memory-neo-api
# Inside pod:
prisma migrate deploy --schema=schema.prisma
```

### Point CLI to your instance

```bash
memory-neo login --api-url https://your-api.fly.dev
```

---

## Project structure

```
memory-neo/
├── memory_neo/              ← Python package (pip install memory-neo)
│   ├── cli/                 ← push, query, context, login commands
│   ├── core/                ← scanner, AST extractor, ignore patterns
│   ├── graph/               ← HTTP client to backend
│   ├── nlp/                 ← result formatter
│   └── utils/               ← config, display helpers
├── api/                     ← FastAPI backend (Fly.io)
│   ├── routes/              ← push, query, context, auth endpoints
│   ├── services/            ← graph (Memgraph), nlp (Claude), auth
│   └── db/                  ← schema.prisma (PostgreSQL)
├── deploy/                  ← Dockerfiles, fly.toml configs, init.cypher
└── docs/                    ← this file
```

---

## Tech stack

| Layer | Technology |
|---|---|
| CLI package | Python + Click + Rich |
| Backend | FastAPI on Fly.io |
| Graph DB | Memgraph on Fly.io (Bolt protocol) |
| Postgres | Supabase |
| NLP engine | Claude API (claude-sonnet) |
| Auth | API key (SHA-256 hashed) |

---

## License

MIT
