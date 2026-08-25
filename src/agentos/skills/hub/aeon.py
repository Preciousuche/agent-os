"""Aeon skill source — browses and installs skills from the Aeon catalog.

The Aeon repository (https://github.com/aeonfun/aeon) publishes every skill as
``skills/<slug>/SKILL.md`` and indexes all of them in a single
``catalog/skills.json``. That index is the difference from the other partner
sources: Bankr and Capminal have to fan out one request per allowlisted slug
because neither publishes something crawlable, while one GET here describes the
whole catalog.

Aeon skills are written for Aeon's own runtime — scheduled GitHub Actions runs
with a durable ``memory/`` directory, a ``./secretcurl`` credential wrapper, and
a ``./notify`` Telegram transport. None of that exists in AgentOS, so the
allowlist here is a *portability* filter rather than the crawlability workaround
it is for Bankr, and :func:`adapt_skill_md` reconciles what is left. Downloading
and installation are delegated to :class:`GitHubSource`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from typing import Any

import structlog
import yaml

from agentos.env import trust_env as _trust_env
from agentos.skills.hub.github import GitHubSource, _parse_identifier
from agentos.skills.hub.source import SkillBundle, SkillMeta, SkillSource, infer_category

log = structlog.get_logger(__name__)

_DEFAULT_REPO = "aeonfun/aeon"
_DEFAULT_REF = "main"
_CATALOG_PATH = "catalog/skills.json"
#: Directory under the repository root that holds one directory per skill.
_SKILL_ROOT = "skills"
# Only these skills are loaded from aeonfun/aeon. Aeon publishes 75, but most
# either operate an Aeon instance (``aeon-doctor``, ``memory-flush``,
# ``fork-fleet``) or read ``memory/`` as their actual input, and neither
# survives the move to an interactive runtime.
#
# Every slug here had its live data sources checked. Needing a credential is
# not disqualifying — operators supply their own — so the bar is that the skill
# is coherent under an interactive runtime and that its setup steps say plainly
# what it costs to run. :data:`_SETUP_NOTES` carries the cases where the
# catalog's own "optional" flag understates that.
_ALLOWED_SLUGS: tuple[str, ...] = (
    "github-trending",
    "investigation-report",
    "last30",
    "narrative-tracker",
    "pm-manipulation",
    "token-pick",
    "tx-explain",
    "unlock-monitor",
    "video-script",
    "you-web-search",
)

#: Per-skill setup caveats that ``requires`` alone does not convey. Aeon marks
#: a key "optional" when the skill still starts without it, which is true but
#: hides how much stops working — verified live against each provider.
_SETUP_NOTES: dict[str, str] = {
    "investigation-report": (
        "Etherscan v2 rejects unkeyed requests and does not serve Base on the "
        "free tier — four of the six checks need a paid plan"
    ),
    "tx-explain": (
        "Without an Etherscan key, method decoding falls back to the built-in "
        "selector table; Base RPC and receipt-log parsing stay keyless"
    ),
}
_AEON_EMOJI = "🌀"
_CATALOG_TTL_SECONDS = 15 * 60
_FAILURE_RETRY_SECONDS = 60

#: Aeon's six categories mapped onto the browse buckets AgentOS filters by.
#: Consulted only when :func:`infer_category` finds nothing more specific, so a
#: skill whose slug says "token" still lands in "defi" rather than being flattened
#: into its Aeon category. Hard-coding one category for the whole catalog would
#: collapse the browse chip row into a single no-op filter.
_AEON_CATEGORY_FALLBACK: dict[str, str] = {
    "crypto": "crypto",
    "dev": "dev",
    "basics": "data",
    "productivity": "other",
    "core": "other",
    "evolution": "other",
}

#: Prepended to every installed Aeon skill, between the frontmatter and Aeon's
#: own prose. Aeon's runtime affordances appear as discrete edge blocks in the
#: allowlisted skills — a "read memory/ to dedup" preamble, a "send via
#: ./notify" step, a closing log template — rather than being woven through the
#: logic, which is why annotating them is enough and forking the prose is not.
#: Written against the instance layout as a whole rather than the specific paths
#: seen today, because ``soul/`` and ``output/`` turned up in skills whose
#: ``memory/`` coupling had already been accounted for.
_ADAPTER_NOTE = """\
> **Running under AgentOS.** This skill was written for Aeon's scheduled
> runtime, which does not exist here. Adapt it as follows:
>
> - **No Aeon instance files.** Paths rooted in an Aeon checkout — `memory/`,
>   `soul/`, `output/`, `scripts/`, `aeon.yml` — are absent. Skip any step that
>   reads or writes them, including the dedup-against-past-runs preamble and the
>   closing log block, and take context from this conversation instead.
> - **No `./secretcurl`.** Use `curl` with the environment variable directly, or
>   the keyless fallback the skill documents.
> - **No `./notify`.** Present the report in your reply. Keep the skill's own
>   significance gate: if it says to stay quiet when nothing is notable, say that
>   briefly rather than padding.
> - **`${var}` is the argument the user gave you**; `${today}` is today's date.
>   Neither is a template the runtime substitutes.
"""


def _category_for(slug: str, aeon_category: str) -> str:
    """Return the browse-filter bucket for an Aeon skill.

    Deliberately takes only the two facts both call sites have. The browse card
    reads ``catalog/skills.json`` and the installed row reads SKILL.md
    frontmatter; feeding the richer of the two (frontmatter ``tags``) to one and
    not the other put the same skill in different buckets on the two surfaces.
    """
    inferred = infer_category(slug, "Aeon", [aeon_category] if aeon_category else [])
    if inferred != "other":
        return inferred
    return _AEON_CATEGORY_FALLBACK.get(aeon_category, "other")


def _env_requirements(requires: object) -> list[tuple[str, bool]]:
    """Return ``(name, optional)`` pairs from a catalog ``requires`` list.

    Aeon writes these two ways: ``{"key": "X", "optional": true}`` in
    ``catalog/skills.json`` and a bare ``X?`` string in SKILL.md frontmatter,
    where the ``?`` suffix marks it optional. Both are accepted so the same
    helper serves the catalog and the frontmatter rewrite.
    """
    if not isinstance(requires, list):
        return []
    out: list[tuple[str, bool]] = []
    for item in requires:
        if isinstance(item, dict):
            key = str(item.get("key") or "").strip()
            optional = bool(item.get("optional"))
        elif isinstance(item, str):
            key = item.strip()
            optional = key.endswith("?")
            key = key.rstrip("?").strip()
        else:
            continue
        if key:
            out.append((key, optional))
    return out


def _setup_steps(slug: str, requires: object, mcp: object) -> list[str]:
    """Render the catalog's credential and MCP prerequisites as setup steps.

    Aeon's ``requires`` contract does not map onto AgentOS's
    ``metadata.agentos.requires.env`` schema, so without this the browse card
    would claim a skill needs nothing while its body reaches for an API key.
    """
    steps = [
        f"Set {name}" if not optional else f"Optional: set {name}"
        for name, optional in _env_requirements(requires)
    ]
    if isinstance(mcp, list):
        steps += [f"Connect the {str(s).strip()} MCP server" for s in mcp if str(s).strip()]
    note = _SETUP_NOTES.get(slug)
    if note:
        steps.append(note)
    return steps


def _split_frontmatter(skill_md: str) -> tuple[str, str] | None:
    """Split ``SKILL.md`` into its raw frontmatter block and the body after it."""
    if not skill_md.startswith("---"):
        return None
    end = skill_md.find("\n---", 3)
    if end == -1:
        return None
    body_start = skill_md.find("\n", end + 1)
    if body_start == -1:
        return None
    return skill_md[4:end], skill_md[body_start + 1 :]


def adapt_skill_md(skill_md: str, slug: str) -> str:
    """Reconcile one Aeon ``SKILL.md`` with what AgentOS reads.

    Three edits, none of which touch Aeon's prose:

    * ``metadata.requires`` is rewritten from Aeon's list form into the
      ``{env: [{name, required}]}`` shape ``_resolve_metadata`` understands.
      AgentOS silently drops the list form, so without this the optional keys
      these skills can use never reach the operator.
    * ``metadata.category`` is remapped onto a real browse bucket, so the
      installed row and the catalog card agree.
    * :data:`_ADAPTER_NOTE` is inserted between the frontmatter and the body.

    Returns the input unchanged when the frontmatter cannot be parsed — a skill
    that installs with stale metadata beats one that fails to install at all.
    """
    split = _split_frontmatter(skill_md)
    if split is None:
        return skill_md
    raw_fm, body = split
    try:
        frontmatter = yaml.safe_load(raw_fm)
    except yaml.YAMLError:
        return skill_md
    if not isinstance(frontmatter, dict):
        return skill_md

    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict):
        env = [
            {"name": name, "required": not optional}
            for name, optional in _env_requirements(metadata.get("requires"))
        ]
        if env:
            metadata["requires"] = {"env": env}
        metadata["category"] = _category_for(slug, str(metadata.get("category") or ""))

    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{rendered}\n---\n\n{_ADAPTER_NOTE}\n{body.lstrip()}"


def _matches(meta: SkillMeta, query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join(
        [meta.name, meta.provider, meta.category, meta.description, *meta.tags]
    ).lower()
    return q in haystack


class AeonSource(SkillSource):
    """Skill source backed by the aeonfun/aeon GitHub catalog."""

    def __init__(
        self,
        token: str | None = None,
        *,
        repo: str = _DEFAULT_REPO,
        ref: str = _DEFAULT_REF,
        allowlist: Sequence[str] = _ALLOWED_SLUGS,
    ) -> None:
        self._github = GitHubSource(token=token)
        self._repo = repo
        self._ref = ref
        self._allowlist = tuple(allowlist)
        self._raw_base = f"https://raw.githubusercontent.com/{repo}/{ref}"
        self._cache_metas: list[SkillMeta] | None = None
        self._cache_at = 0.0
        self._last_failure_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def source_id(self) -> str:
        return "aeon"

    @property
    def trust_level(self) -> str:
        return "community"

    def _skill_url(self, slug: str) -> str:
        return f"https://github.com/{self._repo}/tree/{self._ref}/{_SKILL_ROOT}/{slug}"

    async def search(self, query: str, limit: int = 200) -> list[SkillMeta]:
        """List Aeon skills (all when query is empty; filtered otherwise)."""
        metas = await self._load_catalog()
        results = [m for m in metas if _matches(m, query)]
        return results[:limit]

    def _allowlisted_slug(self, identifier: str) -> str | None:
        """Return the allowlisted slug ``identifier`` names, or ``None``.

        Both the repository and the full ``skills/<slug>`` path are checked, so
        an identifier cannot pull an arbitrary directory out of aeonfun/aeon —
        the source a skill arrives through is recorded as its provenance and
        brands it as Aeon's.
        """
        ref = _parse_identifier(identifier)
        if ref is None or ref.repo_full.lower() != self._repo.lower():
            return None
        for slug in self._allowlist:
            if ref.skill_dir.strip("/") == f"{_SKILL_ROOT}/{slug}":
                return slug
        return None

    async def inspect(self, identifier: str) -> SkillMeta | None:
        slug = self._allowlisted_slug(identifier)
        if slug is None:
            log.warning("aeon.identifier_rejected", op="inspect")
            return None
        for meta in await self._load_catalog():
            if meta.name == slug:
                return meta
        return await self._github.inspect(identifier)

    async def fetch(self, identifier: str) -> SkillBundle | None:
        slug = self._allowlisted_slug(identifier)
        if slug is None:
            log.warning("aeon.identifier_rejected", op="fetch")
            return None
        bundle = await self._github.fetch(identifier)
        if bundle is None:
            return None
        skill_md = bundle.files.get("SKILL.md")
        if isinstance(skill_md, str):
            bundle.files["SKILL.md"] = adapt_skill_md(skill_md, slug)
        # GitHubSource builds a bare meta from the frontmatter, which carries no
        # version. Swap in the catalog row so the lockfile records the commit
        # sha — the only handle we have for noticing that an allowlisted skill
        # changed underneath us.
        for meta in await self._load_catalog():
            if meta.name == slug:
                bundle.meta = meta
                break
        return bundle

    async def _load_catalog(self) -> list[SkillMeta]:
        async with self._lock:
            now = time.monotonic()
            if self._cache_metas is not None and (now - self._cache_at) < _CATALOG_TTL_SECONDS:
                return self._cache_metas
            # Negative cache: after a failed fetch, serve what we have without hammering GitHub.
            if (now - self._last_failure_at) < _FAILURE_RETRY_SECONDS:
                return self._cache_metas or []

            metas = await self._fetch_catalog()
            if metas is None:
                self._last_failure_at = time.monotonic()
                return self._cache_metas or []

            self._cache_metas = metas
            self._cache_at = time.monotonic()
            return metas

    async def _fetch_catalog(self) -> list[SkillMeta] | None:
        """Fetch the single catalog index and build one row per allowlisted slug."""
        import httpx

        if not self._allowlist:
            return []

        url = f"{self._raw_base}/{_CATALOG_PATH}"
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=_trust_env()) as client:
                resp = await client.get(url, headers=self._github._headers())
                resp.raise_for_status()
                catalog = json.loads(resp.content)
        except Exception as exc:
            log.warning("aeon.fetch_failed", error=str(exc))
            return None

        rows = catalog.get("skills") if isinstance(catalog, dict) else None
        if not isinstance(rows, list):
            log.warning("aeon.catalog_malformed")
            return None

        by_slug = {
            str(row.get("slug") or ""): row
            for row in rows
            if isinstance(row, dict) and row.get("slug")
        }
        metas = [
            self._meta_from_catalog(slug, by_slug[slug])
            for slug in self._allowlist
            if slug in by_slug
        ]
        if not metas:
            return None
        metas.sort(key=lambda m: m.name)
        return metas

    def _meta_from_catalog(self, slug: str, row: dict[str, Any]) -> SkillMeta:
        """Build a browse-time SkillMeta from one ``catalog/skills.json`` row.

        ``provider`` is hard-coded rather than read from the row: the source a
        skill arrives through is what brands it, and a catalog entry must not be
        able to choose the name it appears under.
        """
        aeon_category = str(row.get("category") or "")
        tags = [aeon_category] if aeon_category else []
        identifier = self._skill_url(slug)
        return SkillMeta(
            # The slug, not the catalog's display name: it is what the skill's
            # own frontmatter declares, so the lockfile key and the "installed"
            # badge on this card agree.
            name=slug,
            description=str(row.get("description") or ""),
            version=str(row.get("sha") or ""),
            author="aeon",
            source_id="aeon",
            trust_level="community",
            identifier=identifier,
            homepage=identifier,
            license="MIT",
            tags=tags,
            provider="Aeon",
            logo="",
            emoji=_AEON_EMOJI,
            category=_category_for(slug, aeon_category),
            setup=_setup_steps(slug, row.get("requires"), row.get("mcp")),
        )
