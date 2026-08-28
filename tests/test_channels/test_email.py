from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agentos.channels.email import ChannelEntry, EmailChannel, EmailChannelConfig
from agentos.channels.types import IncomingMessage


def test_email_channel_entry_validation() -> None:
    entry = ChannelEntry(
        imap_server="imap.example.com",
        imap_username="user@example.com",
        imap_password="password",
        smtp_server="smtp.example.com",
        smtp_username="user@example.com",
        smtp_password="password",
        allowed_from_addresses=["allowed@example.com", "@company.com"],
    )
    assert entry.imap_server == "imap.example.com"
    assert entry.allowed_from_addresses == ["allowed@example.com", "@company.com"]


def test_email_access_control_evaluation() -> None:
    config = EmailChannelConfig(
        allowed_from_addresses=["user@example.com", "@company.com", "*@another.com"]
    )
    channel = EmailChannel(config=config)

    # Exact match admitted
    msg1 = IncomingMessage(sender_id="user@example.com", channel_id="email", content="hi")
    decision1 = channel.evaluate_access(msg1, is_group=False, mentioned=False)
    assert decision1.admit is True

    # Domain match admitted
    msg2 = IncomingMessage(sender_id="someone@company.com", channel_id="email", content="hi")
    decision2 = channel.evaluate_access(msg2, is_group=False, mentioned=False)
    assert decision2.admit is True

    # Wildcard domain match admitted
    msg3 = IncomingMessage(sender_id="someone@another.com", channel_id="email", content="hi")
    decision3 = channel.evaluate_access(msg3, is_group=False, mentioned=False)
    assert decision3.admit is True

    # Unknown denied
    msg4 = IncomingMessage(sender_id="unknown@unknown.com", channel_id="email", content="hi")
    decision4 = channel.evaluate_access(msg4, is_group=False, mentioned=False)
    assert decision4.admit is False
    assert decision4.reason == "not_in_allowlist"


def test_email_access_control_open_by_default() -> None:
    config = EmailChannelConfig(allowed_from_addresses=[])
    channel = EmailChannel(config=config)

    # Empty list admits everyone
    msg = IncomingMessage(sender_id="stranger@stranger.com", channel_id="email", content="hi")
    decision = channel.evaluate_access(msg, is_group=False, mentioned=False)
    assert decision.admit is True


def test_email_parsing_new_thread() -> None:
    config = EmailChannelConfig()
    channel = EmailChannel(config=config)

    raw_email_headers = (
        "From: Alice <alice@example.com>\n"
        "To: Agent <agent@example.com>\n"
        "Subject: Project Update\n"
        "Message-ID: <msg-123@example.com>\n"
        "\n"
        "Hello agent! Let's get started."
    )

    import email

    msg = email.message_from_string(raw_email_headers)
    incoming = channel._parse_email_message(msg)

    assert incoming is not None
    assert incoming.sender_id == "alice@example.com"
    assert incoming.content == "Hello agent! Let's get started."
    assert incoming.metadata["subject"] == "Project Update"
    assert incoming.metadata["native_message_id"] == "<msg-123@example.com>"
    assert incoming.metadata["native_thread_id"] == "<msg-123@example.com>"
    assert incoming.metadata["is_group"] is True


def test_email_parsing_reply_thread() -> None:
    config = EmailChannelConfig()
    channel = EmailChannel(config=config)

    raw_email_headers = (
        "From: Alice <alice@example.com>\n"
        "To: Agent <agent@example.com>\n"
        "Subject: Re: Project Update\n"
        "Message-ID: <msg-456@example.com>\n"
        "In-Reply-To: <msg-123@example.com>\n"
        "References: <msg-123@example.com>\n"
        "\n"
        "Any updates?"
    )

    import email

    msg = email.message_from_string(raw_email_headers)
    incoming = channel._parse_email_message(msg)

    assert incoming is not None
    assert incoming.sender_id == "alice@example.com"
    assert incoming.metadata["subject"] == "Re: Project Update"
    assert incoming.metadata["native_message_id"] == "<msg-456@example.com>"
    assert incoming.metadata["native_thread_id"] == "<msg-123@example.com>"


@pytest.mark.asyncio
async def test_email_send_outbound() -> None:
    config = EmailChannelConfig(
        smtp_server="smtp.example.com",
        smtp_username="agent@example.com",
    )
    channel = EmailChannel(config=config)

    inbound = IncomingMessage(
        sender_id="alice@example.com",
        channel_id="email",
        content="Hello",
        metadata={
            "subject": "Project",
            "native_message_id": "<msg-123@example.com>",
            "references": "<msg-abc@example.com>",
            "native_chat_id": "<msg-abc@example.com>",
        },
    )

    reply = channel.build_reply_message("Sure, here is the answer.", inbound)

    with patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp

        await channel.send(reply)

        mock_smtp.sendmail.assert_called_once()
        args = mock_smtp.sendmail.call_args[0]
        assert args[0] == "agent@example.com"
        assert args[1] == ["alice@example.com"]
        raw_msg_str = args[2]
        import email as email_pkg

        parsed_mime = email_pkg.message_from_string(raw_msg_str)
        assert parsed_mime["Subject"] == "Re: Project"
        assert parsed_mime["In-Reply-To"] == "<msg-123@example.com>"
        assert parsed_mime["References"] == "<msg-abc@example.com> <msg-123@example.com>"

        body_part = parsed_mime.get_payload(0)
        assert body_part.get_content_type() == "text/plain"
        body_decoded = body_part.get_payload(decode=True).decode("utf-8")
        assert "Sure, here is the answer." in body_decoded


@pytest.mark.asyncio
async def test_email_send_file(tmp_path) -> None:
    config = EmailChannelConfig(
        smtp_server="smtp.example.com",
        smtp_username="agent@example.com",
    )
    channel = EmailChannel(config=config)

    test_file = tmp_path / "report.txt"
    test_file.write_bytes(b"Monthly report content")

    channel._last_headers["alice@example.com"] = {
        "subject": "Status Report",
        "message_id": "<msg-123@example.com>",
        "references": "<msg-abc@example.com>",
    }

    with patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp

        await channel.send_file("alice@example.com", str(test_file), content="Here is your file.")

        mock_smtp.sendmail.assert_called_once()
        args = mock_smtp.sendmail.call_args[0]
        assert args[0] == "agent@example.com"
        assert args[1] == ["alice@example.com"]
        raw_msg_str = args[2]
        import email as email_pkg

        parsed_mime = email_pkg.message_from_string(raw_msg_str)
        assert parsed_mime["Subject"] == "Re: Status Report"

        body_part = parsed_mime.get_payload(0)
        body_decoded = body_part.get_payload(decode=True).decode("utf-8")
        assert "Here is your file." in body_decoded

        file_part = parsed_mime.get_payload(1)
        assert file_part.get_content_type() == "application/octet-stream"
        assert file_part.get_filename() == "report.txt"
        file_decoded = file_part.get_payload(decode=True)
        assert file_decoded == b"Monthly report content"


def test_email_config_fields_validation() -> None:
    entry = ChannelEntry(
        imap_server="imap.example.com",
        imap_username="user@example.com",
        imap_password="password",
        smtp_server="smtp.example.com",
        smtp_username="user@example.com",
        smtp_password="password",
        smtp_use_ssl=True,
        timeout_s=25.0,
    )
    assert entry.smtp_use_ssl is True
    assert entry.timeout_s == 25.0

    config = EmailChannelConfig(smtp_use_ssl=True, timeout_s=25.0)
    assert config.smtp_use_ssl is True
    assert config.timeout_s == 25.0


@pytest.mark.asyncio
async def test_email_send_outbound_ssl() -> None:
    config = EmailChannelConfig(
        smtp_server="smtp.example.com",
        smtp_username="agent@example.com",
        smtp_use_ssl=True,
        timeout_s=10.0,
    )
    channel = EmailChannel(config=config)

    reply = channel.build_reply_message(
        "Hi",
        IncomingMessage(sender_id="alice@example.com", channel_id="email", content="Hello"),
    )

    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl_class:
        mock_smtp = MagicMock()
        mock_smtp_ssl_class.return_value = mock_smtp

        await channel.send(reply)

        mock_smtp_ssl_class.assert_called_once_with("smtp.example.com", 587, timeout=10.0)
        mock_smtp.sendmail.assert_called_once()


@pytest.mark.asyncio
async def test_email_idle_flow() -> None:
    config = EmailChannelConfig(
        imap_server="imap.example.com",
        imap_username="user@example.com",
        imap_password="password",
        timeout_s=5.0,
    )
    channel = EmailChannel(config=config)
    channel._connected = True

    mock_imap = MagicMock()
    mock_imap.capability.return_value = ("OK", [b"IMAP4rev1 IDLE"])

    mock_imap.readline.side_effect = [
        b"+ idling\r\n",
        b"* 1 EXISTS\r\n",
        b"OK IDLE terminated\r\n",
    ]

    mock_sock = MagicMock()
    mock_imap.socket.return_value = mock_sock

    search_call_count = 0

    def mock_search(criteria, charset=None):
        nonlocal search_call_count
        search_call_count += 1
        if search_call_count == 1:
            return ("OK", [b"1"])
        else:
            channel._connected = False
            return ("OK", [b""])

    mock_imap.search.side_effect = mock_search
    raw_email = b"From: alice@example.com\r\nSubject: Test\r\nMessage-ID: <123>\r\n\r\nHello IDLE"
    mock_imap.fetch.return_value = ("OK", [(None, raw_email)])

    select_call_count = 0

    def mock_select(r, w, x, timeout):
        nonlocal select_call_count
        select_call_count += 1
        if select_call_count == 1:
            return ([mock_sock], [], [])
        else:
            channel._connected = False
            return ([], [], [])

    loop = asyncio.get_running_loop()

    with patch("select.select", side_effect=mock_select):
        await loop.run_in_executor(None, channel._run_idle, mock_imap, loop)

    assert channel._queue.qsize() == 1
    queued_msg = await channel._queue.get()
    assert queued_msg.sender_id == "alice@example.com"
    assert queued_msg.content == "Hello IDLE"


@pytest.mark.asyncio
async def test_email_idle_unsupported_fallback() -> None:
    config = EmailChannelConfig(
        imap_server="imap.example.com",
        imap_username="user@example.com",
        imap_password="password",
        poll_interval_s=1.0,
    )
    channel = EmailChannel(config=config)
    channel._connected = True

    mock_imap = MagicMock()
    mock_imap.capability.return_value = ("OK", [b"IMAP4rev1"])

    mock_imap.search.side_effect = [("OK", [b"1"]), ("OK", [b""])]
    raw_email = (
        b"From: bob@example.com\r\n"
        b"Subject: Test Fallback\r\n"
        b"Message-ID: <456>\r\n"
        b"\r\n"
        b"Hello Fallback"
    )
    mock_imap.fetch.return_value = ("OK", [(None, raw_email)])

    def mock_sleep(seconds):
        channel._connected = False

    loop = asyncio.get_running_loop()
    with patch("time.sleep", side_effect=mock_sleep):
        await loop.run_in_executor(None, channel._run_idle, mock_imap, loop)

    assert channel._queue.qsize() == 1
    queued_msg = await channel._queue.get()
    assert queued_msg.sender_id == "bob@example.com"
    assert queued_msg.content == "Hello Fallback"
