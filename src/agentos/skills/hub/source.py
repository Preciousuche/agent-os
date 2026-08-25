"""SkillSource ABC and Community source data models."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# Coarse category buckets inferred from the slug/provider so the browse UI can
# offer meaningful filter chips. Keywords match whole slug/provider tokens
# (split on non-alphanumerics), not substrings — so "design" does not become
# "sign" and "alphabet" does not become "bet". Ordered by specificity — first
# keyword hit wins.
#
# This lives here rather than in one source module because every catalog source
# needs the same buckets: a category is a *browse filter*, and filters only work
# when the sources agree on what "defi" means. A source that hard-codes one
# category for its whole catalog collapses the chip row into a no-op.
_CATEGORY_KEYWORDS: list[tuple[str, frozenset[str]]] = [
    ("trading", frozenset({"trade", "trading", "swap", "uniswap", "dex", "perp", "hyperliquid"})),
    (
        "defi",
        frozenset({"defi", "aave", "lend", "yield", "vault", "stake", "liquidity", "lp", "token"}),
    ),
    ("wallet", frozenset({"wallet", "account", "erc4337", "signer", "sign", "custody"})),
    ("markets", frozenset({"polymarket", "kalshi", "prediction", "bet", "market", "odds"})),
    (
        "social",
        frozenset({"farcaster", "twitter", "neynar", "social", "community", "chat", "message"}),
    ),
    (
        "data",
        frozenset(
            {"alchemy", "zerion", "data", "monitor", "analytics", "index", "scan", "research"}
        ),
    ),
    ("nft", frozenset({"nft", "collectible", "mint", "opensea"})),
    (
        "dev",
        frozenset({"foundry", "contract", "audit", "gas", "deploy", "sdk", "dev", "skill", "eval"}),
    ),
    ("infra", frozenset({"ens", "rpc", "node", "infra", "gateway", "x402", "webhook"})),
]


def infer_category(slug: str, provider: str, tags: Sequence[str] = ()) -> str:
    """Return a coarse category for browse filters, or "other" when unknown.

    ``tags`` is folded into the same token set as the slug and provider, so a
    skill whose slug says little on its own still lands in a real bucket.
    Sources that parse ``tags`` out of frontmatter should pass them; those that
    have none can omit the argument.
    """
    haystack = " ".join([slug, provider, *tags]).lower()
    tokens = set(_TOKEN_RE.findall(haystack))
    for category, keywords in _CATEGORY_KEYWORDS:
        if tokens & keywords:
            return category
    return "other"


@dataclass
class SkillMeta:
    """Metadata for a skill in a Community source listing."""

    name: str
    description: str = ""
    version: str = ""
    author: str = ""
    source_id: str = ""
    trust_level: str = "community"  # "builtin" | "trusted" | "community"
    identifier: str = ""  # source-specific ID (e.g. slug@version)
    homepage: str = ""
    license: str = ""
    tags: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    provider: str = ""  # publisher/brand (e.g. Bankr catalog "provider")
    logo: str = ""  # raw URL to a logo asset, or "" for an initials fallback
    emoji: str = ""  # avatar emoji shown when no logo asset is available
    category: str = ""  # coarse grouping for browse filters (e.g. "defi")
    setup: list[str] = field(default_factory=list)  # ordered setup steps, if any
    demo: dict[str, Any] = field(default_factory=dict)  # {title, language, code}


@dataclass
class SkillBundle:
    """Downloaded skill ready for installation."""

    name: str
    files: dict[str, str | bytes] = field(default_factory=dict)  # relative_path → content
    meta: SkillMeta | None = None

    @property
    def skill_md(self) -> str | None:
        content = self.files.get("SKILL.md")
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None


class SkillSource(ABC):
    """Abstract base class for skill Community sources."""

    @abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[SkillMeta]:
        """Search for skills matching query."""

    @abstractmethod
    async def fetch(self, identifier: str) -> SkillBundle | None:
        """Download a skill by its source-specific identifier."""

    @abstractmethod
    async def inspect(self, identifier: str) -> SkillMeta | None:
        """Get metadata for a skill without downloading."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this source (e.g. 'clawhub', 'github')."""

    @property
    @abstractmethod
    def trust_level(self) -> str:
        """Trust level: 'builtin', 'trusted', or 'community'."""
