"""Compatibility parser for text-encoded tool-call protocols.

Some models emit a tool call as XML-shaped text in the assistant message
instead of a real function-call payload. The `<invoke name="...">` /
`<parameter name="...">` pair is the actual signal; different providers wrap
it in different outer tags that mean nothing beyond "this is a tool call":
MiniMax's ``<minimax:tool_call>``, the ``<tvoe_calls>`` typo-wrapper, DSML's
pipe-prefixed ``<|DSML|tool_calls>`` / ``<｜DSML｜tool_calls>``, or no wrapper
at all. ``engine.tool_text_compat`` already strips all of these variants from
what the user sees; this module has to recognize the same set, or a
successfully-hidden tool call is silently never executed.

DSML additionally tags each ``<parameter>`` with ``string="true"`` or
``string="false"`` to say whether its text content is a literal string or a
JSON-encoded value (a list, dict, number, or bool) that must be decoded
before it reaches the tool's real argument type -- a `sheets` parameter for
a spreadsheet tool, say, needs a list, not the string ``"[...]"``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_INVOKE_RE = re.compile(
    r'<\s*(?:[|｜]\s*DSML\s*[|｜]\s*)?invoke\s+name\s*=\s*"([^"]+)"\s*>(.*?)'
    r'<\s*/\s*(?:[|｜]\s*DSML\s*[|｜]\s*)?invoke\s*>',
    re.DOTALL | re.IGNORECASE,
)
_PARAM_RE = re.compile(
    r'<\s*(?:[|｜]\s*DSML\s*[|｜]\s*)?parameter\s+name\s*=\s*"([^"]+)"'
    r'(?:\s+string\s*=\s*"(true|false)")?\s*>(.*?)'
    r'<\s*/\s*(?:[|｜]\s*DSML\s*[|｜]\s*)?parameter\s*>',
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class TextProtocolToolCall:
    name: str
    arguments: dict[str, object]


def contains_text_tool_call_protocol(text: str) -> bool:
    """Return True when text contains a text-encoded ``<invoke>`` tool call.

    The outer wrapper tag (``<minimax:tool_call>``, ``<tvoe_calls>``, DSML's
    pipe-prefixed tags, or none at all) carries no information beyond "this
    is a tool call" -- the ``<invoke name="...">`` tag is the real signal, so
    detection keys on that directly rather than enumerating every wrapper
    spelling a model might produce.
    """
    return bool(_INVOKE_RE.search(text))


def _decode_parameter_value(raw: str, is_json: bool) -> object:
    if is_json:
        try:
            return json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            # A parameter explicitly marked string="false" that fails to
            # decode is likely truncated or malformed; falling back to the
            # literal text is safer than dropping the whole tool call.
            pass
    value = raw
    if value.startswith("\n"):
        value = value[1:]
    if value.endswith("\n"):
        value = value[:-1]
    return value


def parse_text_tool_calls(text: str) -> list[TextProtocolToolCall]:
    """Extract text-encoded tool invocations from assistant text."""
    if not contains_text_tool_call_protocol(text):
        return []

    calls: list[TextProtocolToolCall] = []
    for invoke_match in _INVOKE_RE.finditer(text):
        name = invoke_match.group(1).strip()
        body = invoke_match.group(2)
        arguments: dict[str, object] = {}
        for param_match in _PARAM_RE.finditer(body):
            key = param_match.group(1).strip()
            is_json = param_match.group(2) == "false"
            arguments[key] = _decode_parameter_value(param_match.group(3), is_json)
        if name:
            calls.append(TextProtocolToolCall(name=name, arguments=arguments))
    return calls
