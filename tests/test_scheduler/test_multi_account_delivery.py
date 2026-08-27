from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agentos.channels.manager import ChannelManager
from agentos.channels.types import OutgoingMessage
from agentos.scheduler.delivery import DeliveryChain
from agentos.scheduler.payloads import make_script_payload
from agentos.scheduler.types import (
    CronJob,
    DeliveryConfig,
    DeliveryMode,
    FailureDestination,
    SessionTarget,
)


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self.name = name
        self.messages: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_cron_delivery_resolves_and_honors_account_id() -> None:
    # Setup two Slack adapters
    adapter1 = _FakeAdapter("slack-bot-1")
    adapter2 = _FakeAdapter("slack-bot-2")
    channels = {"slack-bot-1": adapter1, "slack-bot-2": adapter2}
    channel_types = {"slack-bot-1": "slack", "slack-bot-2": "slack"}

    # Use a real ChannelManager configured with two adapters of the same type
    manager = ChannelManager(
        _channels=channels,  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types=channel_types,
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    job = CronJob(
        id="job-1",
        name="multi-acc-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            account_id="slack-bot-1",
        ),
    )

    report = await chain.deliver(
        job,
        result_text="hello world",
        success=True,
        summary="hello world",
        session_key="cron:job-1:run:deadbeef",
    )

    assert report.channel_status == "delivered"
    # Ensure message went to adapter 1 and not adapter 2
    assert len(adapter1.messages) == 1
    assert adapter1.messages[0].content == "hello world"
    assert len(adapter2.messages) == 0


@pytest.mark.asyncio
async def test_cron_delivery_resolution_failure_reports_failed() -> None:
    # Setup one Slack adapter
    adapter = _FakeAdapter("slack-bot-1")
    channels = {"slack-bot-1": adapter}
    channel_types = {"slack-bot-1": "slack"}

    # Use a real ChannelManager
    manager = ChannelManager(
        _channels=channels,  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types=channel_types,
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    # Use a non-existent account_id
    job = CronJob(
        id="job-1",
        name="multi-acc-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            account_id="slack-bot-nonexistent",
        ),
    )

    report = await chain.deliver(
        job,
        result_text="hello world",
        success=True,
        summary="hello world",
        session_key="cron:job-1:run:deadbeef",
    )

    assert report.channel_status == "delivery_failed"
    assert "delivery target resolution failed: unsupported_account" in report.channel_detail


@pytest.mark.asyncio
async def test_reply_target_account_id_override_and_empty_target_account_no_reuse() -> None:
    # Setup two Slack adapters
    adapter1 = _FakeAdapter("slack-bot-1")
    adapter2 = _FakeAdapter("slack-bot-2")
    channels = {"slack-bot-1": adapter1, "slack-bot-2": adapter2}
    channel_types = {"slack-bot-1": "slack", "slack-bot-2": "slack"}

    manager = ChannelManager(
        _channels=channels,  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types=channel_types,
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    job = CronJob(
        id="job-1",
        name="multi-acc-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            account_id="slack-bot-1",
        ),
    )

    # 1. ReplyTarget overrides the job account
    reply_target_override = SimpleNamespace(
        kind="channel",
        channel_name="slack",
        to="C0123ABCDEF",
        thread_id="",
        account_id="slack-bot-2",
    )
    envelope_override = SimpleNamespace(reply_target=reply_target_override)

    report_override = await chain.deliver(
        job,
        result_text="hello override",
        success=True,
        summary="hello override",
        session_key="cron:job-1:run:deadbeef",
        route_envelope=envelope_override,
    )
    assert report_override.channel_status == "delivered"
    assert len(adapter2.messages) == 1
    assert adapter2.messages[0].content == "hello override"
    assert len(adapter1.messages) == 0

    # 2. Empty target account does NOT fall back to job's stale account,
    # leading to ambiguous failure
    reply_target_empty = SimpleNamespace(
        kind="channel",
        channel_name="slack",
        to="C0123ABCDEF",
        thread_id="",
        account_id="",
    )
    envelope_empty = SimpleNamespace(reply_target=reply_target_empty)

    report_empty = await chain.deliver(
        job,
        result_text="hello empty",
        success=True,
        summary="hello empty",
        session_key="cron:job-1:run:deadbeef",
        route_envelope=envelope_empty,
    )
    assert report_empty.channel_status == "delivery_failed"
    assert "delivery target resolution failed: ambiguous_account" in report_empty.channel_detail


@pytest.mark.asyncio
async def test_failure_destination_account_id_routing() -> None:
    # Setup two Telegram adapters
    adapter1 = _FakeAdapter("telegram-bot-1")
    adapter2 = _FakeAdapter("telegram-bot-2")
    channels = {"telegram-bot-1": adapter1, "telegram-bot-2": adapter2}
    channel_types = {"telegram-bot-1": "telegram", "telegram-bot-2": "telegram"}

    manager = ChannelManager(
        _channels=channels,  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types=channel_types,
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    fd = FailureDestination(
        mode=DeliveryMode.CHANNEL,
        channel_name="telegram",
        channel_id="T0123456",
        account_id="telegram-bot-2",
    )
    job = CronJob(
        id="job-1",
        name="failure-dest-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.NONE,
            failure_destination=fd,
        ),
    )

    status = await chain.dispatch_failure_alert(job, "job execution failed")
    assert status == "delivered"
    assert len(adapter2.messages) == 1
    assert adapter2.messages[0].content == "job execution failed"
    assert len(adapter1.messages) == 0


@pytest.mark.asyncio
async def test_no_account_unique_and_ambiguous_resolution() -> None:
    # 1. Unique resolution when only 1 adapter exists for the type
    adapter_slack = _FakeAdapter("slack-bot-1")
    manager = ChannelManager(
        _channels={"slack-bot-1": adapter_slack},  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types={"slack-bot-1": "slack"},
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    job = CronJob(
        id="job-1",
        name="unique-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            account_id="",  # No account_id provided
        ),
    )

    report = await chain.deliver(
        job, "hello unique", True, "hello unique", "cron:job-1:run:deadbeef"
    )
    assert report.channel_status == "delivered"
    assert len(adapter_slack.messages) == 1

    # 2. Ambiguous resolution when multiple adapters exist for the type
    # and no account_id is specified
    adapter_slack2 = _FakeAdapter("slack-bot-2")
    manager_ambiguous = ChannelManager(
        _channels={"slack-bot-1": adapter_slack, "slack-bot-2": adapter_slack2},  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types={"slack-bot-1": "slack", "slack-bot-2": "slack"},
    )
    chain_ambiguous = DeliveryChain(channel_manager_ref=lambda: manager_ambiguous)

    report_ambiguous = await chain_ambiguous.deliver(
        job, "hello ambiguous", True, "hello ambiguous", "cron:job-1:run:deadbeef"
    )
    assert report_ambiguous.channel_status == "delivery_failed"
    assert "delivery target resolution failed: ambiguous_account" in report_ambiguous.channel_detail


@pytest.mark.asyncio
async def test_slack_resolved_thread_metadata() -> None:
    adapter = _FakeAdapter("slack-bot-1")
    manager = ChannelManager(
        _channels={"slack-bot-1": adapter},  # type: ignore
        _turn_runner=None,
        _session_manager=None,
        _channel_types={"slack-bot-1": "slack"},
    )
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    job = CronJob(
        id="job-1",
        name="thread-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
            thread_id="thread-456",
        ),
    )

    report = await chain.deliver(
        job, "hello thread", True, "hello thread", "cron:job-1:run:deadbeef"
    )
    assert report.channel_status == "delivered"
    assert len(adapter.messages) == 1
    msg = adapter.messages[0]
    assert msg.content == "hello thread"
    assert msg.reply_to == "thread-456"
    assert msg.metadata == {"channel": "C0123ABCDEF"}


@pytest.mark.asyncio
async def test_compatibility_fallback_for_managers_without_resolve_delivery_target() -> None:
    class LegacyManager:
        def __init__(self, channels: dict[str, Any]) -> None:
            self._channels = channels

        def get(self, name: str) -> Any:
            return self._channels.get(name)

    adapter = _FakeAdapter("slack")
    legacy_manager = LegacyManager({"slack": adapter})
    chain = DeliveryChain(channel_manager_ref=lambda: legacy_manager)  # type: ignore

    job = CronJob(
        id="job-1",
        name="legacy-test",
        handler_key="script_run",
        payload=make_script_payload("test.sh"),
        session_target=SessionTarget.ISOLATED,
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C0123ABCDEF",
        ),
    )

    report = await chain.deliver(
        job, "hello legacy", True, "hello legacy", "cron:job-1:run:deadbeef"
    )
    assert report.channel_status == "delivered"
    assert len(adapter.messages) == 1
    assert adapter.messages[0].content == "hello legacy"
