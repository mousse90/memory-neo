# memory-neo `/context/*` API — spec (TODO côté memory-neo)

**Sprint** : CONTEXT-SIGNATURE — 2026-05-20
**Statut** : ✅ **implémenté** (memory-neo ≥ 0.2.0). Section auth mise à
jour en NODE-OWNERSHIP (0.4.0).

---

## 0. Authentification (mise à jour NODE-OWNERSHIP)

Tous les endpoints `/context/*` passent par la dépendance unique
`require_auth`. Ils acceptent **soit** `X-API-Key: <mnk_…>` (canal
propriétaire, legacy), **soit** `Authorization: Bearer <jwt>` (canal
service M2M laboria-auth). Aucun credential → `401`.

L'identité (`scope_user_id`) **dérive du credential** via
`resolve_principal`, jamais d'un `user_id` du payload :

- legacy `X-API-Key` → `User.id`
- laboria service → `claims.sub` (+ `orgId` comme `scope_tenant_id`)

Scopes (principals **service** uniquement ; humains + clés legacy
auto-pass) : `memory-neo:episodes:write` (index / delete),
`memory-neo:episodes:read` (query / hydrate). Un `user_id` dans le body
n'est qu'une auto-assertion : s'il diffère de l'identité dérivée → `403`.
Détails dans [`OWNERSHIP-CONTRACT.md`](./OWNERSHIP-CONTRACT.md).

Endpoints de rappel ajoutés (NODE-OWNERSHIP) :
`POST /context/episodes/by-ids` (hydrate épisodes, `episodes:read`) et
`DELETE /context/episodes/by-ids?ids=…` (`episodes:write`, nœuds d'axes
partagés préservés).

---

## 1. `POST /context/index`

Indexe la signature multimodale d'un épisode dans le graphe Memgraph
en parallèle des nodes `Memory`.

### Request

```
POST /context/index
Headers: X-API-Key: <mnk_…>   |   Authorization: Bearer <jwt>
Content-Type: application/json
```

```jsonc
{
  "user_id": "<auto-assertion optionnelle ; doit == l'identité dérivée du credential, sinon 403>",
  "episode_id": "ep-xxx",
  "signature": {
    "when": "2026-05-20T10:23:00Z",
    "when_relative": "morning",
    "activity": "coding",
    "activity_object": "RePTiLS",
    "topic_tags": ["evanescence", "compression"],
    "where_label": "domicile"
  }
}
```

### Effet attendu côté Memgraph

```cypher
MERGE (e:Episode {id: $episode_id})
SET e.when = $when, e.scope_tenant_id = ..., e.scope_user_id = ...

// Upserts canoniques (par scope) :
MERGE (a:Activity        {name: $activity})
MERGE (o:ActivityObject  {name: $activity_object})
MERGE (w:Where           {name: $where_label})        // si non-null
MERGE (ts:TimeSlot       {name: $when_relative})
FOREACH (t IN $topic_tags |
  MERGE (topic:Topic {name: t})
  MERGE (e)-[:ON_TOPIC]->(topic)
)

MERGE (e)-[:OCCURRED_DURING]->(a)
MERGE (e)-[:ABOUT_OBJECT]->(o)
MERGE (e)-[:AT_LOCATION]->(w)                          // si w existe
MERGE (e)-[:AT_TIMESLOT]->(ts)
```

### Response

```json
{ "ok": true, "episode_id": "ep-xxx" }
```

- `200` / `201` : indexation OK.
- `404` (état actuel, endpoint absent) : RePTiLS soft-fail, log
  warning, poursuit en mode dégradé.

---

## 2. `POST /context/query`

Recherche les épisodes matching un filtre multi-axes, en mode
intersection (par défaut) ou union.

### Request

```jsonc
{
  "user_id": "<optionnel>",
  "filters": {
    "activity": ["coding"],
    "topic_tags": ["evanescence", "compression"],
    "activity_object": ["RePTiLS"],
    "where_label": null,
    "when_after": "2026-05-01T00:00:00Z",
    "when_before": null,
    "when_relative": null
  },
  "mode": "intersection",
  "limit": 50
}
```

- Une clé à `null` est ignorée.
- `mode="intersection"` : un épisode doit matcher **chaque** axe
  contraint.
- `mode="union"` : un épisode qui matche **au moins un** axe.

### Cypher attendu (intersection)

```cypher
MATCH (e:Episode)
WHERE e.scope_tenant_id = $tenant AND e.scope_user_id = $user
WITH e
WHERE ($activity IS NULL OR
       EXISTS { MATCH (e)-[:OCCURRED_DURING]->(:Activity {name: IN $activity}) })
  AND ($topic_tags IS NULL OR
       ALL(t IN $topic_tags WHERE
            EXISTS { MATCH (e)-[:ON_TOPIC]->(:Topic {name: t}) }))
  AND ($activity_object IS NULL OR
       EXISTS { MATCH (e)-[:ABOUT_OBJECT]->(:ActivityObject {name: IN $activity_object}) })
  AND ($where_label IS NULL OR
       EXISTS { MATCH (e)-[:AT_LOCATION]->(:Where {name: IN $where_label}) })
  AND ($when_after IS NULL OR e.when >= $when_after)
  AND ($when_before IS NULL OR e.when <= $when_before)
  AND ($when_relative IS NULL OR
       EXISTS { MATCH (e)-[:AT_TIMESLOT]->(:TimeSlot {name: $when_relative}) })
RETURN e.id AS id, … LIMIT $limit
```

### Response

```jsonc
{
  "episode_ids": ["ep-xxx", "ep-yyy"],
  "count": 2,
  "matched_axes_per_episode": {
    "ep-xxx": ["activity:coding", "topic:evanescence", "object:RePTiLS"],
    "ep-yyy": ["activity:coding"]
  }
}
```

- `episode_ids` : ordre par défaut (créé/à implémenter — par `when`
  desc).
- `matched_axes_per_episode` : optionnel mais utile à la synthèse
  RePTiLS pour citer "depuis l'activité X, sur Y, le matin".
- `count` : `len(episode_ids)` quand `limit` n'est pas atteint, total
  réel (avant `limit`) sinon.

---

## 3. Multi-tenant

Les routes filtrent obligatoirement sur le scope du caller, **résolu
depuis le credential** (`X-API-Key` **ou** `Bearer` M2M) via
`resolve_principal` — jamais d'un `user_id` du payload. Un `episode_id`
qui n'appartient pas au scope du caller est traité comme inexistant —
absent du résultat sur `query` et `episodes/by-ids`, ignoré par les
`DELETE` scopés.

## 4. Indexation recommandée

```cypher
CREATE INDEX ON :Episode(id);
CREATE INDEX ON :Episode(when);
CREATE INDEX ON :Activity(name);
CREATE INDEX ON :Topic(name);
CREATE INDEX ON :ActivityObject(name);
```

## 5. Contrat de soft-fail (côté RePTiLS)

Tant que ces endpoints n'existent pas (réponse 404) ou ne sont pas
joignables :

- `MemoryNeoClient.index_context()` log un warning + retourne `False`.
- `MemoryNeoClient.query_context()` retourne un résultat vide.
- `MultiModalRecallStrategy.filter_by_axes()` dégrade au chemin
  sémantique (axes inconcluants).

RePTiLS continue à fonctionner sans régression. La couche
multimodale devient simplement *additive* dès que memory-neo
implémente les deux routes.
