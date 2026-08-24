from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agentos.channels.types import OutgoingMessage
from agentos.scheduler.delivery import DeliveryChain, _is_transient_delivery_error


def test_is_transient_delivery_error() -> None:
    # Timeout
    assert _is_transient_delivery_error(TimeoutError()) is True
    assert _is_transient_delivery_error(httpx.TimeoutException("timeout")) is True

    # NetworkError
    assert _is_transient_delivery_error(httpx.NetworkError("network error")) is True

    # HTTPStatusError - transient
    resp_503 = httpx.Response(503, request=httpx.Request("POST", "https://example.com"))
    err_503 = httpx.HTTPStatusError("503", request=resp_503.request, response=resp_503)
    assert _is_transient_delivery_error(err_503) is True

    resp_429 = httpx.Response(429, request=httpx.Request("POST", "https://example.com"))
    err_429 = httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429)
    assert _is_transient_delivery_error(err_429) is True

    # HTTPStatusError - permanent
    resp_403 = httpx.Response(403, request=httpx.Request("POST", "https://example.com"))
    err_403 = httpx.HTTPStatusError("403", request=resp_403.request, response=resp_403)
    assert _is_transient_delivery_error(err_403) is False

    # Text based pattern
    assert _is_transient_delivery_error(Exception("Rate limit exceeded")) is True
    assert _is_transient_delivery_error(Exception("Connection reset by peer econnreset")) is True
    assert _is_transient_delivery_error(Exception("Unauthorized access")) is False


class _FakeAdapter:
    def __init__(self) -> None:
        self.call_count = 0
        self.raise_transient = True

    async def send(self, message: OutgoingMessage) -> None:
        self.call_count += 1
        if self.raise_transient and self.call_count == 1:
            raise httpx.NetworkError("temporary connection failure")


class _FakeChannelManager:
    def __init__(self, adapter: _FakeAdapter | None) -> None:
        self.adapter = adapter

    def get(self, name: str) -> _FakeAdapter | None:
        return self.adapter


@pytest.mark.asyncio
async def test_post_to_webhook_retry_success() -> None:
    chain = DeliveryChain(channel_manager_ref=lambda: None)

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        req = httpx.Request("POST", "https://hooks.example.com")
        if call_count == 1:
            resp_503 = httpx.Response(503, request=req)
            raise httpx.HTTPStatusError("503", request=req, response=resp_503)
        return httpx.Response(200, request=req)

    # Use patch to mock httpx.AsyncClient.post with a custom async function
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_client_post:
        mock_client_post.side_effect = mock_post
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            res = await chain._post_to_webhook(
                job_id="job-1",
                job_name="test-job",
                text="hello",
                url="https://hooks.example.com",
                token="",
            )
            assert res == "delivered"
            assert call_count == 2
            mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_post_to_webhook_permanent_failure_no_retry() -> None:
    chain = DeliveryChain(channel_manager_ref=lambda: None)

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        req = httpx.Request("POST", "https://hooks.example.com")
        resp_403 = httpx.Response(403, request=req)
        raise httpx.HTTPStatusError("403", request=req, response=resp_403)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_client_post:
        mock_client_post.side_effect = mock_post
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            res = await chain._post_to_webhook(
                job_id="job-1",
                job_name="test-job",
                text="hello",
                url="https://hooks.example.com",
                token="",
            )
            assert res == "delivery_failed"
            assert res.detail == "403"
            assert call_count == 1
            mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_post_to_channel_retry_success() -> None:
    adapter = _FakeAdapter()
    manager = _FakeChannelManager(adapter)
    chain = DeliveryChain(channel_manager_ref=lambda: manager)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await chain._post_to_channel(
            job_id="job-1",
            text="hello",
            channel_name="slack",
            channel_id="C123",
            thread_id="",
        )
        assert res == "delivered"
        assert adapter.call_count == 2
        mock_sleep.assert_called_once_with(1.0)
