"""Issue #3290: a Chainlink feed-directory outage dropped the whole reading.

``_resolve_target`` fetched ``FEEDS_URL`` unguarded, so DNS, a timeout, a
5xx or a non-JSON body propagated out of ``main`` as ``{"query", "error"}``
and the caller lost the on-chain reading the RPC had already answered --
address, ``uiMultiplier()``, supply, holder balance. The note written for
this case, "could not fetch the Chainlink feed directory", was reachable only
when the fetch *succeeded* with a non-list body.

The directory is an optional price source, so its fetch now goes through
``_try`` like every other optional read and lands in ``readErrors`` under
``feedDirectory``. The token list is not optional and still aborts.
"""

from __future__ import annotations

import email.message
import importlib.util
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/agentos/skills/bundled/robinhood-chain-stocks/scripts/chain_stocks.py"

_spec = importlib.util.spec_from_file_location("chain_stocks_feed_outage", SCRIPT)
assert _spec is not None and _spec.loader is not None
chain_stocks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chain_stocks)

AAPL = "0x1111111111111111111111111111111111111111"
HOLDER = "0x2222222222222222222222222222222222222222"
TOKEN_LIST = {
    "tokens": [
        {"address": AAPL, "symbol": "AAPL", "name": "Apple • Robinhood Token", "decimals": 18}
    ]
}
FEED_NOTE = "could not fetch the Chainlink feed directory; price unavailable, not disproven"


def _word(value: int) -> str:
    return f"{value & ((1 << 256) - 1):064x}"


def _rpc_answer(payload: dict[str, Any]) -> str:
    """A healthy Stock Token: uiMultiplier 1e18, supply 1000, 18 decimals, AAPL."""
    selector = payload["params"][0]["data"][:10]
    if selector == chain_stocks.SEL_UI_MULTIPLIER:
        return "0x" + _word(10**18)
    if selector == chain_stocks.SEL_TOTAL_SUPPLY:
        return "0x" + _word(1000 * 10**18)
    if selector == chain_stocks.SEL_DECIMALS:
        return "0x" + _word(18)
    if selector == chain_stocks.SEL_SYMBOL:
        return "0x" + _word(32) + _word(4) + b"AAPL".hex().ljust(64, "0")
    if selector == chain_stocks.SEL_BALANCE_OF:
        return "0x" + _word(5 * 10**18)
    return "0x" + _word(0)


def _stub_http(monkeypatch: pytest.MonkeyPatch, feeds: Any) -> None:
    """Token list and RPC answer normally; *feeds* is returned, or raised."""

    def fake_http_json(url: str, timeout: float, payload: dict[str, Any] | None = None) -> Any:
        if url == chain_stocks.FEEDS_URL:
            if isinstance(feeds, BaseException):
                raise feeds
            return feeds
        if url == chain_stocks.TOKEN_LIST_URL:
            return TOKEN_LIST
        assert payload is not None
        return {"jsonrpc": "2.0", "id": 1, "result": _rpc_answer(payload)}

    monkeypatch.setattr(chain_stocks, "_http_json", fake_http_json)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    assert chain_stocks.main([*argv, "--no-cards"]) == 0
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return out


OUTAGES = [
    pytest.param(urllib.error.URLError("directory unreachable (connection refused)"), id="dns"),
    pytest.param(TimeoutError("timed out"), id="timeout"),
    pytest.param(
        urllib.error.HTTPError(
            chain_stocks.FEEDS_URL, 503, "Service Unavailable", email.message.Message(), None
        ),
        id="5xx",
    ),
    pytest.param(ValueError("Expecting value: line 1 column 1 (char 0)"), id="non_json_body"),
    pytest.param(OSError("network is unreachable"), id="os_error"),
]


# ── the report ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("outage", OUTAGES)
def test_a_feed_directory_outage_keeps_the_reading(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], outage: BaseException
) -> None:
    _stub_http(monkeypatch, outage)

    out = _run(capsys, "--query", "Apple")

    assert "error" not in out, out
    token = out["token"]
    assert token["address"] == AAPL
    assert token["onchainSymbol"] == "AAPL"
    assert token["isStockToken"] is True
    assert token["totalSupply"] == str(1000 * 10**18)
    assert "price" not in token


@pytest.mark.parametrize("outage", OUTAGES)
def test_the_outage_is_recorded_and_the_note_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], outage: BaseException
) -> None:
    """The note existed for exactly this failure but was unreachable from it."""
    _stub_http(monkeypatch, outage)

    token = _run(capsys, "--query", "Apple")["token"]

    assert token["readErrors"]["feedDirectory"] == str(outage)
    assert FEED_NOTE in token["notes"]
    assert not any("no Chainlink feed published" in note for note in token["notes"])


def test_the_outage_shape_equals_the_non_list_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The issue's expectation: an unreachable directory degrades to exactly
    the shape a non-list body already produced, plus the recorded reason."""
    _stub_http(monkeypatch, {"unexpected": "shape"})
    non_list = _run(capsys, "--query", "Apple")["token"]

    _stub_http(monkeypatch, urllib.error.URLError("down"))
    outage = _run(capsys, "--query", "Apple")["token"]

    assert outage.pop("readErrors") == {"feedDirectory": "<urlopen error down>"}
    assert "readErrors" not in non_list
    assert outage == non_list


def test_the_outage_shape_equals_no_price_plus_the_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--no-price`` never fetches the directory; the reading it produces is
    what the outage must not lose."""
    _stub_http(monkeypatch, urllib.error.URLError("down"))
    no_price = _run(capsys, "--query", "Apple", "--no-price")["token"]
    outage = _run(capsys, "--query", "Apple")["token"]

    outage.pop("readErrors")
    assert outage.pop("notes") == [FEED_NOTE]
    assert "notes" not in no_price
    assert outage == no_price


# ── the other paths through _resolve_target ────────────────────────────────


def test_an_address_only_run_survives_the_outage_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_http(monkeypatch, urllib.error.URLError("down"))

    token = _run(capsys, "--address", AAPL)["token"]

    assert token["isStockToken"] is True
    assert token["readErrors"] == {"feedDirectory": "<urlopen error down>"}
    assert FEED_NOTE in token["notes"]


def test_the_holder_balance_is_still_read_during_the_outage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_http(monkeypatch, urllib.error.URLError("down"))

    token = _run(capsys, "--query", "Apple", "--holder", HOLDER)["token"]

    assert token["holding"]["balance"] == str(5 * 10**18)
    assert "valueUsd" not in token["holding"], "no price, so no valuation"


def test_the_outage_does_not_hide_an_rpc_read_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both dicts of read errors are reported; merging must not drop either."""

    def fake_http_json(url: str, timeout: float, payload: dict[str, Any] | None = None) -> Any:
        if url == chain_stocks.FEEDS_URL:
            raise urllib.error.URLError("down")
        if url == chain_stocks.TOKEN_LIST_URL:
            return TOKEN_LIST
        assert payload is not None
        if payload["params"][0]["data"][:10] == chain_stocks.SEL_TOTAL_SUPPLY:
            raise chain_stocks.RpcError("execution reverted")
        return {"jsonrpc": "2.0", "id": 1, "result": _rpc_answer(payload)}

    monkeypatch.setattr(chain_stocks, "_http_json", fake_http_json)

    token = _run(capsys, "--query", "Apple")["token"]

    assert set(token["readErrors"]) == {"feedDirectory", "totalSupply"}


def test_a_token_list_outage_still_aborts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The list is not optional: without it there is no address to read."""

    def fake_http_json(url: str, timeout: float, payload: dict[str, Any] | None = None) -> Any:
        if url == chain_stocks.TOKEN_LIST_URL:
            raise urllib.error.URLError("list down")
        return []

    monkeypatch.setattr(chain_stocks, "_http_json", fake_http_json)

    out = _run(capsys, "--query", "Apple")

    assert out == {"query": "Apple", "error": "<urlopen error list down>"}


def test_no_price_never_touches_the_directory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    urls: list[str] = []

    def fake_http_json(url: str, timeout: float, payload: dict[str, Any] | None = None) -> Any:
        urls.append(url)
        if url == chain_stocks.TOKEN_LIST_URL:
            return TOKEN_LIST
        assert payload is not None
        return {"jsonrpc": "2.0", "id": 1, "result": _rpc_answer(payload)}

    monkeypatch.setattr(chain_stocks, "_http_json", fake_http_json)

    token = _run(capsys, "--query", "Apple", "--no-price")["token"]

    assert chain_stocks.FEEDS_URL not in urls
    assert "readErrors" not in token


def test_a_healthy_directory_still_prices(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Guard: the wrapped fetch still hands a real list to the feed lookup."""
    feed = {
        "name": "Robinhood AAPL / USD",
        "proxyAddress": "0x3333333333333333333333333333333333333333",
        "heartbeat": 86400,
        "threshold": 0.5,
        "docs": {"baseAsset": "AAPL"},
    }
    _stub_http(monkeypatch, [feed])
    monkeypatch.setattr(
        chain_stocks,
        "_read_price",
        lambda _rpc, _proxy, _timeout, _now: {"usd": 1.5, "updatedAt": 0, "ageSeconds": 1},
    )

    token = _run(capsys, "--query", "Apple")["token"]

    assert token["price"]["usd"] == 1.5
    assert "readErrors" not in token
    assert "notes" not in token
