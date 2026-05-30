# Validation locale et déploiement — Context Endpoints

**Sprint** : MEMORY-NEO-CONTEXT-VALIDATION — 2026-05-30
**Statut** : 42 / 42 tests verts contre Memgraph réel + 5 scénarios curl E2E validés en local.
**Companion** : [`CONTEXT-API-SPEC.md`](./CONTEXT-API-SPEC.md),
[`CONTEXT-ENDPOINTS-IMPLEMENTATION.md`](./CONTEXT-ENDPOINTS-IMPLEMENTATION.md)

---

## 1. Prérequis environnement

| Composant | Version / chemin validé | Notes |
|---|---|---|
| Python | `/Users/moustaphahoundjomacair/.pyenv/shims/python3.12` | Le `venv/` repo est en 3.14, pytest cassé (`pyexpat` ABI broken). **Utiliser pyenv 3.12.** |
| `email-validator` | installé via `python3.12 -m pip install email-validator` | Dep transitive de `pydantic[email]` requise par `auth.py` (`EmailStr`). |
| Memgraph | container Docker nommé `memgraph`, image `memgraph/memgraph-platform`, port `7687` | Container déjà créé — on `start`, pas `run`. |
| `.env` | racine repo, présent | Voir variables ci-dessous. |

Variables d'env utilisées (déjà dans `.env`, à overrider en local pour forcer dev mode) :

```
MEMGRAPH_HOST=127.0.0.1
MEMGRAPH_PORT=7687
ENVIRONMENT=development        # .env contient "production" — override en local
DEV_API_KEY=local-dev-key
DEV_USER_ID=usr_local
DEV_EMAIL=dev@local.dev
```

En mode `development`, `validate_api_key()` court-circuite Prisma et accepte
`DEV_API_KEY` comme clé valide → pas besoin de Supabase / Postgres local.

## 2. Lancer Memgraph local

```bash
docker start memgraph
until nc -z localhost 7687; do sleep 1; done
echo "Memgraph UP sur bolt://localhost:7687"
```

Si le container n'existe pas (premier setup d'une machine vierge) :

```bash
docker run -d --name memgraph -p 7687:7687 memgraph/memgraph:latest
```

Verif :

```bash
docker ps --filter name=memgraph --format "{{.Names}}: {{.Status}}"
# → memgraph: Up X seconds
```

## 3. Lancer les tests (42)

```bash
cd /Users/moustaphahoundjomacair/Documents/dev/memory-neo
/Users/moustaphahoundjomacair/.pyenv/shims/python3.12 -m pytest tests/ -v
```

Résultat attendu :

```
collected 42 items
tests/test_context_index.py ............                   [ 28%]
tests/test_context_query.py ...............                [ 64%]
tests/test_context_unit.py ...............                 [100%]
============================== 42 passed in 1.52s ==============================
```

Si Memgraph n'est pas démarré : `15 passed, 27 skipped` (les intégrations
auto-skip via `conftest.pytest_collection_modifyitems`).

## 4. Lancer le serveur en local

```bash
cd /Users/moustaphahoundjomacair/Documents/dev/memory-neo
mkdir -p /tmp/memneo-logs

ENVIRONMENT=development \
DEV_API_KEY=local-dev-key \
DEV_USER_ID=usr_local \
DEV_EMAIL=dev@local.dev \
MEMGRAPH_HOST=127.0.0.1 \
MEMGRAPH_PORT=7687 \
/Users/moustaphahoundjomacair/.pyenv/shims/python3.12 -m uvicorn api.main:app \
  --port 8000 --log-level info > /tmp/memneo-logs/uvicorn.log 2>&1 &
```

Vérifier qu'il répond :

```bash
curl -s http://localhost:8000/health
# → {"status":"ok","service":"memory-neo-api","version":"0.2.0"}
```

Swagger : http://localhost:8000/docs

## 5. Test E2E curl (5 scénarios validés)

### 5.1 Index — épisode avec 5 axes

```bash
curl -s -X POST http://localhost:8000/context/index \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "usr_local",
    "episode_id": "ep-e2e-validation-001",
    "signature": {
      "when": "2026-05-30T10:23:00Z",
      "when_relative": "morning",
      "activity": "coding",
      "activity_object": "RePTiLS",
      "topic_tags": ["evanescence", "compression"],
      "where_label": "domicile"
    }
  }'
# Attendu :
# {"ok":true,"episode_id":"ep-e2e-validation-001","nodes_created":7,"relations_created":6}
```

7 nodes = 1 Episode + 5 axis (Activity, ActivityObject, Where, TimeSlot, 1er Topic) + 1 Topic supplémentaire ; 6 relations.

### 5.2 Index — même payload → idempotence

Rejouer la requête 5.1 :

```
{"ok":true,"episode_id":"ep-e2e-validation-001","nodes_created":0,"relations_created":0}
```

### 5.3 Query intersection

```bash
curl -s -X POST http://localhost:8000/context/query \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "usr_local",
    "filters": {
      "activity": ["coding"],
      "topic_tags": ["evanescence", "compression"],
      "activity_object": ["RePTiLS"]
    },
    "mode": "intersection",
    "limit": 50
  }'
# Attendu :
# {"episode_ids":["ep-e2e-validation-001"],"count":1,
#  "matched_axes_per_episode":{"ep-e2e-validation-001":[
#    "activity:coding","topic:evanescence","topic:compression","object:RePTiLS"]}}
```

### 5.4 Query union (multi-episode)

Indexer un deuxième épisode au passage :

```bash
curl -s -X POST http://localhost:8000/context/index \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"user_id":"usr_local","episode_id":"ep-e2e-validation-002",
       "signature":{"when":"2026-05-30T15:00:00Z","activity":"reading",
                    "topic_tags":["philosophie"]}}'

curl -s -X POST http://localhost:8000/context/query \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"user_id":"usr_local",
       "filters":{"activity":["coding"],"topic_tags":["philosophie"]},
       "mode":"union","limit":50}'
# Attendu : 2 episodes, ordre when DESC :
# ep-e2e-validation-002 (matched topic:philosophie)
# ep-e2e-validation-001 (matched activity:coding)
```

### 5.5 Isolation user

```bash
# Mismatch user_id payload != caller → 403
curl -i -X POST http://localhost:8000/context/query \
  -H "X-API-Key: local-dev-key" -H "Content-Type: application/json" \
  -d '{"user_id":"usr_other","filters":{},"mode":"intersection","limit":50}'
# → HTTP/1.1 403 Forbidden
# → {"detail":"user_id mismatch"}
```

Sans `user_id` dans le payload : le caller voit uniquement ses propres
episodes (scope strict via `MATCH (e:Episode {scope_user_id: $uid})`).

## 6. Vérification Memgraph + cleanup

Inspection :

```bash
/Users/moustaphahoundjomacair/.pyenv/shims/python3.12 - <<'PY'
from neo4j import GraphDatabase
d = GraphDatabase.driver("bolt://127.0.0.1:7687", auth=("",""))
with d.session() as s:
    for row in s.run("""
        MATCH (e:Episode {scope_user_id: 'usr_local'})-[r]->(n)
        RETURN e.id AS eid, type(r) AS rel, labels(n)[0] AS nlabel, n.name AS nname
        ORDER BY eid, rel, nname
    """):
        print(f"{row['eid']} -[{row['rel']}]-> {row['nlabel']} {row['nname']}")
d.close()
PY
```

Sortie attendue pour ep-001 : 5 relations (`ABOUT_OBJECT`, `AT_LOCATION`,
`AT_TIMESLOT`, `OCCURRED_DURING`, 2× `ON_TOPIC`).

Cleanup des nodes de test :

```bash
/Users/moustaphahoundjomacair/.pyenv/shims/python3.12 - <<'PY'
from neo4j import GraphDatabase
d = GraphDatabase.driver("bolt://127.0.0.1:7687", auth=("",""))
with d.session() as s:
    s.run("""
        MATCH (n)
        WHERE n.scope_user_id = 'usr_local'
          AND (n:Episode OR n:Activity OR n:Topic OR n:ActivityObject OR n:Where OR n:TimeSlot)
        DETACH DELETE n
    """)
d.close()
PY
```

## 7. Procédure de déploiement Fly.io

### 7.1 Checks pré-déploiement (obligatoires)

- [ ] `git status` montre **un seul** thème de changements (ici : code/docs context). La modif OTP de `api/routes/auth.py` doit être **stashée** ou **commitée séparément** — voir §9.
- [ ] `pytest tests/` → **42 passed**, 0 fail, 0 skip (Memgraph local up).
- [ ] Test curl E2E §5.1–5.5 OK contre `http://localhost:8000`.
- [ ] Routes existantes non régressées : `GET /context/{target}`, `POST /nodes`, `POST /query` répondent (§5 OpenAPI list).
- [ ] `flyctl status -a memory-neo-api` → app green, dernière release stable.
- [ ] Backup état Memgraph prod si la migration de schéma a un risque
      (ici : seulement des `CREATE INDEX` idempotents → risque ~nul, mais
      noter la release courante pour rollback rapide).

### 7.2 Déployer

```bash
cd /Users/moustaphahoundjomacair/Documents/dev/memory-neo
flyctl deploy --config deploy/fly.api.toml --dockerfile deploy/api.Dockerfile
```

(Voir `deploy/fly.api.toml` — app `memory-neo-api`, region `cdg`, healthcheck `GET /health`.)

### 7.3 Smoke-test post-déploiement

```bash
# 1. Health
curl -s https://memory-neo-api.fly.dev/health
# → {"status":"ok",...}

# 2. Swagger inclut bien les nouveaux endpoints
curl -s https://memory-neo-api.fly.dev/openapi.json | python3 -c "
import json,sys
spec = json.load(sys.stdin)
for p in sorted(spec['paths']):
    if '/context' in p: print(p, list(spec['paths'][p].keys()))
"
# → /context/index ['post']
# → /context/query ['post']
# → /context/{target} ['get']

# 3. Index + query avec une vraie clé (clé prod, pas DEV_API_KEY)
curl -s -X POST https://memory-neo-api.fly.dev/context/index \
  -H "X-API-Key: <PROD_API_KEY>" -H "Content-Type: application/json" \
  -d '{"episode_id":"ep-smoke-prod-001","signature":{
       "when":"2026-05-30T18:00:00Z","activity":"smoke-test"}}'

curl -s -X POST https://memory-neo-api.fly.dev/context/query \
  -H "X-API-Key: <PROD_API_KEY>" -H "Content-Type: application/json" \
  -d '{"filters":{"activity":["smoke-test"]},"mode":"intersection","limit":5}'

# 4. Non-régression dogydoc : un push/query code-graph existant
#    (lancer un job dogydoc connu et vérifier que rien ne casse côté lui).
```

### 7.4 Rollback

```bash
# Lister les releases
flyctl releases -a memory-neo-api

# Rollback vers la release N-1 (avant déploiement context)
flyctl releases rollback <release_id> -a memory-neo-api

# Vérifier
curl -s https://memory-neo-api.fly.dev/health
```

Le schéma n'a que des `CREATE INDEX` idempotents — les indexes ajoutés
restent en place après rollback applicatif, ce qui est sans impact
fonctionnel (Memgraph ignore les index sur des labels non utilisés).

## 8. Modif auth OTP stashée (§hors scope context)

Au début de ce sprint, `api/routes/auth.py` avait une modif non commitée
qui remplaçait le flux `register` par un flux OTP `/send-code` + `/verify-code`
(lié au pilote laboria-auth) — voir `stash@{0}` :

```
git stash list
# stash@{0}: On main: OTP flow WIP — laboria-auth, hors scope context
```

Cette modif :

- touche **toute l'auth memory-neo** → impacte dogydoc en plus de RePTiLS,
- ajoute un fichier `api/services/otp.py` (non importé par le code committed
  → ne casse rien tant que le stash n'est pas ré-appliqué),
- n'a **aucun test**, et n'est ni documentée ni couverte par la suite ici.

→ **Ne pas l'inclure dans le déploiement context.** Elle sera reprise dans
un sprint dédié (`MEMORY-NEO-OTP-AUTH`) avec ses propres tests et un plan
de migration de schéma Prisma propre.

Pour la ré-appliquer plus tard :

```bash
git stash pop stash@{0}
# (ou git stash apply stash@{0} pour la garder dans la stash)
```

## 9. Limites connues v1

| Limite | Plan |
|---|---|
| Pas de `DELETE /context/{episode_id}` | v2 quand RePTiLS aura besoin de cleanup |
| Re-index ne supprime pas les anciennes relations | Documenté — comportement additif historique voulu |
| Pas de `scope_tenant_id` (multi-tenant) | v2 — pour l'instant `scope_user_id` uniquement |
| Pas de pagination cursor | v2 si nécessaire — `limit` suffit pour MVP |
| `email-validator` non listé dans `requirements.api.txt` mais utilisé via `pydantic[email]` | OK en prod (pydantic[email] le tire), ajouter explicitement si on veut lock |
