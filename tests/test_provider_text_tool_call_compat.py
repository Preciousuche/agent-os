"""Text-encoded tool-call extraction must recognize every wrapper protocol
that engine.tool_text_compat already strips from the user-visible text --
otherwise a hidden tool call is silently never executed (#1514).
"""

from __future__ import annotations

from agentos.provider.openai import _synthesize_text_tool_events
from agentos.provider.text_tool_call_compat import (
    TextProtocolToolCall,
    contains_text_tool_call_protocol,
    parse_text_tool_calls,
)
from agentos.provider.types import ToolDefinition, ToolInputSchema


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description="", input_schema=ToolInputSchema())


# ---------------------------------------------------------------------------
# contains_text_tool_call_protocol / parse_text_tool_calls
# ---------------------------------------------------------------------------


def test_plain_text_is_not_detected_as_protocol() -> None:
    assert contains_text_tool_call_protocol("just a normal reply") is False
    assert parse_text_tool_calls("just a normal reply") == []


def test_minimax_wrapper_still_parses() -> None:
    text = (
        "ok\n\n"
        '<minimax:tool_call><invoke name="write_file">'
        '<parameter name="path">a.txt</parameter>'
        '<parameter name="content">hello</parameter>'
        "</invoke></minimax:tool_call>"
    )
    assert contains_text_tool_call_protocol(text) is True
    calls = parse_text_tool_calls(text)
    assert calls == [
        TextProtocolToolCall(name="write_file", arguments={"path": "a.txt", "content": "hello"})
    ]


def test_tvoe_calls_wrapper_parses() -> None:
    """The issue's exact reproduction: a tvoe_calls-wrapped write_file call."""
    text = (
        "Let me write the dashboard now.\n\n"
        '<tvoe_calls><invoke name="write_file">'
        '<parameter name="path">index.html</parameter>'
        '<parameter name="content"><!DOCTYPE html><html><body>app</body></html>'
        "</parameter></invoke></tvoe_calls>"
    )
    calls = parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {
        "path": "index.html",
        "content": "<!DOCTYPE html><html><body>app</body></html>",
    }


def test_dsml_wrapper_parses_and_decodes_json_parameters() -> None:
    """The issue's exact reproduction: DSML's pipe-prefixed wrapper, with a
    string="false" parameter that must be JSON-decoded into a real list, not
    left as an escaped JSON string."""
    text = (
        "Let me create the printable daily record sheet as well:\n\n"
        '<｜DSML｜tool_calls><｜DSML｜invoke name="create_xlsx">'
        '<｜DSML｜parameter name="name" string="true">'
        "bean-sprout-daily-record-sheet.xlsx"
        "</｜DSML｜parameter>"
        '<｜DSML｜parameter name="sheets" string="false">'
        '[{"name":"Record Sheet","rows":[["Day","Height"]]}]'
        "</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>"
    )
    calls = parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "create_xlsx"
    assert calls[0].arguments["name"] == "bean-sprout-daily-record-sheet.xlsx"
    assert calls[0].arguments["sheets"] == [
        {"name": "Record Sheet", "rows": [["Day", "Height"]]}
    ]
    assert isinstance(calls[0].arguments["sheets"], list)


def test_dsml_ascii_pipe_variant_parses() -> None:
    """DSML markup also appears with ASCII pipes (`|DSML|`), not just the
    fullwidth `｜DSML｜` glyph."""
    text = (
        "<|DSML|tool_calls><|DSML|invoke name=\"write_file\">"
        '<|DSML|parameter name="path" string="true">a.txt</|DSML|parameter>'
        "</|DSML|invoke></|DSML|tool_calls>"
    )
    calls = parse_text_tool_calls(text)
    assert calls == [TextProtocolToolCall(name="write_file", arguments={"path": "a.txt"})]


def test_bare_invoke_with_no_wrapper_parses() -> None:
    """engine.tool_text_compat treats a bare <invoke> (no outer wrapper) as
    protocol markup to hide; extraction must match, or the hidden call is
    never executed."""
    text = (
        "ok\n\n"
        '<invoke name="write_file">'
        '<parameter name="path">a.txt</parameter>'
        "</invoke>"
    )
    calls = parse_text_tool_calls(text)
    assert calls == [TextProtocolToolCall(name="write_file", arguments={"path": "a.txt"})]


def test_malformed_json_parameter_falls_back_to_literal_string() -> None:
    """A string="false" parameter that fails to decode must not drop the
    whole tool call -- fall back to the literal text instead."""
    text = (
        '<tvoe_calls><invoke name="create_xlsx">'
        '<｜DSML｜parameter name="sheets" string="false">not valid json'
        "</｜DSML｜parameter></invoke></tvoe_calls>"
    )
    calls = parse_text_tool_calls(text)
    assert calls[0].arguments["sheets"] == "not valid json"


# ---------------------------------------------------------------------------
# _synthesize_text_tool_events: end-to-end wiring
# ---------------------------------------------------------------------------


def test_synthesize_events_for_tvoe_calls_matches_the_issue_repro() -> None:
    tools = [_tool("write_file")]
    text = (
        "Let me write the dashboard now.\n\n"
        '<tvoe_calls><invoke name="write_file">'
        '<parameter name="path">index.html</parameter>'
        '<parameter name="content"><!DOCTYPE html><html><body>app</body></html>'
        "</parameter></invoke></tvoe_calls>"
    )
    events = _synthesize_text_tool_events(text, tools)
    assert len(events) == 2
    start, end = events
    assert start.kind == "tool_use_start"
    assert start.tool_name == "write_file"
    assert end.kind == "tool_use_end"
    assert end.arguments["path"] == "index.html"


def test_synthesize_events_for_dsml_matches_the_issue_repro() -> None:
    tools = [_tool("create_xlsx")]
    text = (
        "Let me create the sheet:\n\n"
        '<｜DSML｜tool_calls><｜DSML｜invoke name="create_xlsx">'
        '<｜DSML｜parameter name="name" string="true">sheet.xlsx</｜DSML｜parameter>'
        '<｜DSML｜parameter name="sheets" string="false">'
        '[{"name":"Sheet1","rows":[["a","b"]]}]'
        "</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>"
    )
    events = _synthesize_text_tool_events(text, tools)
    assert len(events) == 2
    end = events[1]
    assert end.tool_name == "create_xlsx"
    assert end.arguments["sheets"] == [{"name": "Sheet1", "rows": [["a", "b"]]}]


def test_synthesize_events_ignores_unregistered_tool_names() -> None:
    """A text-encoded call to a tool the model wasn't offered must not run."""
    tools = [_tool("write_file")]
    text = '<tvoe_calls><invoke name="delete_everything"></invoke></tvoe_calls>'
    assert _synthesize_text_tool_events(text, tools) == []


def test_synthesize_events_empty_for_plain_text() -> None:
    tools = [_tool("write_file")]
    assert _synthesize_text_tool_events("just chatting, no tools here", tools) == []
