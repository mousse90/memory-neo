// memory-neo/deploy/init.cypher
// Path: deploy/init.cypher
// Purpose: Memgraph schema initialization — indexes for fast lookups
// Run once on fresh Memgraph instance:
//   cat deploy/init.cypher | mgconsole

// ── Indexes ───────────────────────────────────────────────────────────────────
// Memgraph uses label+property indexes for MATCH performance

CREATE INDEX ON :Project(namespace);
CREATE INDEX ON :File(namespace);
CREATE INDEX ON :File(path);
CREATE INDEX ON :Function(namespace);
CREATE INDEX ON :Function(name);
CREATE INDEX ON :Function(file_path);

// ── Constraints ───────────────────────────────────────────────────────────────
// Uniqueness constraints also create indexes

CREATE CONSTRAINT ON (p:Project) ASSERT p.namespace IS UNIQUE;

// ── Verify ────────────────────────────────────────────────────────────────────
// After running, verify with:
//   SHOW INDEX INFO;
//   SHOW CONSTRAINT INFO;
