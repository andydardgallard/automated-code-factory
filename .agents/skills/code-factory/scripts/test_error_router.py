#!/usr/bin/env python3
"""
Deterministic self-test for `error_router.py` (zero LLM tokens, stdlib only).

`references/error-patterns.default.json` is the snapshot of the routing tables of
`references/error-routing.md` (§1 rows 1-20 + §1.1 provider rows A-F); the router classifies a log
against them in array order ("first match wins") and lets a project override patterns through
`.code-factory/state/error-patterns.json` (project-first merge, deduplicated by id).

Covered here: the snapshot's shape and order (ids 1-20 + A-F, categories, routes, retry budgets),
sample logs from the tables (WRONG_RESULTS must win over the generic assertion/compile rows, a
provider `401` line is PROVIDER_AUTH), the unmatched fallback (diagnostician), project priority over
the built-in rows, the default fallback when no project file exists, deterministic and idempotent
`merge` output, `export-defaults` as a byte-exact starter, and the exit-code contract (2 for an
unusable patterns JSON, 1 for an unreadable log), plus the stdlib-only import contract.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

import error_router as er

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "error_router.py"
DEFAULT = SCRIPTS.parent / "references" / "error-patterns.default.json"

# §1 rows 1-20, in table order: id, category, route to.
EXPECTED = [
    ("1", "MISSING_INPUT", "human"),
    ("2", "WRONG_RESULTS", "diagnostician"),
    ("3", "INFRASTRUCTURE", "infrastructure"),
    ("4", "INFRASTRUCTURE", "infrastructure"),
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
]
UNMATCHED_LOG = "everything is fine here\n0 failed\n"


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace", cwd=cwd)


def field(stdout: str, key: str) -> str:
    """Value of one `key: value` output line (the value may contain ': ' itself)."""
    for line in stdout.splitlines():
        if line.startswith(f"{key}: "):
            return line[len(key) + 2:]
    raise AssertionError(f"missing field {key!r} in output:\n{stdout}")


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def write_json(path: pathlib.Path, payload: object) -> pathlib.Path:
    return write(path, json.dumps(payload, indent=2) + "\n")


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
    expect(len(er.match_order(doc)) == 26, "20 §1 rows + 6 provider rows must be classified")
    expect(doc["patterns"][19]["patterns"] == [], "the terminal UNKNOWN row carries no regex")
    expect(all(e["patterns"] for e in doc["patterns"][:19]), "rows 1-19 must all carry regexes")
    ids = [e["id"] for e in doc["patterns"]]
    # Note in §1: business-result markers may sit inside an assertion message.
    expect(ids.index("2") < ids.index("8") < ids.index("19"),
           "WRONG_RESULTS must be checked before the compile/assertion rows")
    # Rows 16/17 share the same regexes — the "(with 'test' in output)" condition is prose, not a
    # regex, so row 16 shadows row 17 under "first match wins". Pinned here so the shadowing is
    # visible rather than silent (the text update of error-routing.md has to resolve it).
    expect(doc["patterns"][15]["patterns"] == doc["patterns"][16]["patterns"],
           "rows 16 and 17 must still mirror the table's shared pattern cell")
    # Row 8's cell is `error[E\d+]` — a CHARACTER CLASS, so it matches `error4`, not Cargo's
    # `error[E0432]`. Copied verbatim here (the snapshot must not rewrite the table); a project can
    # override id 8 with a learned pattern, and the text update of error-routing.md has to decide.
    expect("error[E\\d+]" in doc["patterns"][7]["patterns"],
           f"row 8 must snapshot the table's regex verbatim: {doc['patterns'][7]['patterns']}")
    # Row 18's `Traceback (most recent call last)` keeps its parentheses UNESCAPED (a regex group),
    # so the live alternatives are `Segmentation fault`, `Fatal error`, `panic:` … — same verbatim
    # snapshot policy: the snapshot never rewrites the table, the findings go to the text update.
    expect("Traceback (most recent call last)" in doc["patterns"][17]["patterns"],
           f"row 18 must snapshot the table's regex verbatim: {doc['patterns'][17]['patterns']}")
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
        expect(str(DEFAULT) in field(res.stdout, "patterns"),
               f"the default snapshot must be the source: {res.stdout!r}")
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
        expect(len(merged_ids) == 21,
               f"2 learned + the 19 untouched defaults were expected: {merged_ids}")
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

    print("PASS - error_router.py mirrors the error-routing tables (20 section-1 rows + 6 provider "
          "rows), classifies samples deterministically, lets project-learned patterns win, merges "
          "byte-identically and honours the exit-code contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
