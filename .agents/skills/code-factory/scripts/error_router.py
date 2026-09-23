#!/usr/bin/env python3
"""
Deterministic error router (stdlib only, zero LLM tokens) for the routing tables of
`references/error-routing.md`.

`references/error-patterns.default.json` is the machine-readable snapshot of those tables: section 1
rows 1-20 (`patterns`) and section 1.1 provider rows A-F (`provider_patterns`), each entry
`{id, category, patterns[], route}`. The ARRAY ORDER IS THE PRIORITY ("first match wins") and every
regex is matched case-insensitively. A project LEARNS its own patterns in
`.code-factory/state/error-patterns.json`: they are merged PROJECT-FIRST over the defaults
(deduplicated by id, the project wins), so a learned pattern overrides a built-in one and a partial
project file never loses the built-in patterns.

Usage:
  python error_router.py classify --log <file> [--project-patterns <json>] [--repo <root>]
  python error_router.py merge --project <json> [--out <path>]
  python error_router.py export-defaults [--out <path>] [--repo <root>]

`classify` prints one `key: value` line per field:

  log: <path>
  patterns: <project file> + <default file>     (or just <default file>)
  category: <category>                          (`unmatched` when nothing matched)
  route: <role>                                 (`diagnostician` when nothing matched)
  pattern_id: <id>                              (`-` when nothing matched)
  matched: <regex>                              (`-` when nothing matched)

`merge` writes the project-first union as a complete, valid JSON document — byte-deterministic and
idempotent — both to `--out` (default: the project file itself) and to stdout. `export-defaults`
copies the default snapshot verbatim: the starter file for a project.

Regexes are compiled with re.IGNORECASE (the tables are case-insensitive) and re.MULTILINE, so
line-anchored patterns such as `^error: ` keep their meaning inside a multi-line log.

Match order is section-1 rows 1-20 first, then section-1.1 provider rows A-F: that is the document's
own order, and it keeps every non-provider log classified as before (e.g. `expected 500 but got 502`
stays WRONG_RESULTS instead of being caught by the provider pattern `5\\d\\d`).

Exit codes: 0 = classified / merged / exported; 1 = the log cannot be read; 2 = the patterns JSON is
unusable (broken JSON, missing keys, wrong types, invalid regex) or the CLI was called wrongly.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
DEFAULT_PATTERNS = SCRIPTS.parent / "references" / "error-patterns.default.json"
PROJECT_RELATIVE = pathlib.Path(".code-factory") / "state" / "error-patterns.json"

# Array order is the priority; both groups are concatenated in this order.
GROUPS = ("patterns", "provider_patterns")
DOC_KEYS = ("version", "patterns", "provider_patterns", "retry_budgets")
ENTRY_KEYS = ("id", "category", "patterns", "route")
BUDGETS_KEY = "retry_budgets"
FLAGS = re.IGNORECASE | re.MULTILINE

# The table's row 20 ("UNKNOWN — no pattern matched") is what an unmatched log falls through to.
UNMATCHED_CATEGORY = "unmatched"
UNMATCHED_ROUTE = "diagnostician"


class PatternError(Exception):
    """A patterns document is unusable — report it and exit 2."""


_COMPILED: dict[str, re.Pattern[str]] = {}


def compile_pattern(pattern: str, origin: str) -> re.Pattern[str]:
    """Compile (and cache) one pattern; a broken regex names its origin."""
    cached = _COMPILED.get(pattern)
    if cached is not None:
        return cached
    try:
        regex = re.compile(pattern, FLAGS)
    except re.error as exc:
        raise PatternError(f"{origin}: invalid regex {pattern!r}: {exc}") from exc
    _COMPILED[pattern] = regex
    return regex


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_entries(entries: object, origin: str, key: str) -> list[dict]:
    """Normalized `{id, category, patterns, route}` entries; duplicate ids keep the first one."""
    if not isinstance(entries, list):
        raise PatternError(f"{origin}: {key} must be a list")
    out: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{origin}: {key}[{index}]"
        if not isinstance(entry, dict):
            raise PatternError(f"{where} must be a JSON object")
        missing = [name for name in ENTRY_KEYS if name not in entry]
        if missing:
            raise PatternError(f"{where} is missing key(s): {', '.join(missing)}")
        if not _nonempty_str(entry["id"]):
            raise PatternError(f"{where}.id must be a non-empty string")
        if not _nonempty_str(entry["category"]):
            raise PatternError(f"{where}.category must be a non-empty string")
        if not _nonempty_str(entry["route"]):
            raise PatternError(f"{where}.route must be a non-empty string")
        patterns = entry["patterns"]
        if not isinstance(patterns, list):
            raise PatternError(f"{where}.patterns must be a list of regex strings")
        # An empty list is legal: the terminal UNKNOWN row (id 20) carries no regex — an
        # unmatched log falls through to the Diagnostician instead.
        for pattern in patterns:
            if not _nonempty_str(pattern):
                raise PatternError(f"{where}.patterns must hold non-empty strings, got {pattern!r}")
            compile_pattern(pattern, f"{where}.patterns")
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        out.append({"id": entry["id"], "category": entry["category"],
                    "patterns": list(patterns), "route": entry["route"]})
    return out


def validate_document(data: object, origin: str, *, require_full: bool) -> dict:
    """Normalized document; `require_full` demands all four top-level keys (the default file)."""
    if not isinstance(data, dict):
        raise PatternError(f"{origin}: top level must be a JSON object, got {type(data).__name__}")
    if require_full:
        missing = [key for key in DOC_KEYS if key not in data]
        if missing:
            raise PatternError(f"{origin}: missing required key(s): {', '.join(missing)}")
    elif not any(key in data for key in DOC_KEYS[1:]):
        raise PatternError(
            f"{origin}: needs at least one of {', '.join(DOC_KEYS[1:])} "
            f"(a project file may be partial, an empty one learns nothing)")
    version = data.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise PatternError(f"{origin}: version must be an integer, got {version!r}")
    doc: dict = {"version": version}
    for key in GROUPS:
        doc[key] = validate_entries(data.get(key, []), origin, key)
    budgets = data.get(BUDGETS_KEY, {})
    if not isinstance(budgets, dict):
        raise PatternError(f"{origin}: {BUDGETS_KEY} must be a JSON object")
    for role, value in budgets.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PatternError(
                f"{origin}: {BUDGETS_KEY}.{role} must be a non-negative integer, got {value!r}")
    doc[BUDGETS_KEY] = dict(budgets)
    return doc


def load_document(path: pathlib.Path, *, require_full: bool) -> dict:
    """Read + validate one patterns document; every failure names the file and the problem."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PatternError(f"cannot read patterns file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PatternError(f"invalid JSON in {path}: {exc}") from exc
    return validate_document(data, str(path), require_full=require_full)


def combine(project: dict | None, default: dict) -> dict:
    """Project-first, id-deduplicated union of a project document over the defaults."""
    if project is None:
        return default
    doc: dict = {"version": project.get("version", default["version"])}
    for key in GROUPS:
        learned = {entry["id"] for entry in project[key]}
        doc[key] = project[key] + [entry for entry in default[key] if entry["id"] not in learned]
    doc[BUDGETS_KEY] = {**default[BUDGETS_KEY], **project[BUDGETS_KEY]}
    return doc


def match_order(doc: dict) -> list[dict]:
    """Every entry in match order: section-1 rows, then section-1.1 provider rows."""
    return [entry for key in GROUPS for entry in doc[key]]


def match_entry(text: str, entries: list[dict]) -> tuple[dict | None, str | None]:
    """First entry (and the regex that matched it) in priority order; (None, None) if none does."""
    for entry in entries:
        for pattern in entry["patterns"]:
            if compile_pattern(pattern, f"pattern {entry['id']}").search(text):
                return entry, pattern
    return None, None


def dumps(doc: dict) -> str:
    """Canonical serialization: stable key/entry order, 2-space indent, LF, trailing newline."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def write_json(path: pathlib.Path, text: str) -> None:
    """Write UTF-8 with LF newlines, whatever the platform's default is."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def project_patterns_path(repo: pathlib.Path) -> pathlib.Path:
    return repo / PROJECT_RELATIVE


def resolve_project(project_arg: str | None, repo_arg: str | None) -> pathlib.Path | None:
    """`--project-patterns` (must exist) else the repo's learned file (may be absent)."""
    if project_arg:
        path = pathlib.Path(project_arg)
        if not path.is_file():
            raise PatternError(f"cannot read project patterns {path}: no such file")
        return path
    repo = pathlib.Path(repo_arg) if repo_arg else pathlib.Path.cwd()
    path = project_patterns_path(repo)
    return path if path.is_file() else None


def cmd_classify(args: argparse.Namespace) -> int:
    default = load_document(DEFAULT_PATTERNS, require_full=True)
    project = resolve_project(args.project_patterns, args.repo)
    if project is None:
        doc, source = default, str(DEFAULT_PATTERNS)
    else:
        doc = combine(load_document(project, require_full=False), default)
        source = f"{project} + {DEFAULT_PATTERNS}"

    log = pathlib.Path(args.log)
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read log {log}: {exc}", file=sys.stderr)
        return 1

    entry, pattern = match_entry(text, match_order(doc))
    lines = [f"log: {log}", f"patterns: {source}"]
    if entry is None:
        lines += [f"category: {UNMATCHED_CATEGORY}", f"route: {UNMATCHED_ROUTE}",
                  "pattern_id: -", "matched: -"]
    else:
        lines += [f"category: {entry['category']}", f"route: {entry['route']}",
                  f"pattern_id: {entry['id']}", f"matched: {pattern}"]
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    default = load_document(DEFAULT_PATTERNS, require_full=True)
    project_path = pathlib.Path(args.project)
    project = load_document(project_path, require_full=False)
    text = dumps(combine(project, default))
    write_json(pathlib.Path(args.out) if args.out else project_path, text)
    sys.stdout.write(text)
    return 0


def cmd_export_defaults(args: argparse.Namespace) -> int:
    try:
        payload = DEFAULT_PATTERNS.read_bytes()
    except OSError as exc:
        raise PatternError(f"cannot read the default patterns {DEFAULT_PATTERNS}: {exc}") from exc
    if args.out:
        out = pathlib.Path(args.out)
    else:
        repo = pathlib.Path(args.repo) if args.repo else pathlib.Path.cwd()
        out = project_patterns_path(repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    classify = sub.add_parser("classify", help="Classify one log file against the patterns")
    classify.add_argument("--log", required=True, help="Log file with the combined error output")
    classify.add_argument("--project-patterns", metavar="JSON", default=None,
                          help="Project-learned patterns file (overrides the repo lookup)")
    classify.add_argument("--repo", metavar="ROOT", default=None,
                          help="Repo root holding .code-factory/state (default: cwd)")
    classify.set_defaults(func=cmd_classify)

    merge = sub.add_parser("merge", help="Merge a project file over the defaults (project-first)")
    merge.add_argument("--project", required=True, help="Project-learned patterns file")
    merge.add_argument("--out", default=None,
                       help="Where to write the merged JSON (default: the project file itself)")
    merge.set_defaults(func=cmd_merge)

    export = sub.add_parser("export-defaults", help="Copy the default snapshot as a starter file")
    export.add_argument("--out", default=None,
                        help="Target path (default: <repo>/.code-factory/state/error-patterns.json)")
    export.add_argument("--repo", metavar="ROOT", default=None,
                        help="Repo root used when --out is omitted (default: cwd)")
    export.set_defaults(func=cmd_export_defaults)
    return ap


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the output survive a legacy console.

    A Windows console defaults to a legacy code page (cp866/cp1251) and both the help text and the
    routed log lines carry non-ASCII characters (the em dash `—`), which that codec cannot encode:
    `print_help()` would raise UnicodeEncodeError and the user would get a traceback instead of
    the help, and a classification could be lost the same way. `errors="replace"` keeps a stream
    that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PatternError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
