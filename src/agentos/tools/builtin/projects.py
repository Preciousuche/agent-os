"""Project tools: create, list, update knowledge, move sessions.

Projects group chat sessions across agents; each project's ``knowledge``
text is injected into the system prompt of every member session. These
tools let the agent manage projects from prompting — the same operations
the ``projects.*`` RPC surface exposes to the Web UI and CLI.
"""

from __future__ import annotations

import json

import structlog

from agentos.tools.registry import tool
from agentos.tools.types import ToolError, current_tool_context

_log = structlog.get_logger("agentos.tools.projects")

# ---------------------------------------------------------------------------
# Setter-injected session manager (gateway boot calls set_session_manager)
# ---------------------------------------------------------------------------

_session_manager = None


def set_session_manager(mgr: object) -> None:
    """Inject the SessionManager instance (called from gateway boot)."""
    global _session_manager
    _session_manager = mgr


def _get_session_manager():  # noqa: ANN202
    if _session_manager is None:
        raise ToolError("Session manager not available")
    return _session_manager


def _manager_unavailable(exc: Exception) -> ToolError:
    return ToolError(f"Session manager not available: {exc}")


def _resolve_agent_id(agent_id: str | None) -> str:
    resolved = (agent_id or "").strip()
    if not resolved:
        ctx = current_tool_context.get()
        resolved = getattr(ctx, "agent_id", "") if ctx else ""
    return resolved or "main"


def _current_session_key() -> str | None:
    ctx = current_tool_context.get()
    return getattr(ctx, "session_key", None) if ctx else None


# ---------------------------------------------------------------------------
# projects_create
# ---------------------------------------------------------------------------


@tool(
    name="projects_create",
    description=(
        "Create a project grouping chat sessions. The knowledge text is "
        "injected into the system prompt of every session in the project."
    ),
    params={
        "name": {
            "type": "string",
            "description": "Project name (unique across projects).",
        },
        "knowledge": {
            "type": "string",
            "description": "Optional shared knowledge/instructions text for the project.",
        },
        "agent_id": {
            "type": "string",
            "description": (
                "Default agent for new chats in the project "
                "(defaults to the calling agent); not a membership boundary."
            ),
        },
    },
    required=["name"],
)
async def projects_create(
    name: str = "",
    knowledge: str = "",
    agent_id: str | None = None,
) -> str:
    try:
        mgr = _get_session_manager()
        project = await mgr.create_project(
            agent_id=_resolve_agent_id(agent_id),
            name=name,
            knowledge=knowledge,
        )
        return json.dumps(project, ensure_ascii=False)
    except (ToolError, ValueError):
        raise
    except (ImportError, AttributeError, NotImplementedError) as exc:
        raise _manager_unavailable(exc) from exc


# ---------------------------------------------------------------------------
# projects_list
# ---------------------------------------------------------------------------


@tool(
    name="projects_list",
    description="List projects (with per-project session counts).",
    params={
        "agent_id": {
            "type": "string",
            "description": "Filter by owning agent ID (defaults to all agents).",
        },
    },
    required=[],
)
async def projects_list(agent_id: str | None = None) -> str:
    try:
        mgr = _get_session_manager()
        projects = await mgr.list_projects(agent_id=agent_id or None)
        return json.dumps(projects, ensure_ascii=False)
    except ToolError:
        raise
    except (ImportError, AttributeError, NotImplementedError) as exc:
        raise _manager_unavailable(exc) from exc


# ---------------------------------------------------------------------------
# projects_update
# ---------------------------------------------------------------------------


@tool(
    name="projects_update",
    description=(
        "Rename a project and/or replace its shared knowledge text. Member "
        "sessions pick up the new knowledge on their next turn."
    ),
    params={
        "project_id": {
            "type": "string",
            "description": "Project ID to update.",
        },
        "name": {
            "type": "string",
            "description": "New project name.",
        },
        "knowledge": {
            "type": "string",
            "description": "Replacement knowledge text (full replace, not append).",
        },
    },
    required=["project_id"],
)
async def projects_update(
    project_id: str = "",
    name: str | None = None,
    knowledge: str | None = None,
) -> str:
    if not project_id.strip():
        raise ToolError("project_id must not be empty")
    if name is None and knowledge is None:
        raise ToolError("Provide name and/or knowledge to update")
    try:
        mgr = _get_session_manager()
        project = await mgr.update_project(project_id.strip(), name=name, knowledge=knowledge)
        return json.dumps(project, ensure_ascii=False)
    except (ToolError, ValueError):
        raise
    except KeyError as exc:
        raise ToolError(f"Project not found: {project_id}") from exc
    except (ImportError, AttributeError, NotImplementedError) as exc:
        raise _manager_unavailable(exc) from exc


# ---------------------------------------------------------------------------
# projects_move_session
# ---------------------------------------------------------------------------


@tool(
    name="projects_move_session",
    description=(
        "Move a session into a project, or detach it by omitting project_id. "
        "Defaults to the calling session when session_key is omitted."
    ),
    params={
        "project_id": {
            "type": "string",
            "description": "Target project ID; omit to detach the session from its project.",
        },
        "session_key": {
            "type": "string",
            "description": "Session to move (defaults to the calling session).",
        },
    },
    required=[],
)
async def projects_move_session(
    project_id: str | None = None,
    session_key: str | None = None,
) -> str:
    resolved_key = (session_key or "").strip() or _current_session_key()
    if not resolved_key:
        raise ToolError("session_key is required (no calling session available)")
    try:
        mgr = _get_session_manager()
        node = await mgr.move_session_to_project(
            resolved_key,
            (project_id or "").strip() or None,
        )
        return json.dumps(
            {
                "session_key": node.session_key,
                "project_id": node.project_id,
            }
        )
    except (ToolError, ValueError):
        raise
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    except (ImportError, AttributeError, NotImplementedError) as exc:
        raise _manager_unavailable(exc) from exc
