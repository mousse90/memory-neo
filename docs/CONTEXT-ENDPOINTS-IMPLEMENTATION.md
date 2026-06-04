# memory-neo `/context/*` endpoints — implementation notes

**Sprint** : MEMORY-NEO-CONTEXT-ENDPOINTS — 2026-05-20
**Status** : implemented + 42 tests green (27 integration + 15 unit)
**Companion spec** : [`CONTEXT-API-SPEC.md`](./CONTEXT-API-SPEC.md)

---

## 1. Overview

The `/context/index` + `/context/query` endpoints back the RePTiLS
multimodal recall layer. They run *in parallel* to the existing
`Project / File / Function / Memory` graph — same Memgraph database,
disjoint node labels, no impact on existing code-as-graph or memwar
flows.

Pre-existing `GET /context/{target}` (raw code lookup) is unchanged —
both methods coexist on the same `/context/*` prefix.

## 2. Memgraph schema

### Nodes (new — all scoped per user)

```
(:Episode        {id, scope_user_id, when})
(:Activity       {name, scope_user_id})
(:Topic          {name, scope_user_id})
(:ActivityObject {name, scope_user_id})
(:Where          {name, scope_user_id})
(:TimeSlot       {name, scope_user_id})   // "morning", "weekend", ...
```

### Relations (Episode → axis)

| Relation            | Target           |
| ------------------- | ---------------- |
| `OCCURRED_DURING`   | `:Activity`      |
| `ON_TOPIC`          | `:Topic`         |
| `ABOUT_OBJECT`      | `:ActivityObject`|
| `AT_LOCATION`       | `:Where`         |
| `AT_TIMESLOT`       | `:TimeSlot`      |

### Indexes

Created idempotently at app startup
(`api/services/context_graph.init_context_schema()`).
A standalone Cypher script is also shipped at
[`deploy/memgraph_init_context.cypher`](../deploy/memgraph_init_context.cypher)
for manual application.

We **do not** use `CREATE CONSTRAINT … UNIQUE` — MERGE on
`{name, scope_user_id}` already provides upsert semantics and the
constraint syntax differs across Memgraph versions.

## 3. Upsert + idempotence strategy

`POST /context/index` uses `MERGE … ON CREATE … ON MATCH` on every
node and every relation. Effects:

- Re-indexing an identical payload : `nodes_created=0`,
  `relations_created=0` → true no-op.
- Re-indexing the same `episode_id` with **new** axes : new nodes /
  relations are added, **existing relations are NOT removed**.
  This is intentional in v1 — episodes are historical, additive
  signals. A future endpoint (`DELETE /context/{episode_id}` or a
  versioning field) will handle replacement semantics if needed.
- Re-indexing with the same axes but a different `when` : the
  `Episode.when` property is updated (axis nodes and relations stay).

## 4. Query semantics

`POST /context/query` exposes two modes:

- **intersection** (default) : the episode must match every axis filter
  that is set. For `topic_tags`, all listed tags must be present
  (logical AND). Temporal filters (`when_after` / `when_before`) are
  always AND-combined with the rest.
- **union** : the episode matches if at least one set axis matches.
  For `topic_tags` in union mode, any one tag is enough.

`null` or empty-list values are *ignored* (treated as "filter not
set"). If no filter is set at all, the endpoint returns the most
recent `limit` episodes for the caller's user, ordered by `when DESC`.

`matched_axes_per_episode` only contains axis values that were *part
of a filter*. It's intended to support RePTiLS synthesis citations
("you mentioned this while *coding* on *RePTiLS*…") — not to dump
every axis on every episode.

## 5. Security

- **Auth** : the unified `require_auth` dependency — accepts **either**
  `X-API-Key` (legacy, `DEV_API_KEY` in dev) **or** `Authorization:
  Bearer <jwt>` (laboria-auth M2M / human). No credentials → `401`. This
  is the same dependency used by the node-read endpoints, so a key holder
  indexes context and reads nodes with one credential. See
  [`NODE-HANDSHAKE-RECONCILIATION.md`](./NODE-HANDSHAKE-RECONCILIATION.md).
- **Identity** : derived from the credential via
  `auth.resolve_principal()` (legacy → `User.id`; laboria → `claims.sub`,
  `+orgId` for services). Service principals need scope
  `memory-neo:episodes:write` / `:read`; humans + legacy keys auto-pass.
- **Scope** : every Cypher write/read is parameter-bound to that derived
  identity. Episodes from other principals are *never* returned by
  `/context/query` — even when the filter explicitly names another user.
- **Payload `user_id`** : optional, redundant self-assertion. If present
  it **must** equal the derived identity, otherwise `403 user_id
  mismatch` (legacy callers). It can never select another principal.

## 6. v1 limitations (documented)

| Limitation                                | Plan                                      |
| ----------------------------------------- | ----------------------------------------- |
| No `DELETE /context/{episode_id}`         | Add in v2 once RePTiLS needs cleanup      |
| No historical versioning (re-index ADDs)  | Document; revisit if it causes confusion  |
| `scope_tenant_id` not yet plumbed         | `scope_user_id` only — multi-tenant later |
| `Where(name)` is a free-text label        | No geolocation / hierarchy in v1          |
| No paging beyond `limit`                  | Add cursor in v2 if needed                |

## 7. Manual Cypher cheatsheet

Inspect a user's episodes:

```cypher
MATCH (e:Episode {scope_user_id: "usr_xxx"})
OPTIONAL MATCH (e)-[r]->(n)
RETURN e.id, e.when, type(r), labels(n), n.name
ORDER BY e.when DESC
LIMIT 50;
```

Count episodes per activity:

```cypher
MATCH (e:Episode {scope_user_id: "usr_xxx"})-[:OCCURRED_DURING]->(a:Activity)
RETURN a.name, count(e) AS episodes
ORDER BY episodes DESC;
```

Find episodes intersecting two topics:

```cypher
MATCH (e:Episode {scope_user_id: "usr_xxx"})-[:ON_TOPIC]->(t:Topic)
WHERE t.name IN ["evanescence", "compression"]
WITH e, collect(DISTINCT t.name) AS topics
WHERE size(topics) = 2
RETURN e.id, e.when, topics;
```

## 8. Testing

```bash
# Unit tests (no Memgraph needed)
pytest tests/test_context_unit.py

# Integration tests (need a Memgraph at $MEMGRAPH_HOST:$MEMGRAPH_PORT)
docker run -d --name memgraph -p 7687:7687 memgraph/memgraph:latest
pytest tests/
```

When Memgraph is unreachable, the 27 integration tests SKIP cleanly
(the suite remains green for CI on hosts without graph DB).

## 9. Reference

- Pydantic models : `api/routes/context.py`
- Graph operations : `api/services/context_graph.py`
- Schema init : `api/main.py` lifespan
- OpenAPI : `GET /docs` shows the new endpoints under the `context` tag.
