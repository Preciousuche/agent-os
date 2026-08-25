from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from agentos.skills.hub.aeon import AeonSource, adapt_skill_md
from agentos.skills.hub.source import SkillBundle, SkillMeta
from agentos.skills.loader import _parse_frontmatter, _resolve_metadata

_FIXTURE_SLUGS = ("tx-explain", "token-pick", "github-trending", "missing-from-catalog")

_CATALOG = {
    "version": "1.0",
    "repo": "aeonfun/aeon",
    "total": 4,
    "skills": [
        {
            "slug": "tx-explain",
            "name": "Tx Explain",
            "description": "Decode any Base transaction into a plain-English story.",
            "category": "basics",
            "requires": [{"key": "ETHERSCAN_API_KEY", "optional": True}],
            "mcp": [],
            "sha": "e1d9284",
        },
        {
            "slug": "token-pick",
            "name": "Token Pick",
            "description": "One token recommendation and one prediction market pick.",
            "category": "crypto",
            "requires": [{"key": "COINGECKO_API_KEY", "optional": True}],
            "mcp": [],
            "sha": "abc1234",
        },
        {
            "slug": "github-trending",
            "name": "GitHub Trending",
            "description": "Curated trending across GitHub repos and the Hugging Face Hub.",
            "category": "basics",
            "requires": [],
            "mcp": ["glim"],
            "sha": "def5678",
        },
        {
            # Present in the catalog but never allowlisted — a partner adding a
            # skill upstream must not make it installable here by itself.
            "slug": "memory-flush",
            "name": "Memory Flush",
            "description": "Housekeeping over the instance memory store.",
            "category": "core",
            "requires": [],
            "mcp": [],
            "sha": "0000000",
        },
    ],
}

_TX_EXPLAIN_MD = """\
---
name: tx-explain
description: Decode any Base transaction.
metadata:
  title: Tx Explain
  mode: read-only
  category: basics
  var: ''
  tags:
  - crypto
  - base
  requires:
  - ETHERSCAN_API_KEY?
  - BASE_RPC_URL?
---

## Steps

Read `memory/MEMORY.md` for context, then notify via `./notify`.
"""


class _Response:
    def __init__(self, *, content: bytes = b"", status_code: int = 200) -> None:
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _AsyncClient:
    """Mocks the single catalog/skills.json fetch the Aeon source makes."""

    payload: bytes = json.dumps(_CATALOG).encode("utf-8")
    status_code = 200
    calls = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _AsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> _Response:
        if "/git/trees/" in url:
            raise AssertionError(f"tree API must not be called during browse: {url}")
        if url.endswith("catalog/skills.json"):
            type(self).calls += 1
            return _Response(content=self.payload, status_code=self.status_code)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    _AsyncClient.payload = json.dumps(_CATALOG).encode("utf-8")
    _AsyncClient.status_code = 200
    _AsyncClient.calls = 0


def _source() -> AeonSource:
    return AeonSource(allowlist=_FIXTURE_SLUGS)


def _url(slug: str) -> str:
    return f"https://github.com/aeonfun/aeon/tree/main/skills/{slug}"


@pytest.mark.asyncio
async def test_search_lists_only_allowlisted_catalog_rows(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    results = await _source().search("")

    # memory-flush is in the catalog but not the allowlist; missing-from-catalog
    # is allowlisted but absent upstream. Neither may produce a row.
    assert {r.name for r in results} == {"tx-explain", "token-pick", "github-trending"}
    assert all(r.source_id == "aeon" for r in results)
    assert all(r.trust_level == "community" for r in results)


@pytest.mark.asyncio
async def test_the_whole_catalog_costs_one_request(monkeypatch) -> None:
    """Aeon publishes a real index, so browsing must not fan out per slug."""
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    await _source().search("")

    assert _AsyncClient.calls == 1


@pytest.mark.asyncio
async def test_a_catalog_row_cannot_choose_its_own_brand(monkeypatch) -> None:
    import httpx

    hostile = json.loads(json.dumps(_CATALOG))
    hostile["skills"][0]["provider"] = "Robinhood"
    hostile["skills"][0]["logo"] = "https://evil.example/logo.png"
    _AsyncClient.payload = json.dumps(hostile).encode("utf-8")
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    row = next(r for r in await _source().search("") if r.name == "tx-explain")

    assert row.provider == "Aeon"
    assert row.logo == ""


@pytest.mark.asyncio
async def test_search_derives_a_distinct_category_per_skill(monkeypatch) -> None:
    """A single hard-coded category would collapse the browse chip row."""
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    cats = {r.name: r.category for r in await _source().search("")}

    assert cats["token-pick"] == "defi"  # inferred from the slug
    assert cats["tx-explain"] == "data"  # Aeon "basics" fallback
    assert len(set(cats.values())) > 1


@pytest.mark.asyncio
async def test_requires_and_mcp_become_setup_steps(monkeypatch) -> None:
    """Aeon's requires contract has no other route to the browse card."""
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    rows = {r.name: r for r in await _source().search("")}

    assert rows["tx-explain"].setup[0] == "Optional: set ETHERSCAN_API_KEY"
    assert rows["github-trending"].setup == ["Connect the glim MCP server"]
    assert rows["tx-explain"].version == "e1d9284"
    assert rows["tx-explain"].license == "MIT"


@pytest.mark.asyncio
async def test_search_filters_by_query(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    results = await _source().search("prediction market")

    assert [r.name for r in results] == ["token-pick"]


@pytest.mark.asyncio
async def test_catalog_is_cached_between_searches(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    source = _source()

    await source.search("")
    await source.search("token")

    assert _AsyncClient.calls == 1


@pytest.mark.asyncio
async def test_a_failed_catalog_fetch_yields_no_rows(monkeypatch) -> None:
    import httpx

    _AsyncClient.status_code = 500
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert await _source().search("") == []


@pytest.mark.asyncio
async def test_a_malformed_catalog_yields_no_rows(monkeypatch) -> None:
    import httpx

    _AsyncClient.payload = b"{ not json"
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    assert await _source().search("") == []


@pytest.mark.asyncio
async def test_inspect_and_fetch_enforce_the_allowlist(monkeypatch) -> None:
    """The source a skill arrives through brands it, so it must not pull
    an arbitrary directory out of the partner's repository."""
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    source = _source()

    async def _fail(identifier: str) -> None:
        raise AssertionError(f"GitHubSource must not be reached for {identifier}")

    monkeypatch.setattr(source._github, "fetch", _fail)
    monkeypatch.setattr(source._github, "inspect", _fail)

    for bad in (
        _url("memory-flush"),  # real skill, not allowlisted
        "https://github.com/aeonfun/aeon/tree/main/scripts",  # not under skills/
        "https://github.com/attacker/aeon/tree/main/skills/tx-explain",  # wrong repo
        "https://github.com/aeonfun/aeon/tree/main/skills/tx-explain/nested",
    ):
        assert await source.inspect(bad) is None
        assert await source.fetch(bad) is None


@pytest.mark.asyncio
async def test_fetch_adapts_the_skill_and_carries_the_catalog_version(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    source = _source()

    async def _fetch(identifier: str) -> SkillBundle:
        return SkillBundle(
            name="tx-explain",
            files={"SKILL.md": _TX_EXPLAIN_MD},
            meta=SkillMeta(name="tx-explain"),
        )

    monkeypatch.setattr(source._github, "fetch", _fetch)

    bundle = await source.fetch(_url("tx-explain"))

    assert bundle is not None
    assert "Running under AgentOS" in str(bundle.files["SKILL.md"])
    # Without this the lockfile records no version, and an upstream rewrite of
    # an allowlisted skill would be invisible.
    assert bundle.meta is not None
    assert bundle.meta.version == "e1d9284"
    assert bundle.meta.provider == "Aeon"


def test_adapt_recovers_env_vars_the_loader_would_otherwise_drop() -> None:
    """Aeon writes ``requires`` as a list; ``_resolve_metadata`` reads only a dict."""
    assert _resolve_metadata(_parse_frontmatter(_TX_EXPLAIN_MD)[0]).requires is None

    adapted = adapt_skill_md(_TX_EXPLAIN_MD, "tx-explain")
    requires = _resolve_metadata(_parse_frontmatter(adapted)[0]).requires

    assert requires is not None
    assert [(e.name, e.required) for e in requires.env] == [
        ("ETHERSCAN_API_KEY", False),
        ("BASE_RPC_URL", False),
    ]


def test_adapt_puts_the_installed_row_in_the_same_bucket_as_the_browse_card() -> None:
    adapted = adapt_skill_md(_TX_EXPLAIN_MD, "tx-explain")

    assert _resolve_metadata(_parse_frontmatter(adapted)[0]).category == "data"


def test_adapt_leaves_the_body_untouched() -> None:
    body = _parse_frontmatter(_TX_EXPLAIN_MD)[1]

    adapted = adapt_skill_md(_TX_EXPLAIN_MD, "tx-explain")

    assert body in adapted
    assert yaml.safe_load(_parse_frontmatter(adapted)[0]["metadata"]["title"]) == "Tx Explain"


def test_adapt_returns_unparseable_input_unchanged() -> None:
    """A skill that installs with stale metadata beats one that fails to install."""
    for junk in ("no frontmatter here", "---\n: : :\n---\nbody\n", "---\njust a string\n---\n"):
        assert adapt_skill_md(junk, "tx-explain") == junk


@pytest.mark.asyncio
async def test_default_router_exposes_the_aeon_source() -> None:
    from agentos.skills.hub.defaults import get_default_skill_router

    router = get_default_skill_router()

    # Aeon must sit ahead of the generic GitHub source: the router dedupes
    # merged results by name and first source wins, so a bare code-search row
    # would otherwise shadow the branded one.
    ids = router.source_ids
    assert "aeon" in ids
    assert ids.index("aeon") < ids.index("github")
