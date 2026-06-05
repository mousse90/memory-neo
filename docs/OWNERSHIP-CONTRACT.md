# memory-neo — Ownership Contract

**Sprint** : NODE-OWNERSHIP — 2026-06
**Principle** : *the identity derives from the credential, never from the
payload.* Possession of a credential is the proof of ownership. This is the
single rule behind `resolve_principal(auth)` and every scoped read/write.

---

## Two channels

memory-neo authenticates two distinct kinds of caller. Both flow through
the one `require_auth` dependency; they differ in **what identity the
credential proves** and **what data it owns**.

### 1. OWNER channel — `X-API-Key`

- **Credential** : the per-account API key (`mnk_…`). It travels
  **per-request**, in the `X-API-Key` header.
- **Identity** : `User.id` of the account that holds the key
  (`resolve_principal` → `(User.id, None)`).
- **Owns** : that account's personal data — its Memory nodes, its Episodes,
  its projects/graph namespace.
- **Used by** : humans (UI/CLI), and the PONT-MEMOIRE / RLM-MDASH recall
  layer acting **as the owning account** (it holds the account's key).
- **Authorization** : possession of the key == proof of ownership. There is
  no `user_id` parameter to assert someone else's identity; any `user_id` /
  `from_id` in a request is only a redundant self-assertion and must match
  the derived owner (else `403`).

### 2. SERVICE channel — Bearer M2M (`svc_*`)

- **Credential** : a laboria-auth JWT for a service principal (`svc_*`),
  carrying `type=service`, `scopes`, and `orgId`.
- **Identity** : `claims.sub` (the service), tenant `claims.orgId`
  (`resolve_principal` → `(sub, orgId)`).
- **Owns** : the service's **own** data, written under its `sub` (e.g.
  Episodes a service indexes under its own scope). It does **not** own, and
  cannot address, an arbitrary user's data.
- **Used by** : RePTiLS (`svc_reptils`, currently **paused**) for
  `/context/*`.
- **Authorization** : scope-gated (`require_scope`). A service must carry the
  matching scope (`memory-neo:nodes:read|write`,
  `memory-neo:episodes:read|write`); a revoked/unprovisioned service can't
  act. The service acts under its own `sub` — never on behalf of a roaming
  `user_id`.

### Why two, and what this closes

Separating the channels closes the hole where *"a service reads/writes any
`user_id`"*. Before, a `user_id` in the body/query/path picked the data
scope; a caller with any valid credential could address another principal's
data. Now the data scope **is** the credential's identity. A service can
only touch its own `sub`-scoped data; an account key can only touch its
own account's data. Cross-principal access is structurally impossible, not
merely checked.

---

## Kill-switch — Regenerate key

The **Regenerate** button in `/settings` is the kill-switch for the OWNER
channel.

- Regenerating invalidates the account's current `X-API-Key` and issues a
  fresh one (`POST /auth/regenerate-key`).
- **Failure mode is intentional and total** : every holder of the old key
  immediately gets `401`. There is no grace period and no partial validity.
- **Recovery** : redistribute the new key to the legitimate holders (the
  account's own clients / secret stores). This is the lever to revoke a
  leaked key or cut off a misbehaving client.

(The SERVICE channel is revoked upstream in laboria-auth: a disabled
service yields `{valid:false}` on `/validate` and falls through to `401`.)

---

## Key-handling rules (non-negotiable)

- A key is **NEVER logged** — not in application logs, not in request
  traces, not in error messages, not in CI output.
- A key is **never persisted outside the client's secret store**. memory-neo
  stores only a salted SHA-256 **hash** of the key; the raw key is shown
  once at creation and never retrievable thereafter.
- A key travels only in the `X-API-Key` header over TLS. It is not put in
  URLs, query strings, or bodies.
- Treat any key that appears in a log or a shared channel as compromised →
  Regenerate immediately.

---

## One-line summary

> The credential is the identity. Holding the account's key proves you own
> the account's data; holding a service token proves you are that service.
> Nothing in the request body can change whose data you touch.
