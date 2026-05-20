// memory-neo/deploy/memgraph_init_context.cypher
// Path: deploy/memgraph_init_context.cypher
// Purpose: indexes for the parallel multimodal "context" graph
//          (RePTiLS CONTEXT-SIGNATURE sprint).
// Idempotent: re-running is safe — Memgraph throws on duplicate index,
// catch it at the client side (api/services/context_graph.py does this
// automatically on each app startup).
//
// To apply manually:
//   mgconsole -host <host> -port 7687 < deploy/memgraph_init_context.cypher

CREATE INDEX ON :Episode(id);
CREATE INDEX ON :Episode(scope_user_id);
CREATE INDEX ON :Episode(when);

CREATE INDEX ON :Activity(name);
CREATE INDEX ON :Activity(scope_user_id);

CREATE INDEX ON :Topic(name);
CREATE INDEX ON :Topic(scope_user_id);

CREATE INDEX ON :ActivityObject(name);
CREATE INDEX ON :ActivityObject(scope_user_id);

CREATE INDEX ON :Where(name);
CREATE INDEX ON :Where(scope_user_id);

CREATE INDEX ON :TimeSlot(name);
CREATE INDEX ON :TimeSlot(scope_user_id);
