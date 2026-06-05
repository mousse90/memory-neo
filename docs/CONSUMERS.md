# memory-neo — consumer registry

**Updated** : NODE-OWNERSHIP, 2026-06
**Purpose** : impact analysis. Who calls which endpoint, with which channel,
and what breaks when the contract changes. See
[`OWNERSHIP-CONTRACT.md`](./OWNERSHIP-CONTRACT.md) for the two channels and
[`NODE-HANDSHAKE-RECONCILIATION.md`](./NODE-HANDSHAKE-RECONCILIATION.md) for
the auth model.

---

## dogydoc — ingestion

- **Endpoints** : `POST /nodes` only.
- **Channel** : OWNER (`X-API-Key` of the account that owns the memories).
- **Status** : ⚠️ **client NOT yet migrated.** `POST /nodes` is now closed
  (auth required); an unauthenticated write returns `401`.
- **Known client-side silent-fail** : dogydoc currently reports
  `success=true` while writing **0** nodes (it never surfaced the failure).
  Because the endpoint was open, this masked the real breakage; now it will
  surface as `401`.
- **Action required** : migrate dogydoc to send its owner credential
  **BEFORE** any real ingestion. Until then, do **not** run a real
  ingestion — nothing will be written.

## RLM / MDASH — PONT-MEMOIRE (recall & synthesis, upcoming)

- **Endpoints** : reads `POST /context/query`, `POST /context/episodes/by-ids`,
  `POST /nodes/by-ids` (+ `GET /nodes/by-ids`); deletes via the scoped
  `DELETE /nodes/by-ids` and `DELETE /context/episodes/by-ids`.
- **Channel** : OWNER (`X-API-Key` of the owning account). Everything is
  scoped to the credential — no `user_id` travels in the request.
- **Status** : primary consumer of the owner-key channel going forward.

## UI / CLI — humans

- **Endpoints** : `POST /push`, `POST /query`, `GET /projects`,
  `GET /graph/{project_name}`, `GET /context/{target}`.
- **Channel** : OWNER (`X-API-Key`, legacy). These enforce
  `user_id == key.id` (403 on mismatch) and derive the namespace from the
  credential.
- **Status** : stable; untouched by this sprint except the `/graph` +
  `/projects` ownership/injection hardening (transparent to honest callers).

## RePTiLS — eval / recall (PAUSED)

- **Endpoints** : `POST /context/index`, `POST /context/query` (Bearer).
- **Channel** : SERVICE (Bearer M2M, `svc_reptils`, with
  `memory-neo:episodes:read|write` scopes).
- **Status** : **EN PAUSE.** `v0.3.1` behaviour is intact and its
  service-Bearer contract for `/context/*` remains contractual for the day
  it resumes. No active integration depends on it now.

---

## Impact summary

| Change (this sprint) | Affected | Effect |
| --- | --- | --- |
| `POST /nodes` closed | dogydoc | `401` until migrated (was already silently writing 0) |
| `GET /graph` guard + `$param` | UI/CLI | transparent for honest callers; injection closed |
| New recall surfaces | RLM/MDASH | new capabilities, owner-scoped |
| RePTiLS paused | RePTiLS | none — contract preserved for resumption |
