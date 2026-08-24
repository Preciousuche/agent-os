from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from agentos.gateway.config import AuthConfig, GatewayConfig
from agentos.gateway.middleware import AuthMiddleware


def test_invalid_auth_mode_raises_validation_error() -> None:
    # Reject unknown/unimplemented modes at config validation time
    with pytest.raises(ValidationError) as excinfo:
        AuthConfig(mode="password")
    assert "Unsupported or unimplemented auth.mode" in str(excinfo.value)

    with pytest.raises(ValidationError) as excinfo:
        AuthConfig(mode="tokn")  # typo
    assert "Unsupported or unimplemented auth.mode" in str(excinfo.value)


@pytest.mark.asyncio
async def test_auth_middleware_fails_closed_for_unimplemented_mode() -> None:
    # Build a config that has an bypassed or unimplemented mode
    # Since Pydantic prevents direct validation bypass at init, we can test middleware
    # dispatch directly using a mock request.
    from starlette.types import Scope

    async def dummy_app(scope: Scope, receive: Any, send: Any) -> None:
        pass

    config = GatewayConfig()
    # Bypass validation by mutating the private model fields or using model_construct
    config.auth = AuthConfig.model_construct(mode="password")

    middleware = AuthMiddleware(dummy_app, config=config)

    # Mock request targeting a non-public route
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/sessions",
        "headers": [],
    }
    request = Request(scope)

    async def mock_call_next(req: Request) -> Response:
        return Response("OK")

    response = await middleware.dispatch(request, mock_call_next)
    assert response.status_code == 401


def test_password_auth_mode_migration(tmp_path) -> None:
    # A legacy config carrying mode="password" and password="foo" should migrate to token mode
    config_file = tmp_path / "agentos.toml"
    config_file.write_text(
        '[auth]\nmode = "password"\npassword = "hunter2"\n',
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match="auth.mode = 'password' is no longer supported"):
        cfg = GatewayConfig.load(config_file)

    assert cfg.auth.mode == "token"
    # Ensure that it rewrote the file on disk (mode="token" and password popped)
    import tomllib

    with open(config_file, "rb") as f:
        migrated_data = tomllib.load(f)
    assert migrated_data["auth"]["mode"] == "token"
    assert "password" not in migrated_data["auth"]

    # Ensure a backup was created
    backups = [p for p in tmp_path.iterdir() if "backup" in p.name]
    assert len(backups) == 1
    with open(backups[0], "rb") as f:
        backup_data = tomllib.load(f)
    assert backup_data["auth"]["mode"] == "password"
    assert backup_data["auth"]["password"] == "hunter2"
