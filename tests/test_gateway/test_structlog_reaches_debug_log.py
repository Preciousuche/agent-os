"""structlog events belong in debug.log too.

Half of this codebase logs through ``logging.getLogger`` (scheduler jobs, the
reaper) and half through ``structlog`` (delivery, handlers, channels). Only the
first half reached ``~/.agentos/logs/debug.log``, so a cron run could fail with
"delivery failed" in the file while the reason — a structlog warning carrying
Telegram's "chat not found" — existed nowhere but the terminal the gateway
happened to be started in.
"""

from __future__ import annotations

import logging

import structlog

from agentos.gateway.boot import _remove_structlog_tee, _setup_file_logging
from agentos.gateway.config import GatewayConfig


def _remove_debug_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_agentos_debug_file_handler", False):
            root.removeHandler(handler)
            handler.close()


def _enable_file_logging(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTOS_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTOS_LOG_LEVEL", "DEBUG")
    # structlog's own level filter is process-global and another test may have
    # raised it; pin it here so this file tests the tee, not the ambient config.
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    _setup_file_logging(GatewayConfig(log_level="DEBUG"))


def test_a_structlog_warning_lands_in_the_debug_log(tmp_path, monkeypatch) -> None:
    _remove_structlog_tee()
    original = structlog.get_config()
    try:
        _enable_file_logging(tmp_path, monkeypatch)

        structlog.get_logger("agentos.scheduler.delivery").warning(
            "delivery.channel_failed",
            job_id="job-1",
            error="Bad Request: chat not found",
        )

        contents = (tmp_path / "debug.log").read_text()
        assert "delivery.channel_failed" in contents
        assert "chat not found" in contents
        assert "job-1" in contents
    finally:
        _remove_debug_handlers()
        structlog.configure(**original)


def test_the_level_is_preserved_so_filters_still_work(tmp_path, monkeypatch) -> None:
    _remove_structlog_tee()
    original = structlog.get_config()
    try:
        _enable_file_logging(tmp_path, monkeypatch)

        structlog.get_logger("agentos.test").warning("something.wrong")
        structlog.get_logger("agentos.test").info("something.fine")

        contents = (tmp_path / "debug.log").read_text()
        assert "[WARNING]" in contents.split("something.wrong")[0].splitlines()[-1]
        assert "[INFO]" in contents.split("something.fine")[0].splitlines()[-1]
    finally:
        _remove_debug_handlers()
        structlog.configure(**original)


def test_turning_file_logging_off_restores_the_previous_structlog_config(
    tmp_path, monkeypatch
) -> None:
    _remove_structlog_tee()
    original = structlog.get_config()
    try:
        _enable_file_logging(tmp_path, monkeypatch)
        _setup_file_logging(GatewayConfig(log_file_enabled=False))

        assert structlog.get_config()["processors"] == original["processors"]
    finally:
        _remove_debug_handlers()
        structlog.configure(**original)
