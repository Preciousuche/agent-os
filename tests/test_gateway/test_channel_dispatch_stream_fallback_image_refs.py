"""Issue #2940: the batch-fallback reply after a streaming turn left a stale
``![name](name)`` reference for an artifact the stream relay had already
delivered as a native file.

``_deliver_runtime_channel_reply`` dropped the stream-delivered artifacts from
its list *before* ``_strip_delivered_artifact_image_references`` ran, so their
names were exactly the ones missing from the strip set. The text is now
stripped against every artifact it names; the filter still decides what gets
(re-)delivered as a file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentos.artifacts import ArtifactStore
from agentos.channels.types import IncomingMessage, OutgoingMessage
from agentos.engine.types import ArtifactEvent
from agentos.gateway.channel_dispatch import (
    _deliver_runtime_channel_reply,
    _RuntimeChannelStreamRelay,
)

SESSION_KEY = "agent:main:discord:direct:u1"


class _StreamingFileChannel:
    """Streams text and uploads files natively, like Discord or Telegram."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        self.chunks: list[str] = []
        self.files: list[tuple[str, str]] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)

    async def send_streaming(self, chunks: Any, **_kwargs: Any) -> None:
        async for chunk in chunks:
            self.chunks.append(chunk)

    async def send_file(self, chat_id: str, file_path: str) -> None:
        assert Path(file_path).is_file()
        self.files.append((chat_id, Path(file_path).name))


class _FakeTaskRuntime:
    async def enqueue(self, envelope: Any, message: str, *, stream_event_sink: Any = None) -> None:
        return None

    async def wait(self, task_id: str) -> Any:
        return SimpleNamespace(status="succeeded")


class _Transcript:
    def __init__(self, text: str, artifacts: list[dict[str, Any]]) -> None:
        self._text = text
        self._artifacts = artifacts

    async def read_transcript(self, key: str) -> list[dict[str, Any]]:
        return [
            {"role": "user", "content": "draw chart"},
            {
                "role": "assistant",
                "content": json.dumps({"text": self._text, "artifacts": self._artifacts}),
            },
        ]


def _publish(store: ArtifactStore, name: str) -> Any:
    return store.publish_bytes(
        b"\x89PNG\r\n\x1a\n" + name.encode(),
        session_id="session-1",
        session_key=SESSION_KEY,
        name=name,
        mime="image/png",
        source="publish_artifact",
    )


def _message() -> IncomingMessage:
    return IncomingMessage(sender_id="u1", channel_id="c1", content="draw chart")


async def _deliver(
    channel: Any,
    transcript: _Transcript,
    config: Any,
    *,
    relay: Any,
) -> None:
    await _deliver_runtime_channel_reply(
        channel=channel,
        task_runtime=_FakeTaskRuntime(),
        session_manager=transcript,
        session_key=SESSION_KEY,
        task_id="task-1",
        route_envelope=SimpleNamespace(reply_target=None),
        inbound=_message(),
        transcript_watermark=1,
        config=config,
        stream_relay=relay,
    )


def _texts(channel: Any) -> list[str]:
    return [message.content for message in channel.sent]


@pytest.fixture
def config(tmp_path: Path) -> Any:
    return SimpleNamespace(attachments=SimpleNamespace(media_root=str(tmp_path)))


# ── the report ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_stream_delivered_artifact_leaves_no_image_reference_behind(
    tmp_path: Path, config: Any
) -> None:
    store = ArtifactStore(tmp_path)
    chart = _publish(store, "chart.png")
    channel = _StreamingFileChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(channel, _message(), _FakeTaskRuntime(), config)
    assert relay is not None
    await relay.emit(ArtifactEvent(**chart.to_dict()))

    await _deliver(
        channel,
        _Transcript("Here is your chart:\n\n![chart](chart.png)", [chart.to_dict()]),
        config,
        relay=relay,
    )

    assert channel.files == [("c1", "chart.png")], "delivered once, by the stream"
    assert _texts(channel) == ["Here is your chart:"]
    assert all("![chart](chart.png)" not in text for text in _texts(channel))


@pytest.mark.asyncio
async def test_both_delivered_and_pending_references_are_stripped(
    tmp_path: Path, config: Any
) -> None:
    """One artifact went out over the stream, one did not: both references
    are stale in the fallback text, and only the pending one is sent here."""
    store = ArtifactStore(tmp_path)
    chart = _publish(store, "chart.png")
    table = _publish(store, "table.png")
    channel = _StreamingFileChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(channel, _message(), _FakeTaskRuntime(), config)
    assert relay is not None
    await relay.emit(ArtifactEvent(**chart.to_dict()))

    await _deliver(
        channel,
        _Transcript(
            "Chart:\n\n![chart](chart.png)\n\nTable:\n\n![table](table.png)",
            [chart.to_dict(), table.to_dict()],
        ),
        config,
        relay=relay,
    )

    assert channel.files == [("c1", "chart.png"), ("c1", "table.png")]
    assert _texts(channel) == ["Chart:\n\nTable:"]


@pytest.mark.asyncio
async def test_an_image_reference_to_something_that_is_not_an_artifact_stays(
    tmp_path: Path, config: Any
) -> None:
    """Only references to the turn's own artifacts are stale; a link to an
    external image is content."""
    store = ArtifactStore(tmp_path)
    chart = _publish(store, "chart.png")
    channel = _StreamingFileChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(channel, _message(), _FakeTaskRuntime(), config)
    assert relay is not None
    await relay.emit(ArtifactEvent(**chart.to_dict()))

    await _deliver(
        channel,
        _Transcript(
            "![chart](chart.png)\n\nSee also ![logo](https://x.test/logo.png)",
            [chart.to_dict()],
        ),
        config,
        relay=relay,
    )

    assert _texts(channel) == ["See also ![logo](https://x.test/logo.png)"]


# ── what must not change ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_without_a_relay_the_batch_path_is_unchanged(tmp_path: Path, config: Any) -> None:
    store = ArtifactStore(tmp_path)
    chart = _publish(store, "chart.png")
    channel = _StreamingFileChannel()

    await _deliver(
        channel,
        _Transcript("Here is your chart:\n\n![chart](chart.png)", [chart.to_dict()]),
        config,
        relay=None,
    )

    assert channel.files == [("c1", "chart.png")]
    assert _texts(channel) == ["Here is your chart:"]


@pytest.mark.asyncio
async def test_an_artifact_the_stream_delivered_is_not_delivered_again(
    tmp_path: Path, config: Any
) -> None:
    """The filter's own job — pinned beside the fix that moved past it."""
    store = ArtifactStore(tmp_path)
    chart = _publish(store, "chart.png")
    channel = _StreamingFileChannel()
    relay = _RuntimeChannelStreamRelay.maybe_start(channel, _message(), _FakeTaskRuntime(), config)
    assert relay is not None
    await relay.emit(ArtifactEvent(**chart.to_dict()))

    await _deliver(channel, _Transcript("", [chart.to_dict()]), config, relay=relay)

    assert channel.files == [("c1", "chart.png")]
    assert channel.sent == []
