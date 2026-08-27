"""Tests for the V011 projects migration."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import patch


def _load_migration():
    migration_path = Path(__file__).resolve().parents[2] / "migrations" / "V011__projects.py"
    spec = importlib.util.spec_from_file_location("v011_projects", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    with patch("yoyo.step", lambda apply, rollback: (apply, rollback)):
        spec.loader.exec_module(migration)
    return migration


def test_v011_adds_projects_table_and_session_column_idempotently() -> None:
    migration = _load_migration()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE sessions (session_key TEXT PRIMARY KEY, agent_id TEXT)"
        )
        conn.execute(
            "INSERT INTO sessions (session_key, agent_id) VALUES (?, ?)",
            ("agent:main:legacy", "main"),
        )

        migration.apply_step(conn)
        migration.apply_step(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "project_id" in columns

        # Existing rows become project-less — that IS the data migration.
        row = conn.execute(
            "SELECT project_id FROM sessions WHERE session_key = ?",
            ("agent:main:legacy",),
        ).fetchone()
        assert row == (None,)

        project_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        assert {
            "project_id",
            "agent_id",
            "name",
            "knowledge",
            "created_at",
            "updated_at",
            "schema_version",
        } == project_columns
    finally:
        conn.close()


def test_v011_applies_on_fresh_database_without_sessions_table() -> None:
    migration = _load_migration()
    conn = sqlite3.connect(":memory:")
    try:
        migration.apply_step(conn)
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


def test_v011_rollback_drops_projects_but_keeps_session_column() -> None:
    migration = _load_migration()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE sessions (session_key TEXT PRIMARY KEY, agent_id TEXT)"
        )
        migration.apply_step(conn)
        migration.rollback_step(conn)
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
            ).fetchone()
            is None
        )
        # sessions.project_id is intentionally kept (SQLite DROP COLUMN fragility).
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "project_id" in columns
    finally:
        conn.close()
