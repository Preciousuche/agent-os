"""Regression tests ensuring execute_code cleans up temporary directories (Issue #1).

When running execute_code without a configured workspace, an ephemeral
directory is allocated in tempfile.mkdtemp. It must be cleaned up on every
return path, including sandbox denials and execution completions.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agentos.tools.builtin.code_exec import execute_code
from agentos.tools.types import ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_execute_code_cleans_up_ephemeral_workdir_on_denial() -> None:
    temp_root = Path(tempfile.gettempdir())
    before = set(temp_root.glob("agentos_exec_*"))

    # When ToolContext has no workspace_dir and runtime is unconfigured,
    # gate_action denies execution, which must trigger finally cleanup.
    token = current_tool_context.set(ToolContext(workspace_dir=None))
    try:
        await execute_code(code="print('test')")
    finally:
        current_tool_context.reset(token)

    after = set(temp_root.glob("agentos_exec_*"))
    leaked = after - before
    assert len(leaked) == 0, f"Leaked temporary directories: {leaked}"
