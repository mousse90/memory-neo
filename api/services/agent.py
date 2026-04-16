# memory-neo/api/services/agent.py
# Path: api/services/agent.py
# Purpose: Smart router — decides between Cypher query and Claude code analysis
# Called by: api/routes/query.py

import os
import anthropic

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ROUTER_PROMPT = """You are a routing agent for a code knowledge graph system.

Given a user question about a codebase, decide which mode to use:

1. "cypher" — for factual/structural questions that can be answered by querying the graph:
   - "show all functions", "list files", "which files import X"
   - "how many functions per file", "show the X function"
   - "find all async functions", "what files are in src/"

2. "analyze" — for questions requiring understanding, reasoning, or explanation:
   - "how does X work", "explain the auth flow"
   - "what should I modify to add Y feature"
   - "is this code well structured", "what does X function do"
   - "find bugs in X", "how can I improve X"

Reply with ONLY one word: cypher OR analyze"""


async def route_question(question: str) -> str:
    """
    Returns "cypher" or "analyze" based on the question type.
    Fast call — uses minimal tokens.
    """
    try:
        msg = _client.messages.create(
            model="claude-haiku-4-5-20251001",  # fast + cheap for routing
            max_tokens=10,
            system=ROUTER_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        answer = msg.content[0].text.strip().lower()
        return "analyze" if "analyze" in answer else "cypher"
    except Exception:
        return "cypher"  # fallback to cypher on error


ANALYZE_SYSTEM = """You are an expert code analyst. You have access to code snippets from a codebase.

When analyzing code:
- Be concise and direct
- Point to specific files and functions
- Give actionable insights
- Format code with triple backticks

Answer the user's question based on the provided code context."""


async def analyze_with_context(
    question: str,
    context: list[dict],
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """
    Analyze code with Claude using retrieved context from Memgraph.
    context: list of result dicts with 'code', 'name', 'file' fields.
    """
    # Build context block
    context_lines = []
    for r in context[:10]:  # limit to 10 results
        if r.get("code"):
            file_info = f"{r.get('file', '')} · {r.get('name', '')}"
            if r.get('start_line'):
                file_info += f" · L{r['start_line']}–{r['end_line']}"
            context_lines.append(f"### {file_info}")
            context_lines.append(f"```\n{r['code']}\n```")
        elif r.get("name"):
            context_lines.append(f"- **{r.get('name')}**: {r.get('path', '')}")

    context_text = "\n\n".join(context_lines) if context_lines else "No code context available."

    user_message = f"""## Codebase context

{context_text}

## Question

{question}"""

    try:
        msg = _client.messages.create(
            model=model,
            max_tokens=1500,
            system=ANALYZE_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"Analysis failed: {e}"