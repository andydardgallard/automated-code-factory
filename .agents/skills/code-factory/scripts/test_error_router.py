#!/usr/bin/env python3
"""
Deterministic self-test for `error_router.py` (zero LLM tokens, stdlib only).

`references/error-patterns.default.json` is the snapshot of the routing tables of
`references/error-routing.md` (§1 rows 1-20 + §1.1 provider rows A-F); the router classifies a log
against them in array order ("first match wins") and lets a project override patterns through
`.code-factory/state/error-patterns.json` (project-first merge, deduplicated by id).

Covered here: the snapshot's shape and order (ids 1-20 + the browser/MCP infrastructure rows
I1-I4 + A-F, categories, routes, retry budgets),
sample logs from the tables (WRONG_RESULTS must win over the generic assertion/compile rows, a
provider `401` line is PROVIDER_AUTH), the unmatched fallback (diagnostician), the default+project
merge (a learned pattern is tried first, the built-in rows it never touches stay live, the override
of a built-in id wins), the silent default-only mode when no learned file exists, the tolerated
broken AUTO-DISCOVERED learned file (warning on stderr + fallback to the defaults, exit 0) versus
the hard error (exit 2) when the very same file is named with `--project-patterns`, deterministic
and idempotent `merge` output, `export-defaults` as a byte-exact starter, the exit-code contract
(2 for an unusable patterns JSON, 1 for an unreadable log), the OPTIONAL `--repo` anchor — a
RELATIVE `--log` / patterns file / `--out` resolves against it, an absolute path never does —
the EQUALITY OF PATH SPELLINGS (two spellings of one file — a non-ASCII/8.3 short-name base,
simulated — compare as one path through `realpath`+`normcase`, never as raw strings), the
PROBE-WORDING regression (the missing-node line the Web GUI probe ACTUALLY emits is rendered from
`chrome_devtools_mcp.py` itself, never hand-copied, and must classify as row I1) plus the
stdlib-only import contract.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import ast
import ctypes
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import error_router as er

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "error_router.py"
DEFAULT = SCRIPTS.parent / "references" / "error-patterns.default.json"
PROBE = SCRIPTS / "chrome_devtools_mcp.py"     # the Web GUI probe (read-only here)

# The invariant wording of the probe's missing-tool line — the tail that separates it from the
# installer's own `{name} was not found on PATH` message further up the same file. Both are in the
# probe, only this one carries the Web GUI run consequence.
PROBE_MISSING_TOOL_MARKER = "was not found on PATH; a Web GUI run cannot start the "


def render_probe_fstring(node: ast.JoinedStr, values: dict[str, str]) -> str | None:
    """Render one f-string literal of the probe; None when it needs a value the caller did not give."""
    parts: list[str] = []
    for part in node.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif isinstance(part, ast.FormattedValue):
            key = ast.unparse(part.value)             # `name`, `SERVER_NAME`, ...
            if key not in values:
                return None
            parts.append(values[key])
        else:
            return None
    return "".join(parts)


def probe_missing_tool_message(tool: str = "node") -> str:
    """The EXACT line the Web GUI probe emits when `tool` is missing — parsed, never hand-copied.

    The wording is read out of the probe's own source (`probe_capabilities` of
    `scripts/chrome_devtools_mcp.py`) and rendered with a real tool name plus the probe's own
    `SERVER_NAME`, so this regression cannot drift from what the probe actually prints: an edit of the
    probe's message re-renders the sample here, and the routing table has to keep up with it.
    """
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    consts: dict[str, str] = {}
    for node in tree.body:                            # module-level constants only (`SERVER_NAME`)
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
    values = {**consts, "name": tool}
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = render_probe_fstring(node, values)
            if text and PROBE_MISSING_TOOL_MARKER in text:
                return text
    raise AssertionError(f"no f-string with {PROBE_MISSING_TOOL_MARKER!r} in {PROBE}")


# §1 rows 1-20 plus the browser/MCP infrastructure rows I1-I4, in table (match) order:
# id, category, route to. I1-I4 sit between rows 4 and 5 ON PURPOSE — that position is what keeps a
# browser capability line from being stolen by the generic `command not found` / `file not found`
# rows (see the Notes of §1 in references/error-routing.md).
EXPECTED = [
    ("1", "MISSING_INPUT", "human"),
    ("2", "WRONG_RESULTS", "diagnostician"),
    ("3", "INFRASTRUCTURE", "infrastructure"),
    ("4", "INFRASTRUCTURE", "infrastructure"),
    ("I1", "BROWSER_TOOLCHAIN", "infrastructure"),
    ("I2", "BROWSER_MISSING", "infrastructure"),
    ("I3", "MCP_STARTUP", "infrastructure"),
    ("I4", "CHROME_DEVTOOLS_MCP", "infrastructure"),
    ("5", "MISSING_FILE", "ba"),
    ("6", "MISSING_FILE", "ba"),
    ("7", "BAD_COMMAND", "planner"),
    ("8", "COMPILE_ERROR", "coder"),
    ("9", "COMPILE_ERROR", "coder"),
    ("10", "COMPILE_ERROR", "coder"),
    ("11", "COMPILE_ERROR", "coder"),
    ("12", "COMPILE_ERROR", "coder"),
    ("13", "LINK_ERROR", "coder"),
    ("14", "DEPENDENCY", "infrastructure"),
    ("15", "PERMISSION", "human"),
    ("16", "TIMEOUT", "planner"),
    ("17", "TIMEOUT", "coder"),
    ("18", "RUNTIME_CRASH", "coder"),
    ("19", "ASSERTION", "coder"),
    ("20", "UNKNOWN", "diagnostician"),
]
# §1.1 provider rows A-F, in table order.
EXPECTED_PROVIDERS = [
    ("A", "PROVIDER_AUTH", "infrastructure"),
    ("B", "PROVIDER_AUTH", "infrastructure"),
    ("C", "PROVIDER_RATE", "infrastructure"),
    ("D", "PROVIDER_MODEL", "planner"),
    ("E", "PROVIDER_UPSTREAM", "infrastructure"),
    ("F", "PROVIDER_FORMAT", "planner"),
]
BUDGETS = {"coder": 1, "ba": 2, "planner": 2, "diagnostician": 1, "advisor": 1,
           "infrastructure": 3, "reviewer": 2}

# A log line -> the row of §1/§1.1 that must classify it.
SAMPLES = [
    ("ModuleNotFoundError: No module named 'x'", "6", "MISSING_FILE", "ba"),
    ("AssertionError: expected 5 but got 7", "2", "WRONG_RESULTS", "diagnostician"),
    ("error: cannot find value `x` in this scope", "8", "COMPILE_ERROR", "coder"),
    ("Task file not found: task.yaml", "1", "MISSING_INPUT", "human"),
    ("Auto-merging a.py\nMerge conflict in target/debug/x", "3", "INFRASTRUCTURE",
     "infrastructure"),
    ("Permissions of x: operation not permitted", "15", "PERMISSION", "human"),
    ("bash: run.sh: command not found", "7", "BAD_COMMAND", "planner"),
    ("Segmentation fault (core dumped)", "18", "RUNTIME_CRASH", "coder"),
    ("test_x FAILED: 1 != 2", "19", "ASSERTION", "coder"),
    ("cargo: could not compile `bar`: dependency failed", "14", "DEPENDENCY", "infrastructure"),
    ("HTTP 429: rate limit exceeded", "C", "PROVIDER_RATE", "infrastructure"),
    # Browser/MCP INFRASTRUCTURE rows (§1 rows I1-I4): a missing capability is an environment
    # problem, not a code problem. It must never be swallowed by the generic BAD_COMMAND/MISSING_FILE
    # rows, and it never reaches the coder — the coder route stays the ONLY implementation route.
    ("bash: npx: command not found", "I1", "BROWSER_TOOLCHAIN", "infrastructure"),
    ("'npm' is not recognized as an internal or external command", "I1", "BROWSER_TOOLCHAIN",
     "infrastructure"),
    ("Google Chrome was not found; install Chrome for Testing", "I2", "BROWSER_MISSING",
     "infrastructure"),
    ("MCP server 'chrome-devtools' failed to start", "I3", "MCP_STARTUP", "infrastructure"),
    ("npx chrome-devtools-mcp@1.11.0 exited with code 1", "I4", "CHROME_DEVTOOLS_MCP",
     "infrastructure"),
    # The line the Web GUI probe ACTUALLY emits for a missing tool, rendered from the probe's own
    # f-string above (never a hand-written lookalike). A missing Node is an environment problem: row
    # I1 has to match this exact wording, otherwise a real missing-Node run falls through to UNKNOWN
    # and the DIAGNOSTICIAN is dispatched instead of the INFRASTRUCTURE role.
    (probe_missing_tool_message(), "I1", "BROWSER_TOOLCHAIN", "infrastructure"),
    # A GUI implementation/test FAILURE is not infrastructure: it keeps the existing ASSERTION/coder
    # route, because no GUI-specific pattern was added.
    ("AssertionError: the submit button did not call the handler", "19", "ASSERTION", "coder"),
]
UNMATCHED_LOG = "everything is fine here\n0 failed\n"


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def canonical_path(path: str | pathlib.Path) -> str:
    """One canonical spelling of a path: 8.3 short names, case, separators and `.` all fold.

    Every path assertion here compares a spelling the test built itself with a spelling the tool
    reported. On a machine whose user name is not ASCII those two are different SPELLINGS of one
    file (the 8.3 short name against the full Unicode form), so the comparison resolves both sides
    through `realpath` (short names, symlinks, `.`/`..`) and folds case and separators with
    `normcase` where the platform is case-insensitive. A verbatim string comparison of the two
    spellings is the bug this suite regressed on.
    """
    real = os.path.realpath(os.fspath(path))
    return os.path.normcase(real) if os.name == "nt" else real


def expect_same_path(actual: str | pathlib.Path, expected: str | pathlib.Path, msg: str) -> None:
    """Assert two spellings name ONE path — the equality every path assertion in this suite needs."""
    expect(canonical_path(actual) == canonical_path(expected),
           f"{msg}: {actual!r} and {expected!r} are not the same path "
           f"(canonical: {canonical_path(actual)!r} != {canonical_path(expected)!r})")


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the tool and decode its streams as UTF-8.

    `error_router.py` forces UTF-8 on its own output, so the LOCALE code page (a legacy one on a
    machine with a non-ASCII code page) must never be used to decode it: that would mangle exactly
    the non-ASCII paths these assertions compare.
    """
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=cwd)


def field(stdout: str, key: str) -> str:
    """Value of one `key: value` output line (the value may contain ': ' itself)."""
    for line in stdout.splitlines():
        if line.startswith(f"{key}: "):
            return line[len(key) + 2:]
    raise AssertionError(f"missing field {key!r} in output:\n{stdout}")


def sources_of(stdout: str) -> list[str]:
    """The `patterns:` field split into its path parts: `<project file> + <default file>`."""
    return field(stdout, "patterns").split(" + ")


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def write_json(path: pathlib.Path, payload: object) -> pathlib.Path:
    return write(path, json.dumps(payload, indent=2) + "\n")


_SHORT_PATH_MAX = 4096


def other_spelling(path: pathlib.Path) -> str:
    """A second spelling of the SAME path, as a non-ASCII machine hands it out.

    On a machine whose user name is not ASCII `tempfile` can return the base in its 8.3 short form
    (`C:\\Users\\836D~1\\AppData\\Local\\Temp\\...`) while the tool keeps the full Unicode spelling:
    two character-by-character different strings that name one and the same file. The short form is
    asked from Windows itself (`GetShortPathNameW`); on a volume without 8.3 aliases - and outside
    Windows - a case/separator (Windows) or `.`-segment (POSIX) variant of the same path stands in
    for it, i.e. a different normalization of one path that the OS itself resolves identically.
    """
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(_SHORT_PATH_MAX)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
        if 0 < length < len(buffer) and buffer.value != str(path):
            return buffer.value
        return str(path).replace(os.sep, "/").upper()
    return str(path).replace(os.sep, f"{os.sep}.{os.sep}")


def classify(repo: pathlib.Path, log: pathlib.Path,
             *extra: str) -> subprocess.CompletedProcess[str]:
    return run("classify", "--log", str(log), "--repo", str(repo), *extra)


def main() -> int:
    # 1. The snapshot: shape, table order, routes, budgets and the §1 ordering note.
    doc = er.load_document(DEFAULT, require_full=True)
    expect(doc["version"] == 1, f"version: {doc['version']}")
    got = [(e["id"], e["category"], e["route"]) for e in doc["patterns"]]
    expect(got == EXPECTED, f"§1 rows 1-20 changed (order matters): {got}")
    got_providers = [(e["id"], e["category"], e["route"]) for e in doc["provider_patterns"]]
    expect(got_providers == EXPECTED_PROVIDERS, f"§1.1 provider rows A-F changed: {got_providers}")
    expect(doc["retry_budgets"] == BUDGETS, f"retry budgets: {doc['retry_budgets']}")
    expect(len(er.match_order(doc)) == 30,
           "24 §1 rows (1-20 plus the browser/MCP infrastructure rows I1-I4) + 6 provider rows "
           "must be classified")
    by_id = {entry["id"]: entry for entry in doc["patterns"]}
    expect(doc["patterns"][-1]["patterns"] == [], "the terminal UNKNOWN row carries no regex")
    expect(all(e["patterns"] for e in doc["patterns"][:-1]),
           "every non-terminal row must carry regexes")
    ids = [e["id"] for e in doc["patterns"]]
    # Note in §1: business-result markers may sit inside an assertion message.
    expect(ids.index("2") < ids.index("8") < ids.index("19"),
           "WRONG_RESULTS must be checked before the compile/assertion rows")
    # Rows 16/17 share the same regexes — the "(with 'test' in output)" condition is prose, not a
    # regex, so row 16 shadows row 17 under "first match wins". Pinned here so the shadowing is
    # visible rather than silent (the text update of error-routing.md has to resolve it).
    expect(by_id["16"]["patterns"] == by_id["17"]["patterns"],
           "rows 16 and 17 must still mirror the table's shared pattern cell")
    # Row 8's cell is `error[E\d+]` — a CHARACTER CLASS, so it matches `error4`, not Cargo's
    # `error[E0432]`. Copied verbatim here (the snapshot must not rewrite the table); a project can
    # override id 8 with a learned pattern, and the text update of error-routing.md has to decide.
    expect("error[E\\d+]" in by_id["8"]["patterns"],
           f"row 8 must snapshot the table's regex verbatim: {by_id['8']['patterns']}")
    # Row 18's `Traceback (most recent call last)` keeps its parentheses UNESCAPED (a regex group),
    # so the live alternatives are `Segmentation fault`, `Fatal error`, `panic:` … — same verbatim
    # snapshot policy: the snapshot never rewrites the table, the findings go to the text update.
    expect("Traceback (most recent call last)" in by_id["18"]["patterns"],
           f"row 18 must snapshot the table's regex verbatim: {by_id['18']['patterns']}")
    raw = DEFAULT.read_bytes()
    expect(b"\r" not in raw and raw.endswith(b"}\n"), "the snapshot must be LF-terminated UTF-8")

    # 2. Library classification of the table's error families.
    entries = er.match_order(doc)
    for text, eid, category, route in SAMPLES:
        entry, pattern = er.match_entry(text, entries)
        expect(entry is not None, f"{text!r} must match row {eid}, nothing matched")
        expect(entry["id"] == eid,
               f"{text!r} must match row {eid}, matched row {entry['id']} ({entry['category']})")
        expect(entry["category"] == category and entry["route"] == route,
               f"{text!r}: row {eid} must be {category}/{route}, got "
               f"{entry['category']}/{entry['route']}")
        expect(pattern in entry["patterns"], f"{text!r}: matched regex {pattern!r} not in row {eid}")
    entry, _ = er.match_entry("401", entries)
    expect(entry is not None and (entry["id"], entry["category"], entry["route"])
           == ("A", "PROVIDER_AUTH", "infrastructure"),
           f"a bare provider `401` must be PROVIDER_AUTH/infrastructure, got {entry}")
    entry, pattern = er.match_entry(UNMATCHED_LOG, entries)
    expect(entry is None and pattern is None, f"an unknown log must not match, got {entry}")

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        repo = tmp / "repo"                      # no .code-factory: the default must be used
        logs = tmp / "logs"
        repo.mkdir()
        logs.mkdir()
        mod_log = write(logs / "mod.log", "ModuleNotFoundError: No module named 'x'\n")
        auth_log = write(logs / "auth.log", "provider error: 401 Unauthorized\n")
        calm_log = write(logs / "calm.log", UNMATCHED_LOG)

        # 3. CLI contract + fallback to the default snapshot when the project file is absent.
        res = classify(repo, mod_log)
        expect(res.returncode == 0, f"classify must exit 0: {res.stderr!r}")
        expect_same_path(field(res.stdout, "patterns"), DEFAULT,
                         "the default snapshot must be the source")
        expect(field(res.stdout, "category") == "MISSING_FILE"
               and field(res.stdout, "route") == "ba"
               and field(res.stdout, "pattern_id") == "6"
               and field(res.stdout, "matched") == "ModuleNotFoundError",
               f"ModuleNotFoundError must classify as row 6: {res.stdout!r}")
        res = classify(repo, auth_log)
        expect(res.returncode == 0 and field(res.stdout, "category") == "PROVIDER_AUTH"
               and field(res.stdout, "route") == "infrastructure"
               and field(res.stdout, "pattern_id") == "A",
               f"a 401 log must be PROVIDER_AUTH: {res.stdout!r}")
        res = classify(repo, calm_log)
        expect(res.returncode == 0 and field(res.stdout, "category") == "unmatched"
               and field(res.stdout, "route") == "diagnostician"
               and field(res.stdout, "pattern_id") == "-",
               f"an unknown log must be unmatched/diagnostician at exit 0: {res.stdout!r}")

        # 4. A project-learned pattern outranks the built-in row with the same id, and the learned
        #    pattern of a new id outranks every built-in row (project patterns come first).
        project = repo / ".code-factory" / "state" / "error-patterns.json"
        write_json(project, {
            "version": 1,
            "patterns": [
                {"id": "6", "category": "PROJECT_MISSING_MODULE",
                 "patterns": ["ModuleNotFoundError"], "route": "planner"},
                {"id": "L1", "category": "PROJECT_ASSERTION",
                 "patterns": ["AssertionError"], "route": "infrastructure"},
            ],
            "retry_budgets": {"coder": 5},
        })
        res = classify(repo, mod_log)
        expect(field(res.stdout, "category") == "PROJECT_MISSING_MODULE"
               and field(res.stdout, "route") == "planner"
               and field(res.stdout, "pattern_id") == "6",
               f"the project pattern id 6 must win over the built-in row 6: {res.stdout!r}")
        assert_log = write(logs / "assert.log", "AssertionError: 1 != 2\n")
        res = classify(repo, assert_log)
        expect(field(res.stdout, "category") == "PROJECT_ASSERTION"
               and field(res.stdout, "pattern_id") == "L1",
               f"a learned pattern must be tried before the built-in rows: {res.stdout!r}")
        perm_log = write(logs / "perm.log", "bash: /x: Permission denied\n")
        res = classify(repo, perm_log)
        expect(field(res.stdout, "category") == "PERMISSION"
               and field(res.stdout, "pattern_id") == "15",
               f"a partial project file must not hide the built-in rows: {res.stdout!r}")
        res = classify(repo, auth_log)
        expect(field(res.stdout, "category") == "PROVIDER_AUTH"
               and field(res.stdout, "pattern_id") == "A",
               f"a project file without provider_patterns keeps the provider rows: {res.stdout!r}")

        # 5. --project-patterns overrides the repo lookup; a missing one is a hard error.
        explicit = write_json(tmp / "explicit.json", {
            "patterns": [{"id": "6", "category": "EXPLICIT_MISSING",
                          "patterns": ["ModuleNotFoundError"], "route": "human"}]})
        res = classify(repo, mod_log, "--project-patterns", str(explicit))
        expect(res.returncode == 0 and field(res.stdout, "category") == "EXPLICIT_MISSING"
               and field(res.stdout, "route") == "human"
               and field(res.stdout, "pattern_id") == "6",
               f"--project-patterns must override the repo lookup: {res.stdout!r}")
        res = classify(repo, mod_log, "--project-patterns", str(tmp / "nope.json"))
        expect(res.returncode == 2 and "nope.json" in res.stderr,
               f"a missing --project-patterns must exit 2: {res.returncode} {res.stderr!r}")

        # 6. Without --repo the cwd is the repo root (the documented default).
        res = run("classify", "--log", str(mod_log), cwd=str(repo))
        expect(res.returncode == 0 and field(res.stdout, "category") == "PROJECT_MISSING_MODULE",
               f"the cwd must be the default repo root: {res.stdout!r}")

        # 7. merge: project-first, deduplicated by id, deterministic, idempotent, full JSON.
        out1, out2 = tmp / "m1.json", tmp / "m2.json"
        first = run("merge", "--project", str(project), "--out", str(out1))
        again = run("merge", "--project", str(project), "--out", str(out2))
        expect(first.returncode == 0, f"merge must exit 0: {first.stderr!r}")
        expect(out1.read_bytes() == out2.read_bytes()
               and out1.read_bytes() == first.stdout.encode("utf-8"),
               "two merges of the same input must be byte-identical")
        expect(b"\r" not in out1.read_bytes(), "merged JSON must use LF newlines")
        merged = json.loads(first.stdout)
        er.validate_document(merged, "merged", require_full=True)   # a valid full document
        merged_ids = [e["id"] for e in merged["patterns"]]
        expect(merged_ids[:2] == ["6", "L1"],
               f"project patterns must come first: {merged_ids}")
        expect(merged_ids.count("6") == 1, f"id 6 must be deduplicated: {merged_ids}")
        expect(len(merged_ids) == 25,
               f"2 learned + the 23 untouched defaults were expected: {merged_ids}")
        expect([e["id"] for e in merged["provider_patterns"]] == ["A", "B", "C", "D", "E", "F"],
               "the provider rows must all survive the merge")
        expect(merged["retry_budgets"] == {**BUDGETS, "coder": 5},
               f"the project budget must override the default: {merged['retry_budgets']}")
        expect(merged["patterns"][0]["route"] == "planner",
               "the learned entry must keep its own route")
        # merging an already merged file changes nothing (idempotent).
        third = run("merge", "--project", str(out1))
        expect(third.stdout == first.stdout and out1.read_text(encoding="utf-8") == first.stdout,
               "merge must default to --out <project> and be idempotent")
        # …and merging in place into the repo's learned file keeps classifying the same way.
        inplace = run("merge", "--project", str(project))
        expect(inplace.returncode == 0 and project.read_text(encoding="utf-8") == inplace.stdout,
               f"merge must write back to the project file by default: {inplace.stderr!r}")
        res = classify(repo, assert_log)
        expect(field(res.stdout, "category") == "PROJECT_ASSERTION",
               f"an in-place merged project file must still classify: {res.stdout!r}")

        # 8. export-defaults: a byte-exact starter that classifies like the default.
        exported = tmp / "exported.json"
        res = run("export-defaults", "--out", str(exported))
        expect(res.returncode == 0 and exported.read_bytes() == raw,
               f"export-defaults must copy the snapshot verbatim: {res.stderr!r}")
        res = classify(repo, mod_log, "--project-patterns", str(exported))
        expect(field(res.stdout, "category") == "MISSING_FILE"
               and field(res.stdout, "pattern_id") == "6",
               f"the exported starter must classify like the default: {res.stdout!r}")
        res = run("export-defaults", "--repo", str(tmp / "fresh-repo"))
        landed = tmp / "fresh-repo" / ".code-factory" / "state" / "error-patterns.json"
        expect(res.returncode == 0 and landed.read_bytes() == raw,
               f"an omitted --out must land in <repo>/.code-factory/state: {res.stderr!r}")

        # 9. Unusable patterns JSON -> exit 2, naming the file and the problem (classify and merge).
        bad = [
            ("bad-json.json", "{not json", "invalid JSON"),
            ("bad-top.json", "[1, 2]", "top level must be a JSON object"),
            ("bad-empty.json", "{}", "needs at least one of"),
            ("bad-entry.json", json.dumps({"patterns": [1]}), "must be a JSON object"),
            ("bad-key.json", json.dumps({"patterns": [
                {"id": "x", "category": "C", "patterns": ["a"]}]}), "missing key(s): route"),
            ("bad-regex.json", json.dumps({"patterns": [
                {"id": "x", "category": "C", "patterns": ["("], "route": "coder"}]}),
             "invalid regex"),
            ("bad-list.json", json.dumps({"patterns": {"id": "x"}}), "patterns must be a list"),
            ("bad-id.json", json.dumps({"patterns": [
                {"id": " ", "category": "C", "patterns": [], "route": "coder"}]}),
             "id must be a non-empty string"),
            ("bad-pattern.json", json.dumps({"patterns": [
                {"id": "x", "category": "C", "patterns": [7], "route": "coder"}]}),
             "non-empty strings"),
            ("bad-budget.json", json.dumps({"retry_budgets": {"coder": -1}}),
             "must be a non-negative integer"),
        ]
        for name, text, needle in bad:
            path = write(tmp / name, text)
            res = classify(repo, mod_log, "--project-patterns", str(path))
            expect(res.returncode == 2, f"{name} must exit 2, got {res.returncode} ({res.stderr!r})")
            expect(needle in res.stderr, f"{name}: stderr {res.stderr!r} lacks {needle!r}")
            expect(name in res.stderr, f"{name}: stderr must name the file")
            res = run("merge", "--project", str(path))
            expect(res.returncode == 2 and name in res.stderr,
                   f"{name} must be rejected by merge too: {res.returncode} {res.stderr!r}")

        # 9a. The AUTO-DISCOVERED learned file is not a hard input: a broken one is reported on
        #     stderr and falls back to the default snapshot, so a corrupted learned file can never
        #     take the routing down (exit 0). An explicit --project-patterns stays a hard error
        #     (case 9): the caller asked for that exact file.
        broken_repo = tmp / "repo-broken"
        broken_log = write(logs / "broken.log", "ModuleNotFoundError: No module named 'x'\n")
        learned = broken_repo / ".code-factory" / "state" / "error-patterns.json"
        (broken_repo / ".code-factory" / "state").mkdir(parents=True)   # the dir, no learned file
        res = classify(broken_repo, broken_log)                         # normal mode: defaults only
        expect(res.returncode == 0 and res.stderr == "",
               f"no learned file must classify against the defaults silently: {res.stdout!r} "
               f"{res.stderr!r}")
        expect_same_path(field(res.stdout, "patterns"), DEFAULT,
                         "the default snapshot must be the source without a learned file")
        no_project = res.stdout
        for name, text, needle in bad:              # every unusable shape of the learned file
            write(learned, text)
            res = classify(broken_repo, broken_log)
            expect(res.returncode == 0,
                   f"a broken learned file ({name}) must not fail the run: {res.returncode} "
                   f"{res.stderr!r}")
            expect("warning: ignoring the project-learned patterns" in res.stderr
                   and str(learned) in res.stderr and needle in res.stderr,
                   f"the fallback must name the file and the reason ({name}): {res.stderr!r}")
            expect(res.stdout == no_project,
                   f"the fallback must classify exactly as without a learned file ({name}): "
                   f"{res.stdout!r}")
            res = classify(broken_repo, broken_log, "--project-patterns", str(learned))
            expect(res.returncode == 2 and str(learned) in res.stderr,
                   f"the same file named explicitly must stay a hard error ({name}): "
                   f"{res.returncode} {res.stderr!r}")

        # 9b. A VALID learned file is MERGED with the defaults: the learned entries are tried first
        #     (a learned id replaces the built-in row outright), every built-in row they do not
        #     override stays live, and the `patterns:` line names BOTH sources.
        write_json(learned, {
            "version": 1,
            "patterns": [
                {"id": "6", "category": "PROJECT_MISSING_MODULE",
                 "patterns": ["ModuleNotFoundError"], "route": "planner"},
                {"id": "P1", "category": "LEARNED_ONE", "patterns": ["ErrCode 4242"], "route": "ba"},
            ],
            "retry_budgets": {"ba": 0},
        })
        res = classify(broken_repo, broken_log)
        expect(res.returncode == 0 and res.stderr == "",
               f"a valid learned file must not warn: {res.stderr!r}")
        expect(len(sources_of(res.stdout)) == 2,
               f"both sources must be named: {field(res.stdout, 'patterns')!r}")
        expect_same_path(sources_of(res.stdout)[0], learned,
                         "the named learned file must be the same file")
        expect_same_path(sources_of(res.stdout)[1], DEFAULT,
                         "the named default snapshot must be the same file")
        expect(field(res.stdout, "category") == "PROJECT_MISSING_MODULE"
               and field(res.stdout, "route") == "planner" and field(res.stdout, "pattern_id") == "6",
               f"the learned conflict winner must apply: {res.stdout!r}")
        learned_log = write(logs / "learned.log", "ErrCode 4242: boom\n")
        res = classify(broken_repo, learned_log)
        expect(field(res.stdout, "category") == "LEARNED_ONE"
               and field(res.stdout, "route") == "ba" and field(res.stdout, "pattern_id") == "P1",
               f"a learned entry of a new id must apply: {res.stdout!r}")
        res = classify(broken_repo, perm_log)        # a built-in row the learned file never touched
        expect(field(res.stdout, "category") == "PERMISSION"
               and field(res.stdout, "pattern_id") == "15",
               f"the built-in rows must stay live next to the learned ones: {res.stdout!r}")
        # …and the merge rule itself, at library level: project-first order, id-deduplicated union.
        merged = er.combine(er.load_document(learned, require_full=False), doc)
        merged_ids = [e["id"] for e in merged["patterns"]]
        expect(merged_ids[:2] == ["6", "P1"], f"learned entries must come first: {merged_ids}")
        expect(len(merged_ids) == 25 and merged_ids.count("6") == 1,
               f"a learned id must replace, not duplicate, its built-in row: {merged_ids}")
        expect([e["id"] for e in merged["provider_patterns"]]
               == [e["id"] for e in doc["provider_patterns"]],
               "the provider rows must all survive a learned file without provider_patterns")
        expect(merged["retry_budgets"] == {**BUDGETS, "ba": 0},
               f"the learned budgets must override the defaults key-wise: {merged['retry_budgets']}")

        # 9c. `--repo` anchors the RELATIVE paths of the invocation: the log, the patterns files
        #     (`--project-patterns` / `--project`) and `--out` resolve against the run's resolved
        #     repo_path, so a run launched elsewhere classifies the target repository's own log. An
        #     absolute path is taken as it is (`--log` unchanged with a foreign `--repo`), and without
        #     the flag the cwd stays the base (cases 6 and 7).
        launch = tmp / "launch"
        launch.mkdir()
        anchored_repo = tmp / "target" / "repo"
        anchored_log = write(anchored_repo / ".code-factory" / "logs" / "rel.log",
                             "ModuleNotFoundError: No module named 'x'\n")
        res = run("classify", "--log", ".code-factory/logs/rel.log", "--repo", str(anchored_repo),
                  cwd=str(launch))
        expect(res.returncode == 0 and field(res.stdout, "category") == "MISSING_FILE"
               and field(res.stdout, "pattern_id") == "6",
               f"a relative --log must resolve against --repo: {res.stdout!r} {res.stderr!r}")
        expect_same_path(field(res.stdout, "log"), anchored_log,
                         "the anchored path must be the one reported")
        write_json(anchored_repo / ".code-factory" / "state" / "learned.json",
                   {"patterns": [{"id": "6", "category": "ANCHORED_MISSING",
                                  "patterns": ["ModuleNotFoundError"], "route": "human"}]})
        res = run("classify", "--log", ".code-factory/logs/rel.log", "--repo", str(anchored_repo),
                  "--project-patterns", ".code-factory/state/learned.json", cwd=str(launch))
        expect(res.returncode == 0 and field(res.stdout, "category") == "ANCHORED_MISSING"
               and field(res.stdout, "route") == "human",
               f"a relative --project-patterns must resolve against --repo: {res.stdout!r}")
        anchored_project = sources_of(res.stdout)[0]
        expect(canonical_path(anchored_project).startswith(canonical_path(anchored_repo) + os.sep),
               f"the anchored patterns file must be the one named: {res.stdout!r}")
        res = run("merge", "--project", ".code-factory/state/learned.json",
                  "--out", "merged.json", "--repo", str(anchored_repo), cwd=str(launch))
        expect(res.returncode == 0 and (anchored_repo / "merged.json").is_file(),
               f"merge --repo must anchor --project/--out: {res.stderr!r}")
        expect(json.loads((anchored_repo / "merged.json").read_text(encoding="utf-8"))
               ["patterns"][0]["category"] == "ANCHORED_MISSING",
               "the merged document must come from the anchored project file")
        expect(not (launch / "merged.json").exists(),
               "nothing may be written into the launch directory when --repo is given")
        res = run("export-defaults", "--out", "starter.json", "--repo", str(anchored_repo),
                  cwd=str(launch))
        expect(res.returncode == 0 and (anchored_repo / "starter.json").read_bytes() == raw,
               f"export-defaults --repo must anchor a relative --out: {res.stderr!r}")
        res = run("classify", "--log", ".code-factory/logs/rel.log", cwd=str(launch))
        expect(res.returncode == 1 and "cannot read log" in res.stderr,
               f"without --repo the cwd stays the base: {res.stderr!r}")
        res = run("classify", "--log", str(anchored_log), "--repo", str(launch), cwd=str(launch))
        expect(res.returncode == 0 and field(res.stdout, "category") == "MISSING_FILE",
               f"an absolute --log must never be re-anchored: {res.stdout!r} {res.stderr!r}")

        # 9d. The path assertions of this suite compare SPELLINGS of one file: the spelling the
        #     test built and the spelling the tool reported. On a machine whose user name is not
        #     ASCII the temp base arrives in its 8.3 short form (`C:\Users\836D~1\...`) while the
        #     patterns path keeps the full Unicode spelling, so a verbatim `==` fails there although
        #     both strings name one file. The condition is SIMULATED here (this machine's user name
        #     is ASCII): the base carries non-ASCII characters and the second spelling is the short
        #     name Windows itself reports for it (`GetShortPathNameW`) - or, on a volume without 8.3
        #     aliases and outside Windows, a case/separator/`.`-segment variant of the same path.
        base = tmp / "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c" \
                    / "8.3-alias"
        repo_uni = base / "repo"
        log_uni = write(base / "logs" / "rel.log", "ModuleNotFoundError: No module named 'x'\n")
        learned_uni = write_json(repo_uni / ".code-factory" / "state" / "error-patterns.json",
                                 {"patterns": [{"id": "6", "category": "SHORT_NAME_MISSING",
                                                "patterns": ["ModuleNotFoundError"],
                                                "route": "planner"}]})
        alias_repo, alias_log = other_spelling(repo_uni), other_spelling(log_uni)
        expect(alias_log != str(log_uni) and alias_repo != str(repo_uni),
               f"the simulation must spell the same paths differently: {alias_log!r} / "
               f"{alias_repo!r} vs {str(log_uni)!r}")
        res = run("classify", "--log", alias_log, "--repo", alias_repo)
        expect(res.returncode == 0 and res.stderr == "",
               f"one file under two spellings must classify: {res.returncode} {res.stderr!r}")
        expect(field(res.stdout, "category") == "SHORT_NAME_MISSING"
               and field(res.stdout, "pattern_id") == "6",
               f"the learned file must be found through the aliased repo: {res.stdout!r}")
        # The comparison this suite needs: every spelling below names ONE file, so it must compare
        # equal — the short-name spelling against the full Unicode spelling, and against the tool's.
        expect_same_path(alias_log, log_uni, "the short-name and Unicode spellings are one file")
        expect_same_path(alias_repo, repo_uni, "the short-name and Unicode spellings are one repo")
        expect_same_path(field(res.stdout, "log"), log_uni,
                         "the reported log must be the same file as the Unicode spelling")
        expect_same_path(field(res.stdout, "log"), alias_log,
                         "the reported log must be the same file as the short-name spelling")
        reported = sources_of(res.stdout)
        expect(len(reported) == 2, f"both patterns sources must be named: {reported!r}")
        expect_same_path(reported[0], learned_uni, "the named learned file must be the same file")
        expect_same_path(reported[1], DEFAULT, "the named default snapshot must be the same file")

        # 10. An unreadable log is an operational error (1); a wrong CLI call is exit 2.
        res = classify(repo, tmp / "missing.log")
        expect(res.returncode == 1 and "cannot read log" in res.stderr,
               f"an unreadable log must exit 1: {res.returncode} {res.stderr!r}")
        expect(run("classify").returncode == 2, "a missing --log must exit 2")
        expect(run("merge").returncode == 2, "a missing --project must exit 2")
        expect(run().returncode == 2, "a missing subcommand must exit 2")

    # 11. stdlib-only contract (no third-party imports).
    src = pathlib.Path(er.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", src, flags=re.M))
    allowed = {"__future__", "argparse", "json", "pathlib", "re", "sys"}
    expect(imported <= allowed, f"error_router must be stdlib-only, imports={imported}")

    print("PASS - error_router.py mirrors the error-routing tables (24 section-1 rows + 6 provider "
          "rows), classifies samples deterministically, merges the project-learned patterns over "
          "the defaults (project-first, both applied), falls back to the defaults with a warning "
          "when the learned file is unusable, merges byte-identically, anchors relative paths at "
          "--repo, compares every path spelling (8.3 short name / case / separators) as one path, "
          "and honours the exit-code contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
