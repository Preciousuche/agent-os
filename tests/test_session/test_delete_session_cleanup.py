"""delete_session must remove every session-scoped row, not just transcripts."""

from __future__ import annotations

from agentos.session.models import (
    AgentTaskRecord,
    AgentTaskStatus,
    MemoryDurableReceipt,
    SessionNode,
    TranscriptEntry,
)
from agentos.session.storage import SessionStorage

# Fixed epoch ms so the tests never read the system clock.
_T0 = 1_700_000_000_000

SESSION_KEY = "agent:main:webchat:direct:peer-1"


async def _seed(storage: SessionStorage, *, session_id: str, task_id: str) -> None:
    await storage.upsert_session(
        SessionNode(
            session_key=SESSION_KEY,
            session_id=session_id,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    await storage.append_transcript_entry(
        TranscriptEntry(
            session_id=session_id,
            session_key=SESSION_KEY,
            message_id=f"{task_id}-msg",
            role="user",
            content="secret question",
            created_at=_T0,
        )
    )
    await storage.create_agent_task(
        AgentTaskRecord(
            task_id=task_id,
            session_key=SESSION_KEY,
            source_kind="webui",
            queue_mode="followup",
            run_kind="web_turn",
            status=AgentTaskStatus.SUCCEEDED,
            created_at=_T0,
            updated_at=_T0,
            details={"metadata": {"channel": "webchat"}},
        )
    )
    await storage.upsert_memory_durable_receipt(
        MemoryDurableReceipt(
            receipt_id=f"{task_id}-receipt",
            session_key=SESSION_KEY,
            session_id=session_id,
            turn_id="turn-1",
            scope="checkpoint",
            content_hash="h1",
            idempotency_key=f"checkpoint:{SESSION_KEY}:{task_id}",
            status="checkpoint_saved",
            created_at=_T0,
            updated_at=_T0,
        )
    )


async def test_delete_session_removes_tasks_and_memory_receipts() -> None:
    storage = SessionStorage(":memory:")
    await storage.connect()
    try:
        await _seed(storage, session_id="session-1", task_id="task-1")

        await storage.delete_session(SESSION_KEY)

        assert await storage.count_sessions() == 0
        assert await storage.get_transcript("session-1") == []
        assert await storage.list_agent_tasks(SESSION_KEY) == []
        assert await storage.list_memory_durable_receipts(session_key=SESSION_KEY) == []
    finally:
        await storage.close()


async def test_recreated_session_key_does_not_inherit_deleted_tasks() -> None:
    """Session keys are deterministic, so a new chat reuses the deleted key."""
    storage = SessionStorage(":memory:")
    await storage.connect()
    try:
        await _seed(storage, session_id="session-1", task_id="task-1")
        await storage.delete_session(SESSION_KEY)

        # Same key, brand-new session id — what the next inbound message creates.
        await storage.upsert_session(
            SessionNode(
                session_key=SESSION_KEY,
                session_id="session-2",
                created_at=_T0 + 1,
                updated_at=_T0 + 1,
            )
        )

        assert await storage.list_agent_tasks(SESSION_KEY) == []
        grouped = await storage.list_agent_tasks_for_sessions([SESSION_KEY])
        assert grouped[SESSION_KEY] == []
    finally:
        await storage.close()
