#!/usr/bin/env python3
"""
Deterministic task-file parser for the Code Factory (stdlib only, zero LLM tokens).

Phase 0 of a run reads the owner's `task.yaml`. Doing that with an LLM alone is the weak link:
a perfectly valid task with a `business_tests:` block or a multi-line (`|`) acceptance criterion
was rejected as "unreadable", and a rejection costs a whole run. This module is the deterministic
reader for the DOCUMENTED task schema — a deliberately SCOPED YAML subset, not a general YAML
implementation. It never guesses: what it does not understand is an actionable error, never a
silent loss.

Supported schema (top level, column 0):

  title:            <text>          required, non-empty
  repo_path:        <path>          required unless `green_field: true`
  description:      <text>          optional (block scalar `|` / `>` allowed)
  user_story:       <text>          optional (block scalar allowed)
  mode:             hitl | auto     optional (default: hitl)
  task_type:        implement | review | refactor | security_audit   optional (default: implement)
  green_field:      true | false    optional (default: false) — a brand-new project created in place
  acceptance_criteria:              optional list of items, each one of
      - <text>                      a plain string item (a quoted one too)
      - criterion: <text>           with optional siblings `verify: <command>`, `derived: true`
  business_tests:                   optional list of `- scenario/config/expected_results` mappings
  commit_exclude:                   optional list of plain strings
  models:                           optional FLAT mapping `<role>: <model>`
  reference_docs:                   optional list of `- path/skill` mappings
  reference_skills:                 optional list of plain strings

Every text value may be a plain (multi-word) scalar, a quoted scalar, a literal block scalar
(`|`, also `|-` and `|+`) or a folded one (`>`); a key written with no value followed by indented
lines is read as the same text block (the shape the live tasks actually use for `user_story:`).
A quoted scalar must be CLOSED on the same line, and a double-quoted one must be valid
JSON-escaped text: `title: "unterminated` or an invalid escape (`"A \\q value"`) is an error naming
the line and the fix, never text that silently keeps its opening quote.
Block scalars chomp the way YAML does, for both the literal and the folded style: `|-` strips
(no trailing newline), plain `|`/`>` clips (exactly one trailing newline) and `|+`/`>+` keeps
EVERY trailing blank line of the block, so a keep-form text is never shortened. LEADING and
interior blank lines are content in all three forms and survive verbatim (the block indentation
comes from its first NON-blank line). The empty element `str.split` leaves after a terminal newline
is not a line of the file, so a keep-chomp block at the end of a file gains no phantom blank line.
`#` starts a comment — as a full line or trailing one, except inside quotes; blank lines are
ignored; CRLF is normalized to LF before parsing. `derived:` takes only `true` or `false`
(case-insensitive, absent = false): any other value is an error, never a silent false.

Indentation is 2-space based: the keys of one item and the items of one list are aligned, and a
misaligned line is an error that names the line, the column it needs and the fix. A block scalar
body is dedented by the indent of its first non-blank line; a line indented less than that is the
same class of error.

Output: the normalized task as JSON (every text VERBATIM — nothing is re-wrapped, re-quoted or
trimmed inside a text), written to `--out` and summarized in one line on stdout.

Usage:
  python task_parser.py parse --task <file> [--out <json>]
  python task_parser.py --help

Exit codes: 0 = the task was parsed (the summary is printed, `--out` written); 2 = the task is
malformed, unreadable, or the CLI was called wrongly — always a one-line `error: ...` message that
names the file, the line, what is wrong and how to fix it, never a traceback.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Top-level fields of the documented schema, in the order the normalized JSON uses.
TOP_FIELDS = ("title", "repo_path", "description", "user_story", "mode", "task_type",
              "green_field", "acceptance_criteria", "business_tests", "commit_exclude", "models",
              "reference_docs", "reference_skills")

SCALAR_FIELDS = ("title", "repo_path", "description", "user_story")
ENUMS = {
    "mode": ("hitl", "auto"),
    "task_type": ("implement", "review", "refactor", "security_audit"),
}
BOOL_FIELDS = ("green_field",)

ACCEPTANCE_KEYS = ("criterion", "verify", "derived")
BUSINESS_TEST_KEYS = ("scenario", "config", "expected_results")
REFERENCE_DOC_KEYS = ("path", "skill")

_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*:(?P<rest>.*)$")
_BLOCK_HEADER_RE = re.compile(r"^[|>][+-]?$")


class TaskError(Exception):
    """A malformed task file. The message names the line (when there is one) and the fix."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


def _force_utf8() -> None:
    """Force UTF-8 on this process's streams (a legacy console code page would crash on `--help`)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def _indent_of(raw: str) -> int:
    return len(raw) - len(raw.lstrip(" "))


def _split_key(content: str) -> tuple[str | None, str]:
    """`key: rest` -> (key, rest); ("text", None) when the content is not a mapping entry."""
    match = _KEY_RE.match(content)
    if match is None:
        return None, ""
    return match.group("key"), match.group("rest").strip()


def _strip_comment(text: str) -> str:
    """Drop a trailing `#` comment, keeping a `#` that sits inside a quoted scalar."""
    quote = ""
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i:i + 2])
                i += 2
                continue
            if char == quote:
                quote = ""
            out.append(char)
            i += 1
            continue
        if char in "\"'":
            quote = char
            out.append(char)
            i += 1
            continue
        if char == "#" and (i == 0 or text[i - 1] in " \t"):
            break
        out.append(char)
        i += 1
    return "".join(out).rstrip()


def _scalar(text: str, line: int | None = None) -> str:
    """One scalar value: quoted (with escapes) or plain. Nothing else is rewritten.

    A quoted scalar must be CLOSED on the same line: `"unterminated` is an authoring error naming
    the line, never text that silently keeps its opening quote (the pre-fix fallback returned it
    unchanged, so a malformed owner input entered every later stage). A double-quoted value must
    also be valid JSON-escaped text — an invalid escape is an error, not a stripped quote.
    """
    text = text.strip()
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"'):
            raise TaskError(
                f"broken double-quoted scalar {text!r} — a quoted value must END with its closing "
                f"quote on this line, so this one is unterminated or followed by extra text; close "
                f"it ('\"<text>\"') or write the text without quotes", line)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise TaskError(
                f"invalid double-quoted scalar {text!r}: {exc} — inside double quotes use a valid "
                f"escape ('\\\"', '\\\\', '\\n', '\\t' ...) or drop the quotes and write plain "
                f"text", line) from None
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise TaskError(
                f"broken single-quoted scalar {text!r} — a quoted value must END with its closing "
                f"quote on this line, so this one is unterminated or followed by extra text; close "
                f"it (\"'<text>'\") or write the text without quotes", line)
        return text[1:-1].replace("''", "'")
    return text


def _fold(lines: list[str]) -> str:
    """Fold a `>` block: consecutive lines join with a space, an empty line becomes a newline."""
    out: list[str] = []
    after_blank = True
    for line in lines:
        if not line.strip():
            out.append("\n")
            after_blank = True
            continue
        if not after_blank:
            out.append(" ")
        out.append(line.strip())
        after_blank = False
    return "".join(out)


def _missing_value(key: str, line: int | None) -> TaskError:
    """The one message every "key without a value" case shares: the shape and the fix."""
    if key == "criterion":
        return TaskError("'criterion' item is missing a value — write '- criterion: <text>' or a "
                         "block scalar '- criterion: |' followed by indented lines", line)
    return TaskError(f"'{key}' has no value — write '{key}: <text>' on the same line, or a block "
                     f"scalar '{key}: |' followed by indented lines", line)


class TaskParser:
    """Recursive reader for the scoped task schema (one instance per file, no global state)."""

    def __init__(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.lines = normalized.split("\n")
        # `split` yields one empty element AFTER a terminal newline — that element is a split
        # artifact, not a line of the file. Counting it as a line would add a phantom trailing
        # blank line to a keep-chomp (`|+`) block scalar that ends the file.
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
        self.index = 0
        self.lines_of: dict[str, int] = {}

    # -- low level --------------------------------------------------------------------
    def _content(self, i: int) -> tuple[int, str] | None:
        """(indent, content) of line `i`, or None for a blank / comment-only line."""
        raw = self.lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            return None
        lead = raw[:len(raw) - len(raw.lstrip())]
        if "\t" in lead:
            raise TaskError("a tab character in the indentation — this format is space-indented "
                            "(2 spaces per nesting level); replace the tab with spaces", i + 1)
        indent = len(lead)
        content = _strip_comment(raw[indent:])
        if not content.strip():
            return None
        return indent, content

    def _skip(self, i: int) -> int:
        """Index of the next content line at or after `i` (may be past the end)."""
        while i < len(self.lines):
            if self._content(i) is not None:
                return i
            i += 1
        return i

    # -- values -----------------------------------------------------------------------
    def _value_after_key(self, key: str, key_column: int, rest: str, line: int) -> str:
        """The text of `key:`: inline, a block scalar, or an indented text block."""
        if rest:
            if rest[0] in "|>":
                if _BLOCK_HEADER_RE.match(rest) is None:
                    raise TaskError(
                        f"invalid block scalar header {rest!r} — use '|' (literal, line breaks "
                        f"kept) or '>' (folded), optionally with '-' or '+' (e.g. '|-')", line)
                return self._block_scalar(key_column, rest, line)
            return _scalar(rest, line)
        nxt = self._skip(self.index)
        if nxt < len(self.lines):
            indent, content = self._content(nxt)          # type: ignore[misc]
            if indent > key_column:
                return self._text_block(key_column, content)
        raise _missing_value(key, line)

    def _block_scalar(self, key_column: int, header: str, line: int) -> str:
        """One block scalar with YAML chomping: `-` strip, none clip, `+` keep.

        `|-` ends with no newline, `|` (clip) ends with exactly one, `|+` (keep) keeps every
        trailing blank line of the block. LEADING and interior blank lines are content in every
        form, so a body that starts with blank lines keeps them verbatim; only the block's trailing
        blank lines are the chomping input. The block indentation is taken from the first
        NON-blank line, exactly like YAML. Both literal (`|`) and folded (`>`) bodies follow the
        same rule.
        """
        style, chomp = header[0], header[1:2]
        body: list[str] = []
        base: int | None = None
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            if not raw.strip():
                body.append("")              # a blank line is content, leading ones included
                self.index += 1
                continue
            indent = _indent_of(raw)
            if indent <= key_column:
                break
            if base is None:
                base = indent                # indentation comes from the first NON-blank line
            elif indent < base:
                raise TaskError(
                    f"inconsistent indentation inside the block scalar that starts on line "
                    f"{line}: this line is indented by {indent} space(s), but the block body "
                    f"starts at column {base} — indent every line of the block by at least "
                    f"{base} spaces", self.index + 1)
            body.append(raw[base:])
            self.index += 1
        trailing = 0                         # blank lines at the END: the chomping input
        while body and body[-1] == "":
            body.pop()
            trailing += 1
        text = "\n".join(body) if style == "|" else _fold(body)
        if not body:
            return "\n" * trailing if chomp == "+" else ""
        if chomp == "-":                     # strip: no trailing newline at all
            return text
        if chomp == "+":                     # keep: the line break + every trailing blank line
            return text + "\n" * (1 + trailing)
        return text + "\n"                   # clip: exactly one trailing newline

    def _text_block(self, key_column: int, first_content: str) -> str:
        """A key with no inline value and an indented block: same text, plain multi-line shape."""
        collected: list[str] = []
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            if not raw.strip():
                collected.append("")
                self.index += 1
                continue
            if _indent_of(raw) <= key_column:
                break
            collected.append(raw)
            self.index += 1
        while collected and collected[-1] == "":
            collected.pop()
        indents = [_indent_of(line) for line in collected if line.strip()]
        base = min(indents) if indents else 0
        dedented = [line[base:] if line.strip() else "" for line in collected]
        return _fold(dedented).strip()

    # -- collections ------------------------------------------------------------------
    def _mapping_items(self, parent_indent: int, field: str,
                       allowed: tuple[str, ...], required: tuple[str, ...]) -> list[dict]:
        items: list[dict] = []
        item_indent: int | None = None
        while True:
            i = self._skip(self.index)
            if i >= len(self.lines):
                break
            indent, content = self._content(i)             # type: ignore[misc]
            if indent < parent_indent or (indent == parent_indent
                                          and not (content == "-" or content.startswith("- "))):
                break
            if not (content == "-" or content.startswith("- ")):
                raise TaskError(
                    f"expected a list item starting with '- ' under '{field}:' but found "
                    f"{content!r} — every entry of this list is written as "
                    f"'- {allowed[0]}: <text>'", i + 1)
            if item_indent is None:
                item_indent = indent
            elif indent != item_indent:
                raise TaskError(
                    f"inconsistent indentation: this list item starts at column {indent}, but "
                    f"the items of '{field}:' start at column {item_indent} — align every '- ' "
                    f"item of this list (2 spaces per nesting level)", i + 1)
            self.index = i + 1
            body = content[1:].strip()
            items.append(self._one_item(field, allowed, required, i + 1, indent, body))
        return items

    def _one_item(self, field: str, allowed: tuple[str, ...], required: tuple[str, ...],
                  line: int, dash_indent: int, body: str) -> dict:
        if not body:
            raise TaskError(
                f"empty list item — write '- {allowed[0]}: <text>' on this line, or put the keys "
                f"of the item on the following lines indented by {dash_indent + 2} spaces", line)
        if body[0] in "\"'":
            return self._plain_item(field, allowed, body, line)
        key, rest = _split_key(body)
        if key is None:
            return self._plain_item(field, allowed, body, line)
        key_column = dash_indent + 2
        item_line = line                        # the '- ' line: the anchor of every item error
        item: dict[str, object] = {}
        while True:
            if key not in allowed:
                raise TaskError(
                    f"unknown key '{key}' in an item of '{field}:' — allowed keys are: "
                    f"{', '.join(allowed)}", line)
            if key in item:
                raise TaskError(
                    f"duplicate key '{key}' in this item of '{field}:' — each key appears once per "
                    f"item", line)
            item[key] = self._value_after_key(key, key_column, rest, line)
            if key == "derived" and str(item[key]).strip().lower() not in ("true", "false"):
                raise TaskError(
                    f"'derived' takes 'true' or 'false', not {item[key]!r} — write "
                    f"'derived: true' for a criterion derived from other artifacts, or "
                    f"'derived: false' (the default) for a real acceptance criterion", line)
            nxt = self._skip(self.index)
            if nxt >= len(self.lines):
                break
            indent, content = self._content(nxt)           # type: ignore[misc]
            if indent <= dash_indent:
                break
            if indent != key_column:
                raise TaskError(
                    f"inconsistent indentation: the keys of this item of '{field}:' start at column "
                    f"{key_column}, but this line starts at column {indent} — indent it with "
                    f"{key_column} spaces (2 per nesting level)", nxt + 1)
            key, rest = _split_key(content)
            if key is None:
                raise TaskError(
                    f"expected '<key>: <value>' in this item of '{field}:' but found {content!r} — "
                    f"allowed keys are: {', '.join(allowed)}", nxt + 1)
            self.index = nxt + 1
            line = nxt + 1
        for name in required:
            if not str(item.get(name, "")).strip():
                if name in item:
                    raise TaskError(f"'{name}' in this item of '{field}:' is empty — write "
                                    f"'{name}: <text>'", item_line)
                raise TaskError(
                    f"'criterion' item is missing a value — write '- criterion: <text>' or a "
                    f"block scalar '- criterion: |' followed by indented lines"
                    if name == "criterion" else
                    f"this item of '{field}:' is missing the required key '{name}' — write "
                    f"'- {name}: <text>'", item_line)
        return item

    def _plain_item(self, field: str, allowed: tuple[str, ...], body: str,
                    line: int) -> dict:
        text = _scalar(body, line)
        if field != "acceptance_criteria":
            raise TaskError(
                f"an item of '{field}:' must be a mapping with the keys "
                f"{', '.join(allowed)} — write "
                f"'- {allowed[0]}: <text>' (a bare string item is only valid under "
                f"'acceptance_criteria:')", line)
        if not text.strip():
            raise TaskError("this list item is empty — write '- <criterion text>' or "
                            "'- criterion: <text>'", line)
        return {"criterion": text}

    def _string_list(self, parent_indent: int, field: str) -> list[str]:
        values: list[str] = []
        item_indent: int | None = None
        while True:
            i = self._skip(self.index)
            if i >= len(self.lines):
                break
            indent, content = self._content(i)             # type: ignore[misc]
            if indent < parent_indent or (indent == parent_indent
                                          and not content.startswith("-")):
                break
            if not (content == "-" or content.startswith("- ")):
                raise TaskError(
                    f"expected a list item starting with '- ' under '{field}:' but found "
                    f"{content!r} — every entry of this list is a plain string "
                    f"('- \"<text>\"')", i + 1)
            if item_indent is None:
                item_indent = indent
            elif indent != item_indent:
                raise TaskError(
                    f"inconsistent indentation: this list item starts at column {indent}, but "
                    f"the items of '{field}:' start at column {item_indent} — align every '- ' "
                    f"item of this list (2 spaces per nesting level)", i + 1)
            body = content[1:].strip()
            if not body:
                raise TaskError(f"this item of '{field}:' is empty — write '- \"<text>\"'", i + 1)
            key, _rest = _split_key(body)
            if key is not None and body[0] not in "\"'":
                raise TaskError(
                    f"a '{field}:' entry is a plain string, not a mapping — write '- \"<text>\"' "
                    f"instead of '- {body}:'", i + 1)
            values.append(_scalar(body, i + 1))
            self.index = i + 1
        return values

    def _mapping(self, parent_indent: int, field: str, key_hint: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        entry_indent: int | None = None
        while True:
            i = self._skip(self.index)
            if i >= len(self.lines):
                break
            indent, content = self._content(i)             # type: ignore[misc]
            if indent <= parent_indent:
                break
            if entry_indent is None:
                entry_indent = indent
            elif indent != entry_indent:
                raise TaskError(
                    f"inconsistent indentation: the entries of '{field}:' start at column "
                    f"{entry_indent}, but this line starts at column {indent} — indent it with "
                    f"{entry_indent} spaces (2 per nesting level)", i + 1)
            key, rest = _split_key(content)
            if key is None:
                raise TaskError(f"expected '{key_hint}: <value>' under '{field}:' but found "
                                f"{content!r}", i + 1)
            if key in mapping:
                raise TaskError(f"duplicate '{field}:' entry '{key}' — each entry appears once",
                                i + 1)
            self.index = i + 1
            mapping[key] = self._value_after_key(key, indent, rest, i + 1)
        return mapping

    # -- top level --------------------------------------------------------------------
    def parse(self) -> tuple[dict, list[str]]:
        data: dict[str, object] = {}
        warnings: list[str] = []
        while True:
            i = self._skip(self.index)
            if i >= len(self.lines):
                break
            indent, content = self._content(i)             # type: ignore[misc]
            if indent != 0:
                raise TaskError(
                    f"unexpected indentation ({indent} space(s)): this line does not belong to "
                    f"any field — top-level fields start at column 0 and a nested line needs the "
                    f"parent key above it (2 spaces per nesting level)", i + 1)
            key, rest = _split_key(content)
            if key is None:
                raise TaskError(f"expected '<key>: <value>' at the top level but found "
                                f"{content!r} — the documented fields are: "
                                f"{', '.join(TOP_FIELDS)}", i + 1)
            if key in data or key in self.lines_of:
                raise TaskError(f"duplicate top-level field '{key}' — each field appears once "
                                f"in a task file", i + 1)
            self.index = i + 1
            line = i + 1
            if key not in TOP_FIELDS:
                warnings.append(f"line {line}: unknown task field '{key}' — ignored (the "
                                f"documented fields are: {', '.join(TOP_FIELDS)})")
                if rest:
                    self._value_after_key(key, 0, rest, line)   # consume it, value discarded
                else:
                    self._text_block(0, "")
                continue
            self.lines_of[key] = line
            data[key] = self._top_value(key, rest, line)
        self._validate(data)
        return data, warnings

    def _top_value(self, key: str, rest: str, line: int) -> object:
        if key in SCALAR_FIELDS or key in ENUMS or key in BOOL_FIELDS:
            value = self._value_after_key(key, 0, rest, line)
            if key in ENUMS and value not in ENUMS[key]:
                raise TaskError(f"unknown {key} value {value!r} — allowed values are: "
                                f"{', '.join(ENUMS[key])}", line)
            if key in BOOL_FIELDS:
                if value not in ("true", "false"):
                    raise TaskError(f"'{key}' takes 'true' or 'false', not {value!r}", line)
                return value == "true"
            return value
        if rest:
            raise TaskError(f"'{key}:' starts a block and takes no inline value — leave the line "
                            f"as '{key}:' and indent its entries below it", line)
        if key == "acceptance_criteria":
            return self._mapping_items(0, key, ACCEPTANCE_KEYS, ("criterion",))
        if key == "business_tests":
            return self._business_tests(0)
        if key == "reference_docs":
            return self._mapping_items(0, key, REFERENCE_DOC_KEYS, ("path",))
        if key in ("commit_exclude", "reference_skills"):
            return self._string_list(0, key)
        return self._mapping(0, "models", "role")

    def _business_tests(self, parent_indent: int) -> list[dict]:
        items = self._mapping_items(parent_indent, "business_tests", BUSINESS_TEST_KEYS, ())
        for item in items:
            if not any(str(value).strip() for value in item.values()):
                raise TaskError(
                    f"a 'business_tests:' item has no value at all — write '- scenario: <text>' "
                    f"with at least one of: {', '.join(BUSINESS_TEST_KEYS)}", None)
        return items

    def _validate(self, data: dict) -> None:
        if not str(data.get("title", "")).strip():
            raise TaskError(
                "missing required field 'title' — add a top-level line 'title: <short business "
                "goal>' (documented fields: " + ", ".join(TOP_FIELDS) + ")", None)
        if not str(data.get("repo_path", "")).strip() and not data.get("green_field"):
            raise TaskError(
                "missing required field 'repo_path' — add 'repo_path: <path to the project>' at "
                "the top level (relative to the launch directory or absolute), or "
                "'green_field: true' for a brand-new project created in place", None)


def parse_text(text: str) -> tuple[dict, list[str]]:
    """Parse task text -> (raw task, warnings). Raises TaskError naming the line and the fix."""
    return TaskParser(text).parse()


def parse_file(path: str | Path) -> tuple[dict, list[str]]:
    """Read (CRLF-tolerant, UTF-8) and parse a task file. Raises TaskError / OSError."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TaskError(f"the file is not valid UTF-8 ({exc.reason} at byte {exc.start}) — save "
                        f"the task file as UTF-8") from None
    return parse_text(text)


def normalize(task: dict) -> dict:
    """The normalized task document: every documented field present, every text verbatim."""
    return {
        "title": task["title"],
        "repo_path": task.get("repo_path") or None,
        "description": task.get("description"),
        "user_story": task.get("user_story"),
        "mode": task.get("mode", "hitl"),
        "task_type": task.get("task_type", "implement"),
        "green_field": bool(task.get("green_field", False)),
        "acceptance_criteria": [
            {"criterion": item["criterion"], "verify": item.get("verify"),
             "derived": str(item.get("derived", "")).strip().lower() == "true"}
            for item in task.get("acceptance_criteria", [])
        ],
        "business_tests": [
            {"scenario": item.get("scenario"), "config": item.get("config"),
             "expected_results": item.get("expected_results")}
            for item in task.get("business_tests", [])
        ],
        "commit_exclude": list(task.get("commit_exclude", [])),
        "models": dict(task.get("models", {})),
        "reference_docs": [{"path": item["path"], "skill": item.get("skill")}
                           for item in task.get("reference_docs", [])],
        "reference_skills": list(task.get("reference_skills", [])),
    }


def cmd_parse(args: argparse.Namespace) -> int:
    path = Path(args.task)
    try:
        task, warnings = parse_file(path)
    except OSError as exc:
        print(f"error: cannot read task file {str(path)!r}: {exc.strerror or exc} — check the "
              f"path (a task file is readable plain UTF-8 text)", file=sys.stderr)
        return 2
    except TaskError as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                       # never a traceback, whatever the input is
        print(f"error: {path}: cannot parse this task file: {exc} — check its indentation "
              f"against the documented task schema", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"warning: {path}: {warning}", file=sys.stderr)
    document = normalize(task)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        try:
            target = Path(args.out)
            with open(target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        except OSError as exc:
            print(f"error: cannot write {str(args.out)!r}: {exc.strerror or exc} — give a "
                  f"writable path or drop --out", file=sys.stderr)
            return 2
    title = " ".join(str(document["title"]).split())
    if len(title) > 60:
        title = title[:57] + "..."
    print(f"ok: {path}: title={title!r} mode={document['mode']} "
          f"task_type={document['task_type']} "
          f"acceptance_criteria={len(document['acceptance_criteria'])} "
          f"business_tests={len(document['business_tests'])} "
          f"models={len(document['models'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="task_parser.py",
        description="Deterministic parser for the Code Factory task file (documented schema only).")
    sub = parser.add_subparsers(dest="command", required=True)
    parse = sub.add_parser(
        "parse", help="parse a task file, print a one-line summary and optionally write JSON",
        description="Parse <task>, print one summary line, and with --out write the normalized "
                    "task as JSON (all texts verbatim). Exit 2 with an actionable message on a "
                    "malformed task file.")
    parse.add_argument("--task", required=True, metavar="FILE", help="path to the task YAML file")
    parse.add_argument("--out", metavar="JSON",
                       help="write the normalized task as JSON to this path")
    parse.set_defaults(func=cmd_parse)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
