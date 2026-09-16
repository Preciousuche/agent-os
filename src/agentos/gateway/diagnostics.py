"""Runtime diagnostics switch state for the gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from threading import RLock
from typing import Any

from agentos.observability.turn_call_log import (
    TURN_CALL_LOG_ENABLED_VALUES,
    TURN_CALL_LOG_ENV,
)
from agentos.util.bounded_registry import registry_stats


def env_forces_raw_turn_call() -> bool:
    """Return True when the raw turn-call env override is explicitly truthy."""

    return os.environ.get(TURN_CALL_LOG_ENV, "").strip().lower() in TURN_CALL_LOG_ENABLED_VALUES


@dataclass(frozen=True)
class DiagnosticsSnapshot:
    configured_enabled: bool
    runtime_enabled: bool | None
    runtime_raw: bool
    effective_enabled: bool
    detail: str
    raw_enabled: bool
    raw_source: str
    env_override: bool
    warning: str | None = None


class DiagnosticsState:
    """Gateway-lifetime, non-persistent diagnostics mode state."""

    def __init__(self, *, configured_enabled: bool = False) -> None:
        self._configured_enabled = bool(configured_enabled)
        self._runtime_enabled: bool | None = None
        self._runtime_raw = False
        self._lock = RLock()

    @classmethod
    def from_config(cls, config: Any | None) -> DiagnosticsState:
        return cls(
            configured_enabled=bool(getattr(config, "diagnostics_enabled", False))
            if config is not None
            else False
        )

    def set_runtime(self, *, enabled: bool, raw: bool = False) -> DiagnosticsSnapshot:
        with self._lock:
            self._runtime_enabled = bool(enabled)
            self._runtime_raw = bool(enabled and raw)
            return self.snapshot()

    def raw_turn_call_enabled(self) -> bool:
        return self.snapshot().raw_enabled

    def raw_turn_call_source(self) -> str:
        return self.snapshot().raw_source

    def snapshot(self) -> DiagnosticsSnapshot:
        with self._lock:
            effective_enabled = (
                self._configured_enabled if self._runtime_enabled is None else self._runtime_enabled
            )
            runtime_raw = bool(effective_enabled and self._runtime_raw)
            env_override = env_forces_raw_turn_call()
            if env_override:
                raw_source = "env"
            elif runtime_raw:
                raw_source = "runtime"
            else:
                raw_source = "off"
            raw_enabled = raw_source != "off"
            detail = "raw" if runtime_raw else "standard" if effective_enabled else "off"
            warning = (
                f"{TURN_CALL_LOG_ENV} still forces raw capture"
                if env_override and not runtime_raw
                else None
            )
            return DiagnosticsSnapshot(
                configured_enabled=self._configured_enabled,
                runtime_enabled=self._runtime_enabled,
                runtime_raw=self._runtime_raw,
                effective_enabled=effective_enabled,
                detail=detail,
                raw_enabled=raw_enabled,
                raw_source=raw_source,
                env_override=env_override,
                warning=warning,
            )


def registry_snapshot() -> dict[str, Any]:
    """Live bounded-registry sizes, shaped for an operator-facing payload.

    ``BoundedRegistry`` has always collected this, and ``registry_stats()`` has
    always exposed it, but nothing read it — so the only way to notice a
    registry growing was to read the source. That is how every instance of the
    unbounded-container defect has been found so far (#1084, #1098, #1131,
    #2399, #2445), none of them from a running deployment.

    ``atCeiling`` is the useful signal rather than raw size: a registry sitting
    at its ceiling with a rising ``evictions`` count is losing state it will
    have to rebuild, which is the difference between "sized fine" and
    "thrashing".

    The underlying table is weakly held, so a registry owned by a torn-down
    object drops out. That is deliberate — the table that exists to stop leaks
    must not become one — but it means a missing row means "not live now", not
    "zero", and the payload says so rather than letting a reader assume.
    """
    rows = sorted(registry_stats(), key=lambda row: str(row.get("name", "")))
    at_ceiling = [
        str(row.get("name", ""))
        for row in rows
        if int(row.get("maxEntries") or 0)
        and int(row.get("entries") or 0) >= int(row["maxEntries"])
    ]
    return {
        "registries": rows,
        "summary": {
            "count": len(rows),
            "entries": sum(int(row.get("entries") or 0) for row in rows),
            "evictions": sum(int(row.get("evictions") or 0) for row in rows),
            "expirations": sum(int(row.get("expirations") or 0) for row in rows),
            "atCeiling": at_ceiling,
        },
        "note": (
            "Live registries only. A registry owned by a torn-down object is "
            "dropped from this table, so an absent name means 'not live now', "
            "not 'zero'."
        ),
    }


def diagnostics_status_payload(
    state: DiagnosticsState | None,
    config: Any | None,
) -> dict[str, Any]:
    """Build a stable RPC/status payload for the current diagnostics state."""

    resolved_state = state or DiagnosticsState.from_config(config)
    snapshot = resolved_state.snapshot()
    payload: dict[str, Any] = {
        "enabled": snapshot.effective_enabled,
        "detail": snapshot.detail,
        "configured": {
            "diagnostics_enabled": snapshot.configured_enabled,
        },
        "runtime": {
            "enabled": snapshot.runtime_enabled,
            "raw": snapshot.runtime_raw,
        },
        "raw_turn_call": {
            "enabled": snapshot.raw_enabled,
            "source": snapshot.raw_source,
            "env_override": snapshot.env_override,
        },
        "registries": registry_snapshot(),
        "applies_to": "next_turn",
        "server_debug_changed": False,
        "auth_scope_changed": False,
    }
    if snapshot.warning:
        payload["warning"] = snapshot.warning
    return payload
