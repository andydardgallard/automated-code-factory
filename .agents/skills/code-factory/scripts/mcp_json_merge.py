#!/usr/bin/env python3
"""
Text-preserving JSON merge machinery shared by the factory's MCP config helpers.

`farukon_mcp.py` and `chrome_devtools_mcp.py` both insert ONE managed server entry into a project's
`.kimi-code/mcp.json` without rewriting the rest of the file. The surgery is identical — locate the
root object and the `mcpServers` map, serialize the new member with the file's own indentation and
line endings, insert it after the last existing member — while each helper keeps its OWN semantics
on top (which server name, which managed entry, when a merge is refused, what a conflict reports).
Those ~70 lines lived twice; this module is their single home, imported by both helpers.

The contract is deliberately narrow:
  - `insert_managed_server(text, server_name, entry)` returns the merged TEXT and never writes a
    file: the caller verifies the result (it re-parses it and compares against the expected object)
    and owns the persistence, its atomicity and its redacted diagnostics;
  - every byte the merge does not have to change survives, including unrelated servers, unrelated
    settings, indentation width and CRLF line endings;
  - a target that is not a JSON object, an `mcpServers` member that is not an object, or text the
    JSON decoder cannot walk raises `ValueError` — the caller turns that into its own reported error
    (a config is NEVER overwritten on a parse failure).

Stdlib only, library only: no CLI, no side effects at import, no model call.
"""
from __future__ import annotations

import json

_DECODER = json.JSONDecoder()


def insert_managed_server(text: str, server_name: str, entry: dict) -> str:
    """Deep-merge `{server_name: entry}` into the `mcpServers` map of the JSON object `text`.

    Every other byte of the document is preserved (see the module docstring). Raises `ValueError`
    when `text` is not a JSON object or its `mcpServers` member is not an object.
    """
    root_open, root_close = _root_span(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    unit = _indent_unit(text)
    root_members = _object_members(text, root_open)
    servers_member = next((member for member in root_members if member[0] == "mcpServers"), None)
    if servers_member is None:
        root_indent = _line_indent(text, root_members[0][1]) if root_members else unit
        block = _member_block("mcpServers", {server_name: entry}, root_indent, newline)
        return _insert_member(text, root_open, root_close, block, root_indent, newline)
    servers_open = servers_member[2]
    if text[servers_open] != "{":
        raise ValueError("mcpServers must be a JSON object")
    _, servers_end = _DECODER.raw_decode(text, servers_open)
    servers_close = servers_end - 1
    servers_members = _object_members(text, servers_open)
    key_indent = _line_indent(text, servers_member[1])
    if servers_members:
        indent = _line_indent(text, servers_members[0][1]) or (key_indent + unit)
    else:
        indent = key_indent + unit
    block = _member_block(server_name, entry, indent, newline)
    return _insert_member(text, servers_open, servers_close, block, indent, newline)


def _skip_ws(text: str, index: int) -> int:
    """The first non-whitespace offset at or after `index`."""
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _object_members(text: str, obj_open: int) -> list[tuple[str, int, int, int]]:
    """`(key, key_start, value_start, value_end)` for the depth-1 members of the object at `{`."""
    members: list[tuple[str, int, int, int]] = []
    index = _skip_ws(text, obj_open + 1)
    while index < len(text) and text[index] != "}":
        key_start = index
        key, index = _DECODER.raw_decode(text, index)
        index = _skip_ws(text, index)
        if index >= len(text) or text[index] != ":":
            raise ValueError(f"expected ':' after key {key!r} at offset {index}")
        index = _skip_ws(text, index + 1)
        value_start = index
        _, index = _DECODER.raw_decode(text, index)
        members.append((str(key), key_start, value_start, index))
        index = _skip_ws(text, index)
        if index < len(text) and text[index] == ",":
            index = _skip_ws(text, index + 1)
    return members


def _root_span(text: str) -> tuple[int, int]:
    """`(offset of the root '{', offset of its matching '}')` — a non-object document is refused."""
    start = _skip_ws(text, 0)
    if start >= len(text) or text[start] != "{":
        raise ValueError("the config must be a JSON object")
    _, end = _DECODER.raw_decode(text, start)
    return start, end - 1


def _line_indent(text: str, index: int) -> str:
    """The indentation of the line holding `index` ("" when that line carries other text)."""
    line_start = text.rfind("\n", 0, index) + 1
    prefix = text[line_start:index]
    return prefix if prefix.strip() == "" else ""


def _indent_unit(text: str) -> str:
    """The file's own indentation step, read from its first indented line (default two spaces)."""
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped and stripped != line:
            indent = line[:len(line) - len(stripped)]
            if indent:
                return indent
    return "  "


def _member_block(key: str, value: dict, indent: str, newline: str) -> str:
    """`"key": value` serialized like the surrounding file (json indent 2, re-indented)."""
    serialized = json.dumps({key: value}, indent=2).replace("\n", newline)
    lines = serialized.splitlines()[1:-1]
    relative = [line[2:] if line.startswith("  ") else line for line in lines]
    return (newline + indent).join(relative)


def _insert_member(text: str, obj_open: int, obj_close: int, block: str, indent: str,
                   newline: str) -> str:
    """Insert a serialized member into an object, keeping every other byte of the file."""
    inner = text[obj_open + 1:obj_close]
    body = inner.rstrip()
    tail = inner[len(body):]
    if body.strip():
        new_inner = body + "," + newline + indent + block + tail
    else:
        if not tail.strip():
            tail = newline + (_line_indent(text, obj_open) or "")
        new_inner = newline + indent + block + tail
    return text[:obj_open + 1] + new_inner + text[obj_close:]
