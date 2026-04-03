# memory-neo/api/services/nlp.py
# Path: api/services/nlp.py
# Purpose: Convert NL questions to Memgraph Cypher — supports Claude and GPT-4o
# Called by: api/routes/query.py

import os
from typing import Literal

ModelChoice = Literal["claude", "gpt-4o"]

# ── Shared system prompt ───────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Cypher query generator for a code knowledge graph stored in Memgraph.

GRAPH SCHEMA:
  (:Project  {namespace: String, name: String})
  (:File     {namespace: String, name: String, path: String, extension: String, lines: Int, content: String})
  (:Function {namespace: String, name: String, file_path: String, start_line: Int, end_line: Int, code: String, docstring: String, args: List<String>, is_async: Boolean})

RELATIONSHIPS:
  (:Project)-[:CONTAINS]->(:File)
  (:File)-[:HAS_FUNCTION]->(:Function)

RULES:
1. Every node must be filtered by namespace = $namespace — ALWAYS include this.
2. Return ONLY the Cypher query — no explanation, no markdown, no backticks.
3. Use MATCH and RETURN only. Never CREATE, MERGE, DELETE, or SET.
4. For function content queries, always RETURN fn.code.
5. For file listing, RETURN f.name, f.path, f.lines.
6. For counting functions per file: MATCH (f:File {namespace: $namespace})-[:HAS_FUNCTION]->(fn:Function {namespace: $namespace}) RETURN f.name AS file, count(fn) AS function_count ORDER BY function_count DESC
7. For keyword search, use toLower(fn.name) CONTAINS toLower('keyword') OR toLower(fn.code) CONTAINS toLower('keyword').
8. NEVER use size() with relationship patterns — Memgraph does not support it.
9. If unsure, return a safe broad MATCH with LIMIT 20.

EXAMPLES:

User: "show all auth functions"
Cypher: MATCH (f:File {namespace: $namespace})-[:HAS_FUNCTION]->(fn:Function {namespace: $namespace}) WHERE toLower(fn.name) CONTAINS 'auth' OR toLower(fn.code) CONTAINS 'auth' RETURN f.path AS file, fn.name AS name, fn.start_line AS start_line, fn.end_line AS end_line, fn.code AS code

User: "list all Python files"
Cypher: MATCH (f:File {namespace: $namespace, extension: '.py'}) RETURN f.name AS name, f.path AS path, f.lines AS lines ORDER BY f.path

User: "which files import httpx"
Cypher: MATCH (f:File {namespace: $namespace}) WHERE f.content CONTAINS 'import httpx' OR f.content CONTAINS 'from httpx' RETURN f.name AS name, f.path AS path

User: "show the parse_directory function"
Cypher: MATCH (f:File {namespace: $namespace})-[:HAS_FUNCTION]->(fn:Function {namespace: $namespace}) WHERE fn.name = 'parse_directory' RETURN f.path AS file, fn.name AS name, fn.start_line AS start_line, fn.end_line AS end_line, fn.code AS code

User: "how many functions are in each file"
Cypher: MATCH (f:File {namespace: $namespace})-[:HAS_FUNCTION]->(fn:Function {namespace: $namespace}) RETURN f.name AS file, f.path AS path, count(fn) AS function_count ORDER BY function_count DESC

User: "show all files"
Cypher: MATCH (f:File {namespace: $namespace}) RETURN f.name AS name, f.path AS path, f.lines AS lines ORDER BY f.path

User: "show all functions"
Cypher: MATCH (f:File {namespace: $namespace})-[:HAS_FUNCTION]->(fn:Function {namespace: $namespace}) RETURN f.path AS file, fn.name AS name, fn.start_line AS start_line, fn.end_line AS end_line, fn.code AS code ORDER BY f.path, fn.start_line
"""


def _clean_cypher(raw: str, namespace: str) -> str:
    """Strip markdown fences and inject namespace value."""
    cleaned = raw.replace("```cypher", "").replace("```", "").strip()
    return cleaned.replace("$namespace", f'"{namespace}"')


# ── Claude ─────────────────────────────────────────────────────────────────────

async def _query_claude(question: str, namespace: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Namespace: {namespace}\n\nQuestion: {question}",
            }
        ],
    )
    return _clean_cypher(message.content[0].text.strip(), namespace)


# ── GPT-4o ─────────────────────────────────────────────────────────────────────

async def _query_openai(question: str, namespace: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Namespace: {namespace}\n\nQuestion: {question}"},
        ],
        max_tokens=500,
        temperature=0,
    )
    return _clean_cypher(response.choices[0].message.content.strip(), namespace)


# ── Public entrypoint ──────────────────────────────────────────────────────────

async def question_to_cypher(
    question: str,
    namespace: str,
    model: ModelChoice = "claude",
) -> str:
    """
    Convert a natural language question to Cypher.
    model: "claude" (default) | "gpt-4o"
    """
    if model == "gpt-4o":
        return await _query_openai(question, namespace)
    return await _query_claude(question, namespace)