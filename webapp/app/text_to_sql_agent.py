"""
Text-to-SQL Engineer — LangGraph agent that converts natural language
planning questions into SQL, executes them, and returns grounded rows.

Graph
-----
    select_tables → generate_sql → execute_sql ──(error + retries left)──► generate_sql
                                                └──(success or max retries)──► validate_result → END

Backends
--------
    DuckDB   (default) — reads BY input/output CSV files in-memory
    Snowflake          — swap in when Snowflake connectivity is available
    Controlled by SQL_BACKEND env var (default: duckdb)

SQL Model
---------
    A dedicated Ollama model for SQL generation, separate from the chat model.
    Set OLLAMA_SQL_MODEL (e.g. sqlcoder:7b, codellama:13b-instruct).
    Falls back to OLLAMA_MODEL if not set.
"""

import json
import operator
import os
import re
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional
from urllib import error, request as urllib_request

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from .analyzer import (
    INPUT_FOLDER,
    OUTPUT_FOLDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    _chat_table_catalog,
    _match_tables_for_question,
    _resolve_context,
    _safe_rows,
)
from .sql_backends import get_backend, is_safe_sql

OLLAMA_SQL_MODEL = os.getenv("OLLAMA_SQL_MODEL", OLLAMA_MODEL)
MAX_RETRIES = 2
MAX_RESULT_ROWS = 200
MAX_SAMPLE_ROWS = 2


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class SqlAgentState(TypedDict):
    # ── inputs ──────────────────────────────────────────────────────────────
    question: str
    base_dir: str
    week_id: Optional[str]
    scenario_id: Optional[str]
    scope: Dict[str, Any]

    # ── filled by select_tables ──────────────────────────────────────────────
    selected_tables: List[Dict[str, Any]]
    schema_context: str
    table_file_map: Dict[str, str]   # clean_table_name -> abs_file_path

    # ── filled by generate_sql ───────────────────────────────────────────────
    sql: Optional[str]
    attempt: int
    last_error: Optional[str]

    # ── filled by execute_sql ────────────────────────────────────────────────
    result_rows: Optional[List[Dict[str, Any]]]
    execution_error: Optional[str]
    row_count: int

    # ── filled by validate_result ────────────────────────────────────────────
    is_valid: bool
    validation_note: str

    # ── append-only attempt log ──────────────────────────────────────────────
    attempts_log: Annotated[List[Dict[str, Any]], operator.add]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_rows(file_path: str, n: int = MAX_SAMPLE_ROWS) -> List[Dict[str, str]]:
    """Read the first n rows from a pipe-delimited CSV file."""
    rows: List[Dict[str, str]] = []
    try:
        for row in _safe_rows(Path(file_path)):
            rows.append(dict(row))
            if len(rows) >= n:
                break
    except Exception:
        pass
    return rows


def _truncate_values(row: Dict, max_len: int = 40) -> Dict:
    return {k: (str(v)[:max_len] if v is not None else None) for k, v in row.items()}


def _build_schema_context(
    selected_tables: List[Dict[str, Any]],
    table_file_map: Dict[str, str],
    week_id: Optional[str],
    scenario_id: Optional[str],
    site: Optional[str],
) -> str:
    sections: List[str] = []
    for tbl in selected_tables:
        name = tbl.get("table") or ""
        file_path = table_file_map.get(name, "")
        cols = tbl.get("columns") or []
        rows_count = tbl.get("rows", 0)

        sample = _sample_rows(file_path) if file_path else []

        parts = [
            f"Table: {name}",
            f"Rows: {rows_count}",
            f"Columns: {', '.join(str(c) for c in cols)}",
        ]
        if sample:
            parts.append("Sample rows:")
            for i, row in enumerate(sample, 1):
                parts.append(f"  {i}: {json.dumps(_truncate_values(row), ensure_ascii=True)}")
        sections.append("\n".join(parts))

    context_filters: List[str] = []
    if week_id:
        context_filters.append(f"CAPTURE_WK = '{week_id}'")
    if scenario_id:
        context_filters.append(f"SIMULATION_NAME = '{scenario_id}'")
    if site:
        context_filters.append(f"LOC = '{site}'")

    header = "\n\n".join(sections)
    if context_filters:
        header += (
            "\n\n-- Suggested context filters (apply when columns exist):\n"
            + "\n".join(f"-- WHERE {f}" for f in context_filters)
        )
    return header


def _call_ollama_sql(prompt: str) -> Optional[str]:
    """Call the dedicated SQL Ollama model. Returns raw response text."""
    system = (
        "You are a SQL expert for Intel Foundry planning data. "
        "Generate a single DuckDB-compatible SELECT statement that answers the question. "
        "Rules: "
        "1. Return ONLY the SQL query — no explanation, no markdown code blocks, no comments. "
        "2. Use exact table and column names from the schema provided. "
        "3. Always alias aggregates (e.g. COUNT(*) AS row_count). "
        "4. Apply context filters shown in the schema when those columns exist. "
        "5. Never use INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, or TRUNCATE. "
        "6. If you cannot answer with the given schema, return: SELECT 'insufficient_schema' AS status"
    )
    payload = {
        "model": OLLAMA_SQL_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.0},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return ((body.get("message") or {}).get("content") or "").strip() or None


def _extract_sql(raw: str) -> str:
    """Strip markdown code fences and extract the SQL."""
    text = (raw or "").strip()
    # Remove ```sql ... ``` or ``` ... ```
    text = re.sub(r"```(?:sql)?\s*", "", text, flags=re.IGNORECASE).strip("`").strip()
    # Take only up to first semicolon (inclusive)
    match = re.search(r"(select\b.+?)(?:;|$)", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


# ---------------------------------------------------------------------------
# Node 1 – select_tables
# ---------------------------------------------------------------------------

def select_tables(state: SqlAgentState) -> Dict[str, Any]:
    base_dir = Path(state["base_dir"])
    question = state["question"]
    week_id = state.get("week_id")
    scenario_id = state.get("scenario_id")
    scope = state.get("scope") or {}
    site = (scope.get("site") or "").strip() or None

    catalog = _chat_table_catalog(base_dir)
    matched = _match_tables_for_question(question, catalog, max_tables=6)

    # Build file map: clean table name -> absolute path
    table_file_map: Dict[str, str] = {}
    for tbl in matched:
        name = tbl.get("table") or ""
        file_name = tbl.get("file") or ""
        family = tbl.get("family") or "output"
        folder = INPUT_FOLDER if family == "input" else OUTPUT_FOLDER
        full_path = base_dir / folder / file_name
        if full_path.exists():
            table_file_map[name] = str(full_path)

    schema_ctx = _build_schema_context(matched, table_file_map, week_id, scenario_id, site)

    return {
        "selected_tables": matched,
        "schema_context": schema_ctx,
        "table_file_map": table_file_map,
        "attempts_log": [],
    }


# ---------------------------------------------------------------------------
# Node 2 – generate_sql
# ---------------------------------------------------------------------------

def generate_sql(state: SqlAgentState) -> Dict[str, Any]:
    question = state["question"]
    schema_context = state.get("schema_context") or ""
    attempt = state.get("attempt", 0)
    last_error = state.get("last_error")

    prompt_parts = [
        f"Schema:\n{schema_context}",
        f"Question: {question}",
    ]
    if last_error:
        prompt_parts.append(
            f"Previous SQL failed with error:\n{last_error}\n"
            "Please fix the SQL and try again."
        )
    prompt_parts.append("SQL:")

    raw = _call_ollama_sql("\n\n".join(prompt_parts))
    sql = _extract_sql(raw or "") if raw else None

    return {
        "sql": sql,
        "attempt": attempt + 1,
        "last_error": None,
        "attempts_log": [{"attempt": attempt + 1, "sql": sql, "raw_response": raw}],
    }


# ---------------------------------------------------------------------------
# Node 3 – execute_sql
# ---------------------------------------------------------------------------

def execute_sql(state: SqlAgentState) -> Dict[str, Any]:
    sql = (state.get("sql") or "").strip()
    table_file_map = state.get("table_file_map") or {}

    if not sql:
        return {
            "result_rows": None,
            "execution_error": "No SQL was generated.",
            "row_count": 0,
        }

    if not is_safe_sql(sql):
        return {
            "result_rows": None,
            "execution_error": f"Rejected: only SELECT statements are allowed. Got: {sql[:120]}",
            "row_count": 0,
        }

    try:
        with get_backend() as backend:
            backend.register_tables(table_file_map)
            rows = backend.execute(sql, max_rows=MAX_RESULT_ROWS)
        return {
            "result_rows": rows,
            "execution_error": None,
            "row_count": len(rows),
        }
    except Exception as exc:
        return {
            "result_rows": None,
            "execution_error": str(exc),
            "row_count": 0,
        }


def _route_after_execute(state: SqlAgentState) -> str:
    err = state.get("execution_error")
    attempt = state.get("attempt", 0)
    if err and attempt < MAX_RETRIES:
        return "generate_sql"
    return "validate_result"


# ---------------------------------------------------------------------------
# Node 4 – validate_result
# ---------------------------------------------------------------------------

def validate_result(state: SqlAgentState) -> Dict[str, Any]:
    rows = state.get("result_rows")
    err = state.get("execution_error")
    sql = state.get("sql") or ""

    if err:
        return {
            "is_valid": False,
            "validation_note": f"SQL execution failed after {state.get('attempt', 0)} attempt(s): {err}",
        }
    if rows is None:
        return {"is_valid": False, "validation_note": "No result returned."}
    if len(rows) == 0:
        return {
            "is_valid": True,
            "validation_note": "Query executed successfully but returned 0 rows. Try broadening filters.",
        }
    return {
        "is_valid": True,
        "validation_note": f"Query returned {len(rows)} row(s).",
    }


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    builder: StateGraph = StateGraph(SqlAgentState)
    builder.add_node("select_tables", select_tables)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("execute_sql", execute_sql)
    builder.add_node("validate_result", validate_result)

    builder.set_entry_point("select_tables")
    builder.add_edge("select_tables", "generate_sql")
    builder.add_edge("generate_sql", "execute_sql")
    builder.add_conditional_edges(
        "execute_sql",
        _route_after_execute,
        {"generate_sql": "generate_sql", "validate_result": "validate_result"},
    )
    builder.add_edge("validate_result", END)
    return builder.compile()


_graph = _build_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_sql_query(
    base_dir: Path,
    question: str,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run the Text-to-SQL Engineer for a natural language planning question.

    Pipeline: select_tables → generate_sql → execute_sql
              └──(retry on error, max 2)──┘
    → validate_result → return structured result

    Returns a dict with:
      Workflow, SQL, Result Rows, Row Count, Selected Tables,
      Is Valid, Validation Note, Backend, Attempts Log
    """
    context = _resolve_context(base_dir, week_id, scenario_id)

    initial: SqlAgentState = {
        "question": (question or "").strip(),
        "base_dir": str(base_dir),
        "week_id": context.get("week_id"),
        "scenario_id": context.get("scenario_id"),
        "scope": dict(scope or {}),
        # filled by nodes
        "selected_tables": [],
        "schema_context": "",
        "table_file_map": {},
        "sql": None,
        "attempt": 0,
        "last_error": None,
        "result_rows": None,
        "execution_error": None,
        "row_count": 0,
        "is_valid": False,
        "validation_note": "",
        "attempts_log": [],
    }

    final: SqlAgentState = _graph.invoke(initial)

    backend_name = os.getenv("SQL_BACKEND", "duckdb").strip().lower()

    return {
        "Workflow": "Text-to-SQL",
        "Backend": backend_name,
        "Question": question,
        "Context Resolution": context,
        "Selected Tables": [t.get("table") for t in (final.get("selected_tables") or [])],
        "SQL Generated": final.get("sql"),
        "Is Valid": final.get("is_valid"),
        "Validation Note": final.get("validation_note"),
        "Row Count": final.get("row_count", 0),
        "Result Rows": final.get("result_rows") or [],
        "Attempts": final.get("attempt", 0),
        "Attempts Log": final.get("attempts_log") or [],
        "Note": (
            f"Backend: {backend_name.upper()}. "
            "Switch to Snowflake by setting SQL_BACKEND=snowflake and configuring SNOWFLAKE_* env vars. "
            f"SQL model: {OLLAMA_SQL_MODEL}."
        ),
    }
