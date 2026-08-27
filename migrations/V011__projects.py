"""V011 - projects table and session project grouping.

Adds the ``projects`` table (per-agent grouping of chat sessions with
free-form knowledge text injected into member sessions' prompts) and a
nullable ``sessions.project_id`` column. Existing sessions need no
backfill: NULL ``project_id`` means "not in a project", which is the
intended state for every pre-existing row.
"""

from __future__ import annotations

from yoyo import step

__depends__: set[str] = {"V010__transcript_turn_usage"}

CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL DEFAULT 'main',
    name TEXT NOT NULL,
    knowledge TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""


def _table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _has_column(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def apply_step(conn) -> None:
    cur = conn.cursor()
    cur.execute(CREATE_PROJECTS)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_agent ON projects(agent_id)")
    if _table_exists(conn, "sessions"):
        if not _has_column(conn, "sessions", "project_id"):
            cur.execute("ALTER TABLE sessions ADD COLUMN project_id TEXT")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id)"
        )


def rollback_step(conn) -> None:
    # The sessions.project_id column is intentionally left in place: SQLite
    # DROP COLUMN rewrites the table and fails on indexed columns in older
    # SQLite builds. A stray nullable column is harmless to prior code.
    cur = conn.cursor()
    cur.execute("DROP INDEX IF EXISTS idx_sessions_project")
    cur.execute("DROP INDEX IF EXISTS idx_projects_agent")
    cur.execute("DROP TABLE IF EXISTS projects")


steps = [step(apply_step, rollback_step)]
