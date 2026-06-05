# NODE-HANDSHAKE 1/3 — memory-neo side

**Sprint** : NODE-HANDSHAKE — 2026-06-04
**Goal** : a key holder can RE-READ its own nodes and index context with
that **same** key. One auth dependency, identity derived from the
credential — never from a roaming `user_id`.

---

## 0. Prod ⇄ git reconciliation (done first)

Before touching anything, local `main` was compared to the deployed
instance `memory-neo-api.fly.dev` (reported `version 0.2.0`).

**Method** : fetched the live `GET /openapi.json` and diffed it against the
OpenAPI generated from local `main` (`app.openapi()`), then probed live
route status codes.

**Result — NO CONTRACT DRIFT.** The two OpenAPI documents are
byte-identical after normalization (same 17 paths, same params, same 20
component schemas, same version string). In particular the deployed
`/context/index`, `/context/query`, `/nodes/by-ids` and `/nodes/{user_id}`
already declare the **unified** auth surface: two *optional* headers
`authorization` + `X-API-Key` (the signature of `require_auth`), not the
old required-`X-API-Key`. Fly shows the live machines on deploy version 22
(2026-06-02), which is *after* the coexistence-auth commits
(`c525417 → aab717d`).

**Consequence for the RePTiLS e2e constat (2026-06-04):**

| Symptom reported                                   | Status            | Why |
| -------------------------------------------------- | ----------------- | --- |
| `/context/index` → 403 with `X-API-Key`            | **STALE**         | Superseded by the deployed `require_auth`; `require_scope` auto-passes legacy/X-API-Key callers. Confirmed live in step 4. |
| `GET /nodes/by-ids` → 422 (requires `user_id`)     | **REAL — fixed**  | Deployed `by-ids` still required a `user_id` query param. Removed here. |
| `GET /node/{id}` → 404 (endpoint gone)             | **REAL — decided**| Singular getter is intentionally retired. See §2. |

No "phantom target" was patched: the deployed contract equals git `main`,
so the changes in this sprint apply cleanly on top of what is live.

---

## 1. Unified auth (one dependency, identity from the credential)

`api.services.auth.require_auth` is the single auth dependency. It accepts
**either**:

- `Authorization: Bearer <jwt>` → validated against laboria-auth (M2M
  services *and* humans), or
- `X-API-Key: <mnk_…>` → legacy key path,

and returns a normalized principal dict with a `source` field. No
credentials → `401`. It is applied to `/context/index`, `/context/query`,
`/nodes/by-ids`, `/nodes/{user_id}`.

Identity is derived **identically everywhere** through one helper,
`api.services.auth.resolve_principal(auth) -> (user_id, tenant_id)`:

| Source                    | `user_id`     | `tenant_id` |
| ------------------------- | ------------- | ----------- |
| laboria-auth, `service`   | `claims.sub`  | `claims.orgId` |
| laboria-auth, `human`     | `claims.sub`  | `None` |
| legacy `X-API-Key`        | `User.id`     | `None` |

`/context/*` and `/nodes/*` both call `resolve_principal` — the data scope
is the credential's identity. A `user_id` sent in a body/query/path may
only act as a **redundant self-assertion**: if present and different from
the derived identity it is rejected with `403 user_id mismatch` (legacy
`/context/index`, `/context/query`, `/nodes/{user_id}`). It can never
select another principal's data.

`require_scope` semantics are unchanged: service principals must carry the
scope (`memory-neo:nodes:read`, `memory-neo:episodes:write/read`); humans
and legacy keys auto-pass during coexistence.

Bearer consumers (RePTiLS eval runs `/context/*` in Bearer today) are
unaffected — their code path is untouched.

---

## 2. Node read contract — ONE truth

### `GET /nodes/by-ids?ids=<comma,separated>`  ✅ canonical read-by-id

- Owner is **derived from the credential** (`resolve_principal`). The old
  required `user_id` query param is **removed**. Sending it remains
  harmless — FastAPI ignores undeclared query params — so existing callers
  do not break.
- Returns **only** Memory nodes owned by the authenticated principal among
  the requested ids. Ids belonging to another user are silently filtered
  out (never leaked), unknown ids are skipped.
- `ids` is still required → missing `ids` is `422`.
- Scope gate: `memory-neo:nodes:read` (service principals).

### `GET /nodes/{user_id}`  ✅ list-all, ownership-enforced

- Owner derived from the credential. The path `user_id` is a redundant
  self-assertion: `user_id != resolve_principal(...)` → `403 user_id
  mismatch`. You can only list your own nodes.
- Scope gate: `memory-neo:nodes:read`.

### `GET /node/{id}`  ⛔️ RETIRED — definitively dead

The singular getter is **not** restored, as an alias or otherwise. There
is one read-by-id path: `GET /nodes/by-ids?ids=<id>` (a batch of one).
Rationale: the batch endpoint subsumes the singular, keeps a single
ownership-scoped code path, and avoids two divergent contracts. Callers
hitting `/node/{id}` get `404` by design.

### `POST /nodes`  — CLOSED in NODE-OWNERSHIP (see §4)

Originally left open; **closed** by the NODE-OWNERSHIP sprint (2026-06).
Ownership now derives from the credential; `user_id` / `relationship` are
optional self-assertions. No credential → `401`. dogydoc must migrate its
client to send its owner credential BEFORE any real ingestion.

---

## 3. Done criterion

A holder of a credential (legacy `X-API-Key` or laboria Bearer) can:

- **re-read its own nodes** via `GET /nodes/by-ids` / `GET /nodes/{me}`
  with that same credential — and never sees another principal's nodes;
- **index context** via `POST /context/index` with that same credential
  (`X-API-Key` → 200, Bearer service+scope → 200).

Never log a key. Raw upstream errors are surfaced as-is.

---

## 4. NODE-OWNERSHIP (2026-06) — absorbs & closes handshake 2/3 + 3/3

The NODE-OWNERSHIP sprint folds the remaining handshake volets into a
single principle extended from reads (1/3) to **writes and everything
else**: the identity always derives from the credential
(`resolve_principal`), never from the payload. memory-neo is now a
**personal-memory store** — an open write hole is unacceptable.

**Closes 2/3 — write by credential:**

- `POST /nodes` — auth required (`memory-neo:nodes:write` for services);
  owner derived from the credential and used as the SOLE owner in Cypher.
  `user_id` / `relationship.from_id` are optional self-assertions (403 on
  mismatch). `:Memory` label backticked (closes the local-image debt).
- `GET /graph/{project_name}` — same guard as `/push` (`user_id` must equal
  the key's id → 403 otherwise); namespace derived from the credential.
  The namespace is now a **bound `$param`**, not an f-string — Cypher
  injection closed. Same `$prefix` fix on the dev `/projects` branch.

**Closes 3/3 — client alignment / channel ownership:**

- **RePTiLS is PAUSED.** Its `v0.3.1` service-Bearer contract for
  `/context/*` (`svc_reptils`) stays valid for the day it resumes, but no
  active integration depends on it now.
- The **owner-key channel** (per-account `X-API-Key`) becomes the primary
  channel, serving the upcoming **PONT-MEMOIRE / RLM-MDASH** recall &
  synthesis layer.

**New recall surfaces (for RLM/MDASH):**

| Endpoint | Scope | Notes |
| --- | --- | --- |
| `POST /context/episodes/by-ids` | `episodes:read` | Hydrate episodes (props + axes), body `{episode_ids}`, no URL ceiling. |
| `POST /nodes/by-ids` | `nodes:read` | Batch read by body `{ids}` — parity with the GET. |
| `DELETE /nodes/by-ids?ids=…` | `nodes:write` | DETACH DELETE the caller's Memory only → `{deleted:n}`. |
| `DELETE /context/episodes/by-ids?ids=…` | `episodes:write` | Delete the caller's Episodes (+ relations); shared axis nodes preserved → `{deleted:n}`. |

All four scope to `resolve_principal(auth)` and silently filter ids owned
by another principal (never leaked). See
[`OWNERSHIP-CONTRACT.md`](./OWNERSHIP-CONTRACT.md) for the two-channel model
and [`CONSUMERS.md`](./CONSUMERS.md) for the consumer registry.

API version: `0.3.0` → `0.4.0`. **Local-only sprint — not deployed.**
