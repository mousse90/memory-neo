# memory-neo — Deployment Guide v0.2
# Fly.io (paid) + Supabase + Vercel

---

## 0. Prérequis

```bash
brew install flyctl
flyctl auth login

# Vérifier le plan payant
flyctl billing show
# → Si toujours gratuit : flyctl billing upgrade
```

---

## 1. Supabase — Schema

### 1.1 Créer le projet Supabase
→ https://supabase.com/dashboard → New project → region: eu-west-1 (Paris)

### 1.2 Appliquer le schema Prisma
```bash
cd memory-neo

# Copier l'URL de connexion depuis Supabase > Settings > Database > Connection string (URI)
export DATABASE_URL="postgresql://postgres:[MOT_DE_PASSE]@[HOST]:5432/postgres"

pip install prisma
prisma generate --schema=api/db/schema.prisma
prisma db push --schema=api/db/schema.prisma
# → Creates tables: users, api_keys, projects, query_logs, push_logs
```

---

## 2. Fly.io — Memgraph (graph database)

### 2.1 Créer l'app Memgraph
```bash
cd memory-neo

flyctl apps create memory-neo-graph --org personal
```

### 2.2 Créer le volume persistant (10 GB)
```bash
flyctl volumes create memgraph_data \
  --size 10 \
  --region cdg \
  --app memory-neo-graph
# → data survives deploys and restarts
```

### 2.3 Déployer Memgraph
```bash
# Le toml est dans deploy/ — fly cherche depuis la racine du projet
flyctl deploy \
  --config deploy/fly.memgraph.toml \
  --dockerfile deploy/memgraph.Dockerfile \
  --app memory-neo-graph
```

### 2.4 Initialiser le schema Memgraph
```bash
# Ouvrir un tunnel bolt local → port 7687
flyctl proxy 7687:7687 --app memory-neo-graph &

# Dans un autre terminal :
# Option A — mgconsole (si installé)
cat deploy/init.cypher | mgconsole --host 127.0.0.1 --port 7687

# Option B — Python one-liner
python3 -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://127.0.0.1:7687')
with d.session() as s:
    for q in open('deploy/init.cypher').read().split(';'):
        q = q.strip()
        if q and not q.startswith('//'):
            s.run(q)
d.close()
print('✓ Indexes created')
"

kill %1  # stop tunnel
```

---

## 3. Fly.io — FastAPI

### 3.1 Créer l'app API
```bash
flyctl apps create memory-neo-api --org personal
```

### 3.2 Injecter les secrets (NE PAS mettre dans le toml)
```bash
flyctl secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  OPENAI_API_KEY="sk-..." \
  DATABASE_URL="postgresql://postgres:[PASSWORD]@[HOST]:5432/postgres" \
  API_SECRET_SALT="$(openssl rand -base64 32)" \
  DEV_API_KEY="local-dev-key" \
  --app memory-neo-api
```

### 3.3 Déployer l'API
```bash
flyctl deploy \
  --config deploy/fly.api.toml \
  --dockerfile deploy/api.Dockerfile \
  --app memory-neo-api

# Vérifier
flyctl status --app memory-neo-api
curl https://memory-neo-api.fly.dev/health
# → {"status":"ok","service":"memory-neo-api","version":"0.2.0"}
```

### 3.4 Créer le premier utilisateur
```bash
curl -X POST https://memory-neo-api.fly.dev/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "ton@email.com"}'
# → {"user_id": "...", "email": "...", "api_key": "mnk_..."}
# Sauvegarder la clé — montrée une seule fois
```

---

## 4. CLI — pointer vers Fly.io

```bash
memory-neo login --api-url https://memory-neo-api.fly.dev
# Paste: mnk_...

memory-neo push memory-neo
# → Push le projet vers Fly.io Memgraph
```

---

## 5. Vercel — UI

### 5.1 Déployer
```bash
cd memory-neo-ui
npx vercel --prod
```

### 5.2 Variables d'environnement dans Vercel Dashboard
```
NEXT_PUBLIC_API_URL      = https://memory-neo-api.fly.dev
NEXT_PUBLIC_DEV_API_KEY  = mnk_...   ← la clé prod
NEXT_PUBLIC_DEV_USER_ID  = [user_id retourné par /auth/register]
```

→ Redeploy après avoir ajouté les variables.

---

## 6. Vérification finale

```bash
# Santé API
curl https://memory-neo-api.fly.dev/health

# Projets (avec ta clé)
curl https://memory-neo-api.fly.dev/projects \
  -H "X-API-Key: mnk_..."

# Query test
curl -X POST https://memory-neo-api.fly.dev/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: mnk_..." \
  -d '{"question":"show all files","project_name":"memory-neo","user_id":"[USER_ID]","model":"claude"}'
```

---

## 7. Commandes utiles

```bash
# Logs API en temps réel
flyctl logs --app memory-neo-api

# Logs Memgraph
flyctl logs --app memory-neo-graph

# SSH dans l'API
flyctl ssh console --app memory-neo-api

# Redéployer l'API seulement
flyctl deploy --config deploy/fly.api.toml --app memory-neo-api

# Voir les secrets (noms seulement)
flyctl secrets list --app memory-neo-api

# Mise à l'échelle
flyctl scale vm performance-1x --app memory-neo-api
```

---

## Architecture finale

```
Vercel (UI)
  next dev / vercel deploy
  NEXT_PUBLIC_API_URL → Fly.io
          │
          ▼
Fly.io: memory-neo-api  (FastAPI, performance-1x, always-on)
  POST /query    → Claude or GPT-4o → Cypher → Memgraph
  POST /push     → Memgraph WRITE + Supabase project registry
  POST /auth/*   → Supabase users/api_keys
  GET  /projects → Supabase project list
          │              │
          ▼              ▼
Fly.io: memory-neo-graph   Supabase (PostgreSQL)
  Memgraph bolt:7687        users, api_keys
  Volume: memgraph_data     projects, query_logs
  (10GB persistent)         push_logs
```
