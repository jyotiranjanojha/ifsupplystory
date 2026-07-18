"""
SQL execution backends for the Text-to-SQL Engineer.

Provides a pluggable abstraction so the same LangGraph agent works against:
  - DuckDB (default) — reads BY input/output CSV files in-memory, zero setup
  - Snowflake       — drop-in swap once Snowflake connectivity is available

Switch via:
    SQL_BACKEND=duckdb      (default)
    SQL_BACKEND=snowflake
"""

import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List


def _as_bool(value: str, default: bool = False) -> bool:
    """Parse common truthy strings from environment values."""
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# ---------------------------------------------------------------------------
# Security guard
# ---------------------------------------------------------------------------

_UNSAFE_SQL_RE = re.compile(
    r"^\s*(insert|update|delete|drop|create|alter|truncate|merge|replace|grant|revoke)\b",
    re.IGNORECASE,
)


def is_safe_sql(sql: str) -> bool:
    """Return True only for SELECT statements. Blocks all destructive operations."""
    stripped = (sql or "").lstrip()
    return stripped.lower().startswith("select") and not _UNSAFE_SQL_RE.match(stripped)


def _wrap_with_limit(sql: str, max_rows: int) -> str:
    """Append LIMIT if not already present."""
    clean = sql.rstrip("; \n\t")
    if re.search(r"\blimit\b", clean, re.IGNORECASE):
        return clean
    return f"{clean} LIMIT {max_rows}"


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class SqlBackend(ABC):
    """Abstract SQL execution backend."""

    @abstractmethod
    def register_tables(self, table_file_map: Dict[str, str]) -> None:
        """
        Declare which planning tables are available before query execution.

        Args:
            table_file_map: { clean_table_name -> absolute_file_path }
                            DuckDB uses this to create in-memory views.
                            Snowflake ignores it (tables already in the DB).
        """

    @abstractmethod
    def execute(self, sql: str, max_rows: int = 200) -> List[Dict[str, Any]]:
        """Execute a SELECT statement. Returns rows as list of dicts."""

    @abstractmethod
    def close(self) -> None:
        """Release backend resources."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# DuckDB backend — default, works today on CSV snapshots
# ---------------------------------------------------------------------------

class DuckDBBackend(SqlBackend):
    """
    In-memory DuckDB backend.

    Registers each planning CSV file as a DuckDB VIEW so the generated SQL
    can query it directly using the clean table name (no timestamp suffix).
    Requires: pip install duckdb>=0.10
    """

    def __init__(self) -> None:
        import duckdb  # type: ignore
        self._conn = duckdb.connect(":memory:")
        self._registered: List[str] = []
        self._use_pandas = _as_bool(os.getenv("SQL_USE_PANDAS", "false"), default=False)

    def _register_from_dataframe(self, safe_name: str, file_path: str) -> None:
        """Register a CSV as a DataFrame-backed DuckDB view."""
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "SQL_USE_PANDAS=true requires pandas. "
                "Install it with: pip install pandas"
            ) from exc

        frame = pd.read_csv(
            file_path,
            sep="|",
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            on_bad_lines="skip",
        )
        temp_name = f"_df_{safe_name}"
        self._conn.register(temp_name, frame)
        self._conn.execute(f"CREATE OR REPLACE VIEW {safe_name} AS SELECT * FROM {temp_name}")

    def register_tables(self, table_file_map: Dict[str, str]) -> None:
        for table_name, file_path in table_file_map.items():
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
            if self._use_pandas:
                self._register_from_dataframe(safe_name, file_path)
            else:
                posix_path = Path(file_path).as_posix()
                self._conn.execute(
                    f"CREATE OR REPLACE VIEW {safe_name} AS "
                    f"SELECT * FROM read_csv('{posix_path}', "
                    f"delim='|', header=true, ignore_errors=true)"
                )
            self._registered.append(safe_name)

    def execute(self, sql: str, max_rows: int = 200) -> List[Dict[str, Any]]:
        wrapped = _wrap_with_limit(sql, max_rows)
        result = self._conn.execute(wrapped)
        cols = [desc[0] for desc in (result.description or [])]
        rows = result.fetchall()
        return [dict(zip(cols, row)) for row in rows]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Snowflake backend — stub, ready to wire when Snowflake is available
# ---------------------------------------------------------------------------

class SnowflakeBackend(SqlBackend):
    """
    Snowflake backend — placeholder for future connectivity.

    ── When Snowflake access is available ──────────────────────────────────
    1.  pip install snowflake-connector-python
    2.  Set SQL_BACKEND=snowflake
    3.  Configure environment variables:

        SNOWFLAKE_ACCOUNT    your-account.snowflakecomputing.com
        SNOWFLAKE_USER       your_user
        SNOWFLAKE_PASSWORD   your_password   (or use key-pair auth)
        SNOWFLAKE_DATABASE   IFSP_DB
        SNOWFLAKE_SCHEMA     BY_ESP
        SNOWFLAKE_WAREHOUSE  COMPUTE_WH
        SNOWFLAKE_ROLE       PLANNER_ROLE

    ── What changes vs DuckDB ───────────────────────────────────────────────
    - register_tables() becomes a no-op (tables already exist in Snowflake)
    - execute() runs SQL against the Snowflake warehouse
    - Table names in generated SQL must match Snowflake table names exactly
      (e.g. IF_SNOP_ITEMS, BY_IF_SNOP_OUT_INDDMDVIEW)
    - OLLAMA_SQL_MODEL should be set to a capable coding model
      (e.g. sqlcoder:7b, codellama:13b-instruct)

    ── Switch is one config line ────────────────────────────────────────────
    SQL_BACKEND=snowflake
    """

    def __init__(self) -> None:
        try:
            import snowflake.connector  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "snowflake-connector-python is not installed. "
                "Run: pip install snowflake-connector-python"
            ) from exc

        required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise EnvironmentError(
                f"Missing required Snowflake env vars: {missing}. "
                "See SnowflakeBackend docstring for full configuration."
            )

        self._conn = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ.get("SNOWFLAKE_PASSWORD", ""),
            database=os.environ.get("SNOWFLAKE_DATABASE", ""),
            schema=os.environ.get("SNOWFLAKE_SCHEMA", ""),
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
            role=os.environ.get("SNOWFLAKE_ROLE", ""),
        )
        self._cursor = self._conn.cursor()
        self._use_pandas = _as_bool(os.getenv("SNOWFLAKE_USE_PANDAS", "false"), default=False)

    def register_tables(self, table_file_map: Dict[str, str]) -> None:
        # Tables already live in Snowflake — no registration needed.
        pass

    def execute(self, sql: str, max_rows: int = 200) -> List[Dict[str, Any]]:
        wrapped = _wrap_with_limit(sql, max_rows)
        if self._use_pandas:
            try:
                import pandas as pd  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "SNOWFLAKE_USE_PANDAS=true requires pandas. "
                    "Install it with: pip install pandas"
                ) from exc
            frame = pd.read_sql(wrapped, self._conn)
            return frame.to_dict(orient="records")

        self._cursor.execute(wrapped)
        cols = [desc[0] for desc in (self._cursor.description or [])]
        rows = self._cursor.fetchall()
        return [dict(zip(cols, row)) for row in rows]

    def close(self) -> None:
        try:
            self._cursor.close()
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_backend() -> SqlBackend:
    """
    Return the active SQL backend.

    Reads SQL_BACKEND env var (default: duckdb).
    Extend this function to add new backends.
    """
    name = os.getenv("SQL_BACKEND", "duckdb").strip().lower()
    if name == "snowflake":
        return SnowflakeBackend()
    return DuckDBBackend()
