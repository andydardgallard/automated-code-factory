#!/usr/bin/env python3
"""
Deterministic contract test for `farukon_mcp.py` (zero LLM tokens, no network, no cargo build).

Covers, with tempfile fixtures:
  - the applicability decision: a Farukon platform repository PLUS platform-operation task scope is
    `applicable` (crate manifest, workspace member and an existing config entry each count as host
    signature); host signature alone, scope alone, a missing repository and every explicit exclusion
    (`no mcp`, `without farukon`) are `not_applicable` — every decision carries a non-empty reason,
  - `merge-config`: refusal for a repository that is not a Farukon platform root and for a `--target`
    outside the repository, create, byte-for-byte preservation of unrelated servers/settings (LF and
    CRLF), idempotent second run, conflict preserved and reported with exit code 3, an invalid target
    left untouched, `--dry-run` never writing,
  - `validate-config`: the managed command/args/cwd invariants, an absent entry being valid, and the
    malformed variants (foreign command, wrong args, relative or missing cwd, non-object entry),
  - `probe`: the monkeypatchable `_which`/`_try_run` seams (a host without cargo degrades to DATA,
    exit 0), the config capability of a merged project, `--out`, and the exit-1 input errors
    (missing repository, `--target` escape),
  - the bounded JSON-RPC handshake against a REAL spawned fake stdio server: all eight Farukon tools
    listed, a server missing tools, a server that never answers and a server that answers with an
    error — each bounded and each terminating its child process,
  - the CLI contract: `--help` exit 0 for every subcommand, usage error exit 2, no traceback.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "farukon_mcp.py"

sys.path.insert(0, str(SCRIPTS))
import farukon_mcp as fm  # noqa: E402  (the importable API under test)

COUNTER = {"checks": 0}

SCOPE_TEXT = (
    "Implement farukon_start and farukon_stop for the platform: start the instance, verify the "
    "connector state and the message log, then stop it."
)
HOST_ONLY_TEXT = "Refactor the logging module used by the report generator and update its docstring."
# Documentation only: names the platform and nothing it DOES, so it stays OFF.
DOCS_ONLY_TEXT = ("Update the Farukon README documentation: fix the typo in the platform overview "
                  "section.")
# Every IDENTITY word of the vocabulary and none of the OPERATION words: the score alone must not
# decide, otherwise this task would activate a cargo/MCP session.
IDENTITY_ONLY_TEXT = ("Rewrite the farukon platform mcp server mcp tool stdio tool integration "
                      "runtime reference page.")
EXCLUDED_TEXT = ("Fix the unit test of the parser. Do not use mcp here and leave the platform "
                 "without farukon changes.")
# The plain operation verbs of a platform session: "run/test/debug/build the platform" is exactly
# what the specialist is for, and identity + operation is what makes it applicable. Both spellings of
# a bare build are pinned because `build` used to carry a single point and fell below the threshold.
OPERATION_TEXTS = (
    ("Run the Farukon platform and check it comes up.", "run"),
    ("Debug the Farukon platform: the connectors stop responding.", "debug"),
    ("Test the Farukon platform end to end before the release.", "test"),
    ("Build the platform.", "build"),
    ("Build Farukon.", "build"),
    ("Fix the failing test in farukon_mcp/src/server.rs.", "test"),
)
# An operation on a DIFFERENT subject is somebody else's task: run/test are generic verbs, so they
# only count together with the platform identity the task text itself has to name.
UNRELATED_OPERATION_TEXTS = (
    "Run the parser test suite and fix the failures the report generator shows.",
    "Debug the logging helper and test the report formatter end to end.",
    "Restart the documentation build and run the link checker.",
)
# SUBJECT BINDING: the platform is named, but every operation in the task targets DOCUMENTATION. The
# name of the platform elsewhere in the sentence does not transfer an operation to it.
DOCUMENTATION_OPERATION_TEXTS = (
    "Update the Farukon README and run the documentation build.",
    "Fix the Farukon README typo and build the documentation site.",
    "Refresh the Farukon manual: test the documentation examples.",
)
# …while a task that REALLY operates the platform stays applicable next to a documentation edit.
MIXED_SCOPE_TEXT = ("Fix the Farukon README typo and run cargo test for the platform before the "
                    "release.")
# The metadata key pins the specialist's MODEL; it says nothing about what the task operates.
MODEL_KEY_TASK = """\
title: refactor the logging module
description: |
  Replace the hand-rolled logging helper with the project logger and update its docstring.
models:
  coder: deepseek-flash
  farukon_expert: deepseek-flash
mode: auto
"""


def check(cond: bool, msg: str) -> None:
    COUNTER["checks"] += 1
    if not cond:
        raise AssertionError(msg)


def run(*args: str, cwd: str | None = None, env: dict | None = None
        ) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", cwd=cwd, env=env)


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: stderr must not carry a traceback: {res.stderr!r}")


def written(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


@contextlib.contextmanager
def seams(**patches):
    """Temporarily replace module-level seams (`_which`, `_try_run`) with test doubles."""
    originals = {name: getattr(fm, name) for name in patches}
    for name, value in patches.items():
        setattr(fm, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(fm, name, value)


def platform_repo(root: pathlib.Path, style: str = "crate") -> pathlib.Path:
    """A repository carrying the Farukon host signature in the requested shape.

    `workspace` declares the crate at `crates/farukon_mcp` AND puts its manifest there: a
    `members = [...]` entry alone builds nothing, so the declaration without the manifest is a
    separate fixture (`workspace-declared-only`).
    """
    root.mkdir(parents=True, exist_ok=True)
    if style in ("crate", "both"):
        written(root / "farukon_mcp" / "Cargo.toml",
                '[package]\nname = "farukon_mcp"\nversion = "0.1.0"\n')
    if style in ("workspace", "both"):
        written(root / "Cargo.toml",
                '[workspace]\nmembers = [\n  "crates/farukon_mcp",\n  "other_crate",\n]\n')
        written(root / "crates" / "farukon_mcp" / "Cargo.toml",
                '[package]\nname = "farukon_mcp"\nversion = "0.1.0"\n')
    if style == "workspace-declared-only":
        written(root / "Cargo.toml",
                '[workspace]\nmembers = [\n  "crates/farukon_mcp",\n  "other_crate",\n]\n')
    if style == "config":
        written(root / ".kimi-code" / "mcp.json",
                json.dumps({"mcpServers": {"farukon": fm.managed_entry(root)}}, indent=2) + "\n")
    return root


def inserted_member(name: str, entry: dict, indent: str = "    ", newline: str = "\n") -> str:
    """Independently computed expectation of the text `merge_config` must insert."""
    block = json.dumps({name: entry}, indent=2).replace("\n", newline)
    relative = [line[2:] for line in block.splitlines()[1:-1]]
    return "," + newline + indent + (newline + indent).join(relative)


# --------------------------------------------------------------------- applicability

def test_decide(tmp: pathlib.Path) -> None:
    repo = platform_repo(tmp / "platform-crate")
    decision = fm.decide_applicability(SCOPE_TEXT, repo=repo)
    check(decision["decision"] == fm.APPLICABLE,
          f"a platform-operation task in a Farukon repository must be applicable: {decision}")
    check("the repository hosts the Farukon platform" in decision["reason"],
          f"an applicable decision must carry its reason: {decision['reason']!r}")
    check(decision["evidence"]["scope_terms"] and decision["evidence"]["scope_score"] >= 3,
          f"the reason must cite the matched scope terms: {decision['evidence']}")
    check(decision["evidence"]["host_signals"]["crate_manifest"] == "farukon_mcp/Cargo.toml",
          f"the crate manifest must be recorded as the host signature: {decision['evidence']}")

    decision = fm.decide_applicability(HOST_ONLY_TEXT, repo=repo)
    check(decision["decision"] == fm.NOT_APPLICABLE,
          f"host signature WITHOUT task scope must stay not_applicable: {decision}")
    check("no platform-operation scope" in decision["reason"],
          f"the reason must name the missing scope: {decision['reason']!r}")
    check(decision["evidence"]["host_signals"]["platform"] is True
          and decision["evidence"]["scope_score"] < fm.SCOPE_APPLICABLE_SCORE,
          f"the host signature must still be recorded as evidence: {decision['evidence']}")

    bare = tmp / "bare-repo"
    bare.mkdir()
    decision = fm.decide_applicability(SCOPE_TEXT, repo=bare)
    check(decision["decision"] == fm.NOT_APPLICABLE,
          f"task scope WITHOUT a host signature must stay not_applicable: {decision}")
    check("does not host the Farukon platform" in decision["reason"],
          f"the reason must name the missing host signature: {decision['reason']!r}")

    decision = fm.decide_applicability(EXCLUDED_TEXT, repo=repo)
    check(decision["decision"] == fm.NOT_APPLICABLE,
          f"an explicit exclusion must win: {decision}")
    check(decision["evidence"]["exclusions"],
          f"the exclusions must be recorded as evidence: {decision['evidence']}")

    workspace = platform_repo(tmp / "platform-workspace", style="workspace")
    decision = fm.decide_applicability("Run cargo test for the platform and stop the instance.",
                                       repo=workspace)
    check(decision["decision"] == fm.APPLICABLE,
          f"a workspace member must be a host signature: {decision}")
    check(decision["evidence"]["host_signals"]["workspace_member"]
          and decision["evidence"]["host_signals"]["crate_manifest"] is None,
          f"the workspace member must be the recorded signal: {decision['evidence']}")

    config_only = platform_repo(tmp / "platform-config", style="config")
    decision = fm.decide_applicability(HOST_ONLY_TEXT, repo=config_only)
    check(decision["decision"] == fm.NOT_APPLICABLE,
          f"a config entry ALONE without task scope must stay not_applicable: {decision}")
    check(decision["evidence"]["host_signals"]["mcp_entry"],
          f"the config entry must be recorded as a host signal: {decision['evidence']}")
    decision = fm.decide_applicability(SCOPE_TEXT, repo=config_only)
    check(decision["decision"] == fm.APPLICABLE,
          f"a configured platform plus task scope must be applicable: {decision}")

    res = run("decide", "--repo", str(repo), "--text", SCOPE_TEXT)
    expect_clean_cli(res, 0, "decide --text (applicable)")
    check(res.stdout.splitlines()[0] == fm.APPLICABLE,
          f"the first stdout line must be the decision: {res.stdout!r}")
    check("reason: " in res.stdout and "scope_score=" in res.stdout,
          f"the output must carry a reason and the score: {res.stdout!r}")

    payload = json.loads(run("decide", "--repo", str(repo), "--text", SCOPE_TEXT, "--json").stdout)
    check(payload["decision"] == fm.APPLICABLE and payload["reason"], f"--json: {payload}")
    check(set(payload["evidence"]) == {"host_signals", "scope_terms", "exclusions", "scope_score"},
          f"--json evidence must expose the four documented fields: {payload['evidence']}")

    task_file = written(tmp / "task.yaml", f"title: platform\ndescription: |\n  {SCOPE_TEXT}\n")
    res = run("decide", "--repo", str(repo), "--task-file", str(task_file))
    expect_clean_cli(res, 0, "decide --task-file")
    check(res.stdout.splitlines()[0] == fm.APPLICABLE, f"--task-file: {res.stdout!r}")

    # 1a. NEGATIVE: documentation only. Naming the project is not operating it.
    decision = fm.decide_applicability(DOCS_ONLY_TEXT, repo=repo)
    check(decision["decision"] == fm.NOT_APPLICABLE,
          f"a documentation-only task must stay not_applicable: {decision}")
    check("no platform-operation scope" in decision["reason"],
          f"the reason must name the missing operation scope: {decision['reason']!r}")
    check(decision["evidence"]["scope_score"] < fm.SCOPE_APPLICABLE_SCORE,
          f"naming the project alone must not reach the threshold: {decision['evidence']}")

    # 1b. NEGATIVE: identity ONLY. Every identity word together out-scores the threshold, yet the
    # task names no operation — the OPERATION requirement (not the score) is what keeps the role off.
    decision = fm.decide_applicability(IDENTITY_ONLY_TEXT, repo=repo)
    check(decision["evidence"]["scope_score"] >= fm.SCOPE_APPLICABLE_SCORE,
          f"the fixture must clear the score threshold: {decision['evidence']}")
    check(decision["decision"] == fm.NOT_APPLICABLE,
          f"identity vocabulary alone must stay not_applicable: {decision}")
    check("operation terms: none" in decision["reason"],
          f"the reason must say that no operation term matched: {decision['reason']!r}")

    # 1d. POSITIVE: the plain operation verbs. "Run/Test/Debug the platform" is the specialist's own
    # work — the previous table only knew start/stop/deploy, so these tasks were silently OFF.
    for text, verb in OPERATION_TEXTS:
        decision = fm.decide_applicability(text, repo=repo)
        check(decision["decision"] == fm.APPLICABLE,
              f"{text!r} names {verb!r} on the platform, so it must be applicable: {decision}")
        check(verb in decision["evidence"]["scope_terms"],
              f"the matched {verb!r} must be recorded as evidence: {decision['evidence']}")

    # 1e. NEGATIVE: the same verbs on ANOTHER subject. The operation term only counts together with
    # the platform identity the task text itself names, so generic run/test/debug work stays OFF.
    for text in UNRELATED_OPERATION_TEXTS:
        decision = fm.decide_applicability(text, repo=repo)
        check(decision["decision"] == fm.NOT_APPLICABLE,
              f"an operation on another subject must stay not_applicable: {text!r} -> {decision}")
        check("identity terms: none" in decision["reason"],
              f"the reason must say that no platform identity matched: {decision['reason']!r}")

    # 1f. NEGATIVE: subject binding. The platform is NAMED, but every operation in the task operates
    # on DOCUMENTATION — naming Farukon does not make "run the documentation build" a platform run.
    for text in DOCUMENTATION_OPERATION_TEXTS:
        decision = fm.decide_applicability(text, repo=repo)
        check(decision["decision"] == fm.NOT_APPLICABLE,
              f"a documentation operation must stay not_applicable: {text!r} -> {decision}")
        check("identity terms:" in decision["reason"]
              and "identity terms: none" not in decision["reason"],
              f"the platform identity IS present here — the binding must be what refuses it: "
              f"{decision['reason']!r}")
        check("bound to another subject" in decision["reason"],
              f"the reason must record the discarded operations: {decision['reason']!r}")

    # 1g. POSITIVE: a mixed task that REALLY runs the platform stays applicable even next to a
    # documentation edit — one bound operation is enough.
    decision = fm.decide_applicability(MIXED_SCOPE_TEXT, repo=repo)
    check(decision["decision"] == fm.APPLICABLE,
          f"a real platform operation must stay applicable in a mixed task: {decision}")
    check(decision["evidence"]["scope_terms"] and "cargo test" in decision["evidence"]["scope_terms"],
          f"the bound operation must be recorded: {decision['evidence']}")

    # 1c. NEGATIVE: the task pins the specialist's MODEL and does nothing platform-related. Task
    # metadata (`models:`) is wiring, not scope, so it must not be classified at all.
    model_task = written(tmp / "model-key-task.yaml", MODEL_KEY_TASK)
    res = run("decide", "--repo", str(repo), "--task-file", str(model_task), "--json")
    expect_clean_cli(res, 0, "decide --task-file with a models.farukon_expert key")
    payload = json.loads(res.stdout)
    check(payload["decision"] == fm.NOT_APPLICABLE,
          f"a models.farukon_expert key alone must not activate the role: {payload}")
    check("farukon" not in payload["evidence"]["scope_terms"],
          f"the model metadata must be stripped before classification: {payload['evidence']}")
    decision = fm.decide_applicability(MODEL_KEY_TASK, repo=repo)
    check(decision["decision"] == fm.NOT_APPLICABLE
          and decision["evidence"]["scope_terms"] == [],
          f"the metadata block must leave no scope terms at all: {decision['evidence']}")

    res = run("decide", "--repo", str(tmp / "missing-repo"), "--text", SCOPE_TEXT)
    expect_clean_cli(res, 1, "decide with a missing repository")
    check("does not exist" in res.stderr, f"a missing repository must be an error: {res.stderr!r}")

    res = run("decide", "--repo", str(repo), "--task-file", str(tmp / "nope.yaml"))
    expect_clean_cli(res, 1, "decide with a missing task file")
    check("task file not found" in res.stderr, f"a missing task file must be explained: {res.stderr!r}")


# --------------------------------------------------------------------- merge-config

def test_merge_config(tmp: pathlib.Path) -> None:
    # 1. A repository that does not host the platform is refused, and nothing is written.
    plain = tmp / "not-a-platform"
    plain.mkdir()
    res = run("merge-config", "--repo", str(plain))
    expect_clean_cli(res, 1, "merge-config on a non-platform repository")
    check("not a Farukon platform root" in res.stderr,
          f"the refusal must name the missing host signature: {res.stderr!r}")
    check(not (plain / ".kimi-code" / "mcp.json").exists(),
          "a refused merge must not create a config")

    # 2. Create: the managed definition, exactly.
    repo = platform_repo(tmp / "created")
    res = run("merge-config", "--repo", str(repo))
    expect_clean_cli(res, 0, "merge-config create")
    config = repo / ".kimi-code" / "mcp.json"
    check(config.is_file(), "a missing default target must be created")
    check(res.stdout.startswith("created"), f"the create path must be reported: {res.stdout!r}")
    data = json.loads(config.read_text(encoding="utf-8"))
    entry = data["mcpServers"][fm.SERVER_NAME]
    check(entry == {"command": "cargo", "args": ["run", "--quiet", "-p", "farukon_mcp", "--"],
                    "cwd": str(repo)},
          f"the created entry must be the deterministic managed definition: {entry}")
    check(os.path.isabs(entry["cwd"]) and os.path.normpath(entry["cwd"]) == entry["cwd"],
          f"cwd must be an absolute normalized path: {entry['cwd']!r}")
    check(fm.validate_config(config) == (True, []),
          f"the created config must satisfy the invariants: {fm.validate_config(config)}")

    # 3. Idempotent second run: no byte may change.
    before = config.read_text(encoding="utf-8", newline="")
    res = run("merge-config", "--repo", str(repo))
    expect_clean_cli(res, 0, "merge-config idempotent")
    check(res.stdout.startswith("unchanged"), f"the second run must be idempotent: {res.stdout!r}")
    check(config.read_text(encoding="utf-8", newline="") == before,
          "the second run must not change a single byte")

    # 4. Unrelated servers and settings survive byte-for-byte.
    original = (
        '{\n'
        '  "mcpServers": {\n'
        '    "unrelated-server": {\n'
        '      "command": "python",\n'
        '      "args": ["-m", "unrelated.server"]\n'
        '    }\n'
        '  },\n'
        '  "userSetting": {\n'
        '    "keep": true\n'
        '  }\n'
        '}\n'
    )
    preserve = platform_repo(tmp / "preserve")
    target = written(preserve / ".kimi-code" / "mcp.json", original)
    managed = fm.managed_entry(preserve)
    head, sep, rest = original.partition("\n    }")
    check(sep == "\n    }", "the fixture must contain the expected closing brace")
    merged_expected = head + sep + inserted_member(fm.SERVER_NAME, managed) + rest
    res = run("merge-config", "--repo", str(preserve))
    expect_clean_cli(res, 0, "merge-config preserve")
    merged = target.read_text(encoding="utf-8", newline="")
    check(merged == merged_expected,
          f"unrelated servers and settings must survive byte-for-byte:\n{merged!r}\n!=\n"
          f"{merged_expected!r}")
    check(res.stdout.startswith("updated"), f"the merge must be reported as updated: {res.stdout!r}")

    # 5. CRLF file: line endings and unrelated bytes are preserved.
    crlf_repo = platform_repo(tmp / "crlf")
    crlf_original = original.replace("\n", "\r\n")
    crlf_target = written(crlf_repo / ".kimi-code" / "mcp.json", crlf_original)
    head, sep, rest = crlf_original.partition("\r\n    }")
    crlf_expected = head + sep + inserted_member(fm.SERVER_NAME, fm.managed_entry(crlf_repo),
                                                 newline="\r\n") + rest
    res = run("merge-config", "--repo", str(crlf_repo))
    expect_clean_cli(res, 0, "merge-config crlf")
    check(crlf_target.read_text(encoding="utf-8", newline="") == crlf_expected,
          "a CRLF target must keep its line endings and its unrelated bytes")

    # 6. An empty mcpServers map gains the entry and keeps the surrounding indentation.
    empty_repo = platform_repo(tmp / "empty-servers")
    empty_target = written(empty_repo / ".kimi-code" / "mcp.json", '{\n  "mcpServers": {}\n}\n')
    res = run("merge-config", "--repo", str(empty_repo))
    expect_clean_cli(res, 0, "merge-config empty mcpServers")
    emptied = empty_target.read_text(encoding="utf-8", newline="")
    check(emptied.startswith('{\n  "mcpServers": {\n    "farukon": {\n'),
          f"the entry must be indented like its siblings: {emptied!r}")
    check(list(json.loads(emptied)["mcpServers"]) == [fm.SERVER_NAME],
          f"exactly one server must be added: {emptied!r}")

    # 7. A DIFFERENT farukon entry is a conflict: exit 3, bytes preserved, differences reported.
    conflict_text = (
        '{\n'
        '  "mcpServers": {\n'
        '    "farukon": {\n'
        '      "command": "cargo",\n'
        '      "args": ["run", "-p", "farukon_mcp"]\n'
        '    },\n'
        '    "unrelated-server": {\n'
        '      "command": "python"\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    conflict_repo = platform_repo(tmp / "conflict")
    conflict_target = written(conflict_repo / ".kimi-code" / "mcp.json", conflict_text)
    res = run("merge-config", "--repo", str(conflict_repo))
    expect_clean_cli(res, fm.EXIT_CONFLICT, "merge-config conflict")
    check("CONFLICT" in res.stderr and "args" in res.stderr,
          f"the conflict must name the diverging setting: {res.stderr!r}")
    check(conflict_target.read_text(encoding="utf-8", newline="") == conflict_text,
          "a conflicting entry must be preserved byte-for-byte, never overwritten")
    payload = json.loads(run("merge-config", "--repo", str(conflict_repo), "--json").stdout)
    check(payload["status"] == "conflict" and payload["conflict"]["differences"],
          f"--json must expose the conflict and its differences: {payload}")

    # 8. An invalid target is never overwritten.
    broken_repo = platform_repo(tmp / "broken")
    broken_text = '{"mcpServers": {"other": {}}}\nnot json at all\n'
    broken = written(broken_repo / ".kimi-code" / "mcp.json", broken_text)
    res = run("merge-config", "--repo", str(broken_repo))
    expect_clean_cli(res, 1, "merge-config invalid target")
    check("not valid JSON" in res.stderr, f"the invalid target must be explained: {res.stderr!r}")
    check(broken.read_text(encoding="utf-8", newline="") == broken_text,
          "an invalid target must be left untouched")

    # 9. A --target outside the repository is refused; nothing is written there.
    escape_repo = platform_repo(tmp / "escape" / "repo")
    outside = tmp / "escape" / "outside" / "mcp.json"
    res = run("merge-config", "--repo", str(escape_repo), "--target", str(outside))
    expect_clean_cli(res, 1, "merge-config --target escape")
    check("outside the repository root" in res.stderr,
          f"an escaping --target must be refused: {res.stderr!r}")
    check(not outside.exists(), "an escaping --target must never be written")
    res = run("merge-config", "--repo", str(escape_repo), "--target",
              str(escape_repo / ".." / "outside" / "mcp.json"))
    expect_clean_cli(res, 1, "merge-config --target escape (relative dots)")

    # 10. A custom in-repo --target is honoured; --dry-run never writes.
    dry_repo = platform_repo(tmp / "dry-run")
    custom = dry_repo / "nested" / "mcp.json"
    res = run("merge-config", "--repo", str(dry_repo), "--target", str(custom), "--dry-run")
    expect_clean_cli(res, 0, "merge-config --dry-run")
    check(not custom.exists(), "a dry run must not create the target")
    check("[dry-run]" in res.stdout, f"a dry run must say so: {res.stdout!r}")
    res = run("merge-config", "--repo", str(dry_repo), "--target", str(custom))
    expect_clean_cli(res, 0, "merge-config custom --target")
    check(json.loads(custom.read_text(encoding="utf-8"))["mcpServers"][fm.SERVER_NAME]["cwd"]
          == str(dry_repo), "the cwd must stay the platform repository root")


def test_merge_config_write_safety(tmp: pathlib.Path) -> None:
    """A write that cannot happen is a REPORTED error (exit 1, no traceback) and damages nothing."""
    # 1. The target is a DIRECTORY: mkstemp+replace cannot produce a file there.
    dir_repo = platform_repo(tmp / "target-is-directory")
    dir_target = dir_repo / ".kimi-code" / "mcp.json"
    dir_target.mkdir(parents=True)
    res = run("merge-config", "--repo", str(dir_repo))
    expect_clean_cli(res, 1, "merge-config with a directory target")
    check("cannot write" in res.stderr,
          f"an unwritable target must be explained: {res.stderr!r}")
    check(dir_target.is_dir(), "a refused write must leave the target exactly as it was")
    check(not list(dir_target.parent.glob("*.tmp")),
          f"a failed write must not leave a temp file behind: {list(dir_target.parent.glob('*'))}")

    # 2. A regular FILE occupies the directory the config belongs in.
    blocked_repo = platform_repo(tmp / "parent-is-a-file")
    blocker = blocked_repo / ".kimi-code"
    blocker.write_text("not a directory\n", encoding="utf-8")
    res = run("merge-config", "--repo", str(blocked_repo))
    expect_clean_cli(res, 1, "merge-config where the config directory is a file")
    check("cannot write" in res.stderr, f"the blocked directory must be explained: {res.stderr!r}")
    check(blocker.read_text(encoding="utf-8") == "not a directory\n",
          "the file that blocks the directory must be untouched")

    # 3. An existing config that cannot be replaced keeps every byte it had. A read-only target is
    #    the portable probe on Windows (a read-only FILE refuses replacement); where the platform
    #    replaces it anyway (POSIX puts the permission on the DIRECTORY) the case states that
    #    instead of asserting a refusal it cannot produce.
    guard_repo = platform_repo(tmp / "read-only-target")
    guard_target = written(guard_repo / ".kimi-code" / "mcp.json",
                           '{\n  "mcpServers": {\n    "unrelated": {\n      "command": "python"\n'
                           '    }\n  }\n}\n')
    before = guard_target.read_bytes()
    os.chmod(guard_target, 0o444)
    try:
        res = run("merge-config", "--repo", str(guard_repo))
        check("Traceback" not in res.stderr,
              f"a failed write must never traceback: {res.stderr!r}")
        if res.returncode == 1:
            check("cannot write" in res.stderr,
                  f"the failed write must be explained: {res.stderr!r}")
            check(guard_target.read_bytes() == before,
                  "a failed write must preserve the existing bytes (the write is atomic)")
            check(not list(guard_target.parent.glob("*.tmp")),
                  f"no temp file may survive a failed write: {list(guard_target.parent.glob('*'))}")
        else:
            check(res.returncode == 0 and guard_target.read_bytes() != before,
                  f"where the platform replaces a read-only file the merge must succeed: "
                  f"exit {res.returncode} {res.stdout!r} {res.stderr!r}")
    finally:
        os.chmod(guard_target, 0o644)

    # 4. The atomic writer itself: exact bytes, no temp file left behind.
    atomic = tmp / "atomic" / "config.json"
    fm._write_text_exact(atomic, "{\n}\n")
    check(atomic.read_text(encoding="utf-8", newline="") == "{\n}\n",
          "the writer must write the text byte-for-byte")
    check(not list(atomic.parent.glob("*.tmp")), "a successful write must clean its temp file up")


def make_directory_link(link: pathlib.Path, target: pathlib.Path) -> bool:
    """Create a directory link; `False` when this host cannot.

    A symlink needs a privilege Windows does not grant by default, a directory JUNCTION does not,
    so the escape case still runs on a stock Windows box. Both resolve through `realpath`, which is
    exactly what the containment check relies on.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True, errors="replace")
    return res.returncode == 0 and link.is_dir()


def test_target_confinement_follows_symlinks(tmp: pathlib.Path) -> None:
    """A link INSIDE the repository that points OUTSIDE it is not a contained `--target`."""
    repo = platform_repo(tmp / "symlink" / "repo")
    outside = tmp / "symlink" / "outside"
    outside.mkdir(parents=True)
    linked_dir = repo / "linked"
    if not make_directory_link(linked_dir, outside):
        # Only a host that cannot create a directory link at all skips this: the refusal itself is
        # the contract, not the platform's capability.
        print("note: skipping the directory-link escape case — this host cannot create a link")
        return

    res = run("merge-config", "--repo", str(repo), "--target", str(linked_dir / "mcp.json"))
    expect_clean_cli(res, 1, "merge-config through a linked directory escaping the repository")
    check("outside the repository root" in res.stderr,
          f"a linked --target must be refused: {res.stderr!r}")
    check(not (outside / "mcp.json").exists(),
          "a linked --target outside the repository must never be written")

    res = run("merge-config", "--repo", str(repo), "--target",
              str(linked_dir / ".." / "linked" / "mcp.json"))
    expect_clean_cli(res, 1, "merge-config through a linked directory with a './..' spelling")

    res = run("probe", "--repo", str(repo), "--target", str(linked_dir / "mcp.json"))
    expect_clean_cli(res, 1, "probe through a linked directory escaping the repository")
    check("outside the repository root" in res.stderr,
          f"the probe must refuse a linked --target too: {res.stderr!r}")

    # A link over an existing FILE outside the repository: writing through it would edit a file the
    # repository does not own. Creating a FILE symlink still needs the Windows privilege, so this
    # half is skipped where the link cannot be created — the directory half above always covers the
    # containment contract.
    linked_file = repo / "config.json"
    try:
        linked_file.symlink_to(written(outside / "secret.json", "{}\n"))
    except (OSError, NotImplementedError) as exc:
        print(f"note: skipping the file-link escape case — no file symlink here ({exc})")
        return
    res = run("merge-config", "--repo", str(repo), "--target", str(linked_file))
    expect_clean_cli(res, 1, "merge-config through a linked file escaping the repository")
    check("outside the repository root" in res.stderr,
          f"a linked file --target must be refused: {res.stderr!r}")
    check((outside / "secret.json").read_text(encoding="utf-8") == "{}\n",
          "the file behind the link must be untouched")


SECRET = "s3cr3t-token-DO-NOT-ECHO"


def test_diagnostics_never_echo_credentials(tmp: pathlib.Path) -> None:
    """No human or structured diagnostic may echo a value an MCP entry supplies."""
    repo = platform_repo(tmp / "secrets")
    payload = {"mcpServers": {fm.SERVER_NAME: {
        "command": f"cargo {SECRET}",
        "args": ["run", "--api-key", SECRET],
        "cwd": str(repo),
        "env": {"FARUKON_TOKEN": SECRET},
    }}}
    config = written(repo / ".kimi-code" / "mcp.json", json.dumps(payload, indent=2) + "\n")
    before = config.read_bytes()

    # validate-config: the human output and the --json payload name the broken KEY only.
    res = run("validate-config", "--path", str(config))
    expect_clean_cli(res, 1, "validate-config of an entry carrying a credential")
    check("command must be 'cargo'" in res.stdout and "args must be exactly" in res.stdout,
          f"the diagnostics must still name the violated invariants: {res.stdout!r}")
    check(SECRET not in res.stdout and SECRET not in res.stderr,
          f"validate-config must not echo the entry: {res.stdout!r} {res.stderr!r}")
    res = run("validate-config", "--path", str(config), "--json")
    expect_clean_cli(res, 1, "validate-config --json of an entry carrying a credential")
    check(SECRET not in res.stdout and SECRET not in res.stderr,
          f"the --json diagnostics must not echo the entry: {res.stdout!r}")

    # merge-config conflict: exit 3, bytes preserved, and neither stream may echo the entry.
    res = run("merge-config", "--repo", str(repo))
    expect_clean_cli(res, fm.EXIT_CONFLICT, "merge-config conflict on a credential entry")
    check("args" in res.stderr, f"the conflict must name the differing key: {res.stderr!r}")
    check(SECRET not in res.stdout and SECRET not in res.stderr,
          f"the conflict diagnostic must not echo the entry: {res.stdout!r} {res.stderr!r}")
    res = run("merge-config", "--repo", str(repo), "--json")
    expect_clean_cli(res, fm.EXIT_CONFLICT, "merge-config --json conflict on a credential entry")
    check(SECRET not in res.stdout, f"the --json conflict payload must not echo the entry: {res.stdout!r}")
    conflict = json.loads(res.stdout)["conflict"]
    check("existing" not in conflict and conflict.get("existing_keys"),
          f"the payload must carry the KEY names, never the stored values: {conflict}")
    check(config.read_bytes() == before, "a conflicting entry must never be rewritten")

    # `cwd` is a user-supplied value too: every cwd diagnostic must omit it, in the human output, in
    # --json, and in the probe (both streams), whatever the branch (missing, relative, nonexistent,
    # wrong root).
    secret_cwd = tmp / f"{SECRET}-workspace"
    secret_cwd.mkdir()
    entry = fm.managed_entry(repo)
    cwd_cases = {
        "relative": f"../{SECRET}",
        "nonexistent": str(tmp / f"{SECRET}-missing"),
        "wrong-root": str(secret_cwd),
    }
    for label, value in cwd_cases.items():
        broken = written(tmp / f"cwd-{label}.json",
                         json.dumps({"mcpServers": {fm.SERVER_NAME: entry | {"cwd": value}}},
                                    indent=2) + "\n")
        res = run("validate-config", "--path", str(broken))
        check(SECRET not in res.stdout and SECRET not in res.stderr,
              f"validate-config ({label} cwd) must not echo the value: {res.stdout!r}")
        res = run("validate-config", "--path", str(broken), "--json")
        check(SECRET not in res.stdout and SECRET not in res.stderr,
              f"validate-config --json ({label} cwd) must not echo the value: {res.stdout!r}")

    probe_repo = platform_repo(tmp / "secrets-probe")
    entry = fm.managed_entry(probe_repo)
    wrong_root = written(probe_repo / ".kimi-code" / "mcp.json",
                         json.dumps({"mcpServers": {fm.SERVER_NAME: entry | {"cwd": str(secret_cwd)}}},
                                    indent=2) + "\n")
    res = run("probe", "--repo", str(probe_repo), "--target", str(wrong_root))
    expect_clean_cli(res, 0, "probe of a config whose cwd names another directory")
    check("managed platform root" in res.stdout,
          f"the probe must name the managed root it expects: {res.stdout!r}")
    check(SECRET not in res.stdout and SECRET not in res.stderr,
          f"the probe must not echo the stored cwd: {res.stdout!r} {res.stderr!r}")
    res = run("probe", "--repo", str(probe_repo), "--target", str(wrong_root), "--json")
    payload = json.loads(res.stdout)
    check(payload["config_valid"] is False and payload["farukon_usable"] is False,
          f"a cwd outside the platform root must be unusable: {payload['config_problems']}")
    check(SECRET not in res.stdout,
          f"the --json probe must not echo the stored cwd: {res.stdout!r}")
    check(any("managed platform root" in p for p in payload["config_problems"]),
          f"the probe must name the managed root: {payload['config_problems']}")


# --------------------------------------------------------------------- validate-config

def test_validate_config(tmp: pathlib.Path) -> None:
    repo = platform_repo(tmp / "validated")
    config = repo / ".kimi-code" / "mcp.json"
    run("merge-config", "--repo", str(repo))
    ok, problems = fm.validate_config(config)
    check(ok and problems == [], f"a merged config must be valid: {problems}")
    res = run("validate-config", "--path", str(config), "--json")
    expect_clean_cli(res, 0, "validate-config ok")
    payload = json.loads(res.stdout)
    check(payload["ok"] is True and payload["problems"] == [] and payload["path"],
          f"--json must expose path/ok/problems: {payload}")

    absent = written(tmp / "no-farukon.json", json.dumps({"mcpServers": {"other": {}}}) + "\n")
    ok, problems = fm.validate_config(absent)
    check(ok and problems == [], f"a config without the farukon entry is valid (unused path): {problems}")

    base = {"mcpServers": {fm.SERVER_NAME: fm.managed_entry(repo)}}

    def variant(mutate, label: str) -> tuple[bool, list[str]]:
        data = json.loads(json.dumps(base))
        mutate(data["mcpServers"][fm.SERVER_NAME])
        return fm.validate_config(tmp / "variant.json", data)

    cases = (
        ("foreign command", lambda e: e.update({"command": "node"}), "command must be 'cargo'"),
        ("missing args", lambda e: e.pop("args"), "args must be exactly"),
        ("extra argument", lambda e: e["args"].append("--verbose"), "args must be exactly"),
        ("missing separator", lambda e: e["args"].pop(), "args must be exactly"),
        ("relative cwd", lambda e: e.update({"cwd": "farukon"}), "ABSOLUTE"),
        ("empty cwd", lambda e: e.update({"cwd": "  "}), "non-empty absolute path"),
        ("missing cwd", lambda e: e.pop("cwd"), "non-empty absolute path"),
        # An absolute cwd that cannot be entered is a launch path that cannot work: the workspace
        # has to resolve FROM that directory.
        ("nonexistent cwd", lambda e: e.update({"cwd": str(tmp / "not-there")}),
         "EXISTING directory"),
        ("cwd is a file", lambda e: e.update({"cwd": str(tmp / "task.yaml")}), "EXISTING directory"),
    )
    for label, mutate, needle in cases:
        ok, problems = variant(mutate, label)
        check(not ok, f"the {label} variant must be rejected")
        check(any(needle in p for p in problems),
              f"the {label} variant must explain {needle!r}: {problems}")

    non_object = {"mcpServers": {fm.SERVER_NAME: "cargo run"}}
    ok, problems = fm.validate_config(tmp / "non-object.json", non_object)
    check(not ok and any("must be a JSON object" in p for p in problems),
          f"a non-object entry must be rejected: {problems}")

    bad = written(tmp / "bad-cwd.json",
                  json.dumps({"mcpServers": {fm.SERVER_NAME: fm.managed_entry(repo)
                                             | {"cwd": "farukon"}}}, indent=2) + "\n")
    res = run("validate-config", "--path", str(bad))
    expect_clean_cli(res, 1, "validate-config with a relative cwd")
    check("FAIL" in res.stdout and "ABSOLUTE" in res.stdout,
          f"a violating entry must fail loudly: {res.stdout!r}")

    ok, problems = fm.validate_config(tmp / "does-not-exist.json")
    check(not ok and "not found" in problems[0],
          f"a missing config must be reported, not crash: {problems}")

    invalid = written(tmp / "invalid.json", '{\n  "mcpServers": {\n')
    res = run("validate-config", "--path", str(invalid))
    expect_clean_cli(res, 1, "validate-config invalid json")
    check("FAIL" in res.stdout, f"an invalid config must fail loudly: {res.stdout!r}")


# --------------------------------------------------------------------- probe

def test_probe(tmp: pathlib.Path) -> None:
    repo = platform_repo(tmp / "probe-repo")

    # 1. Without the managed config the probe is DEGRADED data: exit 0, config missing.
    res = run("probe", "--repo", str(repo), "--json")
    expect_clean_cli(res, 0, "probe (no config)")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["mcp_config"]["present"] is False,
          f"a missing managed config must be reported: {payload['capabilities']}")
    check(payload["farukon_usable"] is False and payload["handshake"] is None,
          f"an unusable platform path must be reported, exit 0: {payload}")
    check("mcp_config" in payload["missing"],
          f"the missing list must match the capability states: {payload['missing']}")
    for name in fm.CAPABILITY_NAMES:
        cap = payload["capabilities"][name]
        check(isinstance(cap["present"], bool) and cap["reason"].strip(),
              f"capability {name} must report presence + reason: {cap}")

    # 2. A merged config makes the config capability green; cargo presence decides the rest.
    run("merge-config", "--repo", str(repo))
    with seams(_which=lambda name: "/usr/bin/cargo" if name == "cargo" else None,
               _try_run=lambda argv, timeout=fm.VERSION_PROBE_TIMEOUT: "cargo 1.0.0"):
        result = fm.probe_capabilities(repo)
    check(result["capabilities"]["cargo"]["present"] is True,
          f"the injected cargo seam must be reported present: {result['capabilities']['cargo']}")
    check(result["capabilities"]["mcp_config"]["present"] is True and result["config_valid"],
          f"a merged config must be valid: {result['capabilities']['mcp_config']}")
    check(result["farukon_usable"] is True,
          f"cargo + buildable crate + managed config must be usable: {result}")
    check(result["missing"] == [], f"nothing must be missing in the green fixture: {result['missing']}")

    # 3. The `_which`/`_try_run` seams simulate a host without cargo: DATA, never a crash.
    with seams(_which=lambda name: None,
               _try_run=lambda argv, timeout=fm.VERSION_PROBE_TIMEOUT: None):
        degraded = fm.probe_capabilities(repo)
        degraded_checked = fm.probe_capabilities(repo, check_mcp_start=True)
    check(degraded["capabilities"]["cargo"]["present"] is False,
          f"the missing-cargo seam must degrade: {degraded['capabilities']['cargo']}")
    check("cargo" in degraded["missing"] and degraded["farukon_usable"] is False,
          f"a host without cargo must be degraded data: {degraded['missing']}")
    check(degraded_checked["capabilities"][fm.HANDSHAKE_CAPABILITY]["present"] is False
          and "cargo is missing" in degraded_checked["capabilities"][fm.HANDSHAKE_CAPABILITY]["reason"],
          f"--check-mcp-start without cargo must degrade with a reason: "
          f"{degraded_checked['capabilities']}")
    check(degraded_checked["handshake"] is None,
          "no server may be spawned when cargo is missing")

    # 3a. A cargo that is ON PATH but cannot answer `--version` is an UNPROVEN toolchain: present on
    #     the disk is not evidence that it can build anything.
    with seams(_which=lambda name: "/opt/broken/cargo" if name == "cargo" else None,
               _try_run=lambda argv, timeout=fm.VERSION_PROBE_TIMEOUT: None):
        unproven = fm.probe_capabilities(repo)
        unproven_checked = fm.probe_capabilities(repo, check_mcp_start=True)
    check(unproven["capabilities"]["cargo"]["present"] is False,
          f"a cargo whose --version fails must be unusable: {unproven['capabilities']['cargo']}")
    check("--version" in unproven["capabilities"]["cargo"]["reason"],
          f"the reason must name the failed invocation: {unproven['capabilities']['cargo']}")
    check(unproven["farukon_usable"] is False and "cargo" in unproven["missing"],
          f"an unproven toolchain must never yield a usable verdict: {unproven}")
    check(unproven_checked["capabilities"][fm.HANDSHAKE_CAPABILITY]["present"] is False
          and unproven_checked["handshake"] is None,
          f"no server may be spawned on an unproven toolchain: {unproven_checked['capabilities']}")

    # 3b. The managed entry's cwd must be THIS platform root. Another EXISTING directory is a valid
    #     absolute path, yet it launches the crate from the wrong workspace: probe says so.
    other = tmp / "another-existing-workspace"
    other.mkdir(exist_ok=True)
    mismatched = platform_repo(tmp / "probe-cwd-mismatch")
    run("merge-config", "--repo", str(mismatched))
    mismatched_config = mismatched / ".kimi-code" / "mcp.json"
    moved = json.loads(mismatched_config.read_text(encoding="utf-8"))
    moved["mcpServers"][fm.SERVER_NAME]["cwd"] = str(other)
    written(mismatched_config, json.dumps(moved, indent=2) + "\n")
    ok, problems = fm.validate_config(mismatched_config)
    check(ok and problems == [],
          f"an existing cwd is a well-formed entry for validate-config (no root known there): "
          f"{problems}")
    with seams(_which=lambda name: "/usr/bin/cargo" if name == "cargo" else None,
               _try_run=lambda argv, timeout=fm.VERSION_PROBE_TIMEOUT: "cargo 1.0.0"):
        moved_result = fm.probe_capabilities(mismatched)
    check(moved_result["config_valid"] is False and moved_result["farukon_usable"] is False,
          f"a cwd that is not the platform root must not be usable: {moved_result['config_problems']}")
    check(any("managed platform root" in p for p in moved_result["config_problems"]),
          f"the problem must name the wrong root: {moved_result['config_problems']}")
    res = run("probe", "--repo", str(mismatched), "--json")
    expect_clean_cli(res, 0, "probe with a cwd pointing at another existing directory")
    payload = json.loads(res.stdout)
    check(payload["config_valid"] is False and payload["farukon_usable"] is False,
          f"the CLI must report the same unusable verdict: {payload['config_problems']}")
    check(any("managed platform root" in p for p in payload["config_problems"]),
          f"the CLI diagnostics must name the wrong root: {payload['config_problems']}")

    # 3c. A workspace DECLARATION without its manifest is not a buildable crate: `members = [...]`
    #     naming farukon_mcp while `crates/farukon_mcp/Cargo.toml` does not exist builds nothing.
    #     A valid managed config plus a working cargo must not paper over that.
    declared_only = platform_repo(tmp / "probe-declared-only", style="workspace-declared-only")
    written(declared_only / ".kimi-code" / "mcp.json",
            json.dumps({"mcpServers": {fm.SERVER_NAME: fm.managed_entry(declared_only)}},
                       indent=2) + "\n")
    signals = fm.farukon_platform_signals(declared_only)
    check(signals["platform"] is True and signals["workspace_member"] is False
          and signals["workspace_member_manifest"] is None,
          f"a dangling workspace declaration must not be a buildable member: {signals}")
    check(any("MISSING" in detail for detail in signals["details"]),
          f"the host evidence must say the member manifest is missing: {signals['details']}")
    with seams(_which=lambda name: "/usr/bin/cargo" if name == "cargo" else None,
               _try_run=lambda argv, timeout=fm.VERSION_PROBE_TIMEOUT: "cargo 1.0.0"):
        declared_result = fm.probe_capabilities(declared_only)
    buildable_cap = declared_result["capabilities"]["farukon_mcp_buildable"]
    check(buildable_cap["present"] is False,
          f"a declared-but-missing member must not be buildable: {buildable_cap}")
    check("manifest" in buildable_cap["reason"],
          f"the miss must name the missing manifest: {buildable_cap['reason']!r}")
    check(declared_result["config_valid"] is True and declared_result["farukon_usable"] is False,
          f"a valid config and a working cargo cannot make it usable: {declared_result}")
    check("farukon_mcp_buildable" in declared_result["missing"],
          f"the buildable crate must be reported missing: {declared_result['missing']}")
    res = run("probe", "--repo", str(declared_only), "--json")
    expect_clean_cli(res, 0, "probe of a repository with a dangling workspace declaration")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["farukon_mcp_buildable"]["present"] is False
          and payload["farukon_usable"] is False,
          f"the CLI must report the same unusable verdict: {payload['capabilities']}")
    # …and the resolved variant (manifest on disk) IS buildable, so the fix is a real resolution
    # rather than a blanket "member declarations never count".
    resolved_member = platform_repo(tmp / "probe-member-resolved", style="workspace")
    written(resolved_member / ".kimi-code" / "mcp.json",
            json.dumps({"mcpServers": {fm.SERVER_NAME: fm.managed_entry(resolved_member)}},
                       indent=2) + "\n")
    with seams(_which=lambda name: "/usr/bin/cargo" if name == "cargo" else None,
               _try_run=lambda argv, timeout=fm.VERSION_PROBE_TIMEOUT: "cargo 1.0.0"):
        resolved_result = fm.probe_capabilities(resolved_member)
    check(resolved_result["capabilities"]["farukon_mcp_buildable"]["present"] is True
          and resolved_result["farukon_usable"] is True,
          f"a workspace member WITH its manifest must stay buildable: {resolved_result}")

    # 4. A repository that does not host the platform is degraded data (exit 0), not an error.
    bare = tmp / "probe-bare"
    bare.mkdir()
    res = run("probe", "--repo", str(bare), "--json")
    expect_clean_cli(res, 0, "probe (no host signature)")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["farukon_mcp_buildable"]["present"] is False
          and payload["farukon_usable"] is False,
          f"a non-platform repository must be degraded: {payload['capabilities']}")

    # 5. --out: a directory receives the probe file, an explicit *.json is used literally.
    state_repo = platform_repo(tmp / "probe-out")
    res = run("probe", "--repo", str(state_repo), "--out", "state")
    expect_clean_cli(res, 0, "probe --out <dir>")
    out_dir = state_repo / "state" / fm.PROBE_FILE_NAME
    check(out_dir.is_file(), f"--out <dir> must write {fm.PROBE_FILE_NAME}: {list(state_repo.rglob('*'))}")
    check(json.loads(out_dir.read_text(encoding="utf-8"))["repo"] == str(state_repo),
          "the written probe must describe the probed repository")
    literal = state_repo / "state" / "custom.json"
    res = run("probe", "--repo", str(state_repo), "--out", str(literal), "--json")
    expect_clean_cli(res, 0, "probe --out <file.json>")
    check(literal.is_file(), "--out with a .json suffix must be used literally")

    # 6. Input errors are exit 1: a missing repository and an escaping --target.
    res = run("probe", "--repo", str(tmp / "no-such-repo"))
    expect_clean_cli(res, 1, "probe with a missing repository")
    check("does not exist" in res.stderr, f"a missing repository must be explained: {res.stderr!r}")
    res = run("probe", "--repo", str(repo), "--target", str(tmp / "elsewhere" / "mcp.json"))
    expect_clean_cli(res, 1, "probe with an escaping --target")
    check("outside the repository root" in res.stderr,
          f"an escaping --target must be refused: {res.stderr!r}")


# --------------------------------------------------------------------- stdio handshake

GOOD_SERVER = '''
import json, sys
TOOLS = ["farukon_build", "farukon_cargo_test", "farukon_start", "farukon_stop",
         "farukon_connector_state", "farukon_portfolio_snapshot", "farukon_message_log",
         "farukon_web_health"]
print("warmup noise that is not a protocol frame", flush=True)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    if message.get("id") is None:
        continue
    if message["method"] == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "result": {"protocolVersion": "2024-11-05",
                                     "capabilities": {"tools": {}},
                                     "serverInfo": {"name": "fake-farukon", "version": "0"}}}),
              flush=True)
    elif message["method"] == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "result": {"tools": [{"name": n, "inputSchema": {"type": "object"}}
                                               for n in TOOLS]}}), flush=True)
'''

PARTIAL_SERVER = '''
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    if message.get("id") is None:
        continue
    if message["method"] == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "result": {"protocolVersion": "2024-11-05",
                                     "serverInfo": {"name": "partial"}}}), flush=True)
    elif message["method"] == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                          "result": {"tools": [{"name": "farukon_build"}]}}), flush=True)
'''

SILENT_SERVER = '''
import sys
for _line in sys.stdin:
    pass
'''

ERROR_SERVER = '''
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    if message.get("id") is None:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"],
                      "error": {"code": -32601, "message": "no such method"}}), flush=True)
'''


def fake_server(tmp: pathlib.Path, name: str, source: str) -> list[str]:
    path = written(tmp / f"{name}.py", source)
    return [sys.executable, str(path)]


def test_handshake(tmp: pathlib.Path) -> None:
    workdir = tmp / "handshake"
    workdir.mkdir()

    result = fm.mcp_start_handshake(workdir, argv=fake_server(tmp, "good", GOOD_SERVER),
                                    first_response_timeout=30, response_timeout=30)
    check(result["ok"] is True, f"the fake server must satisfy the handshake: {result}")
    check(result["missing_tools"] == [], f"no tool may be missing: {result['missing_tools']}")
    check(list(result["tools"]) == list(fm.FARUKON_TOOLS),
          f"all eight Farukon tools must be listed: {result['tools']}")
    check(result["protocol_version"] == "2024-11-05" and result["server"] == "fake-farukon",
          f"the initialize result must be reported: {result}")
    check(result["cwd"] == str(workdir), "the handshake must run in the repository root")
    check(len(fm.FARUKON_TOOLS) == 8, "the platform contract is exactly eight tools")

    partial = fm.mcp_start_handshake(workdir, argv=fake_server(tmp, "partial", PARTIAL_SERVER),
                                     first_response_timeout=30, response_timeout=30)
    check(partial["ok"] is False, f"a partial toolset must be degraded: {partial}")
    check(len(partial["missing_tools"]) == 7 and "farukon_stop" in partial["missing_tools"],
          f"the missing tools must be named: {partial['missing_tools']}")

    silent = fm.mcp_start_handshake(workdir, argv=fake_server(tmp, "silent", SILENT_SERVER),
                                    first_response_timeout=2, response_timeout=1)
    check(silent["ok"] is False and "no initialize response" in silent["message"],
          f"a silent server must be bounded, not hang: {silent}")

    errored = fm.mcp_start_handshake(workdir, argv=fake_server(tmp, "error", ERROR_SERVER),
                                     first_response_timeout=30, response_timeout=30)
    check(errored["ok"] is False and "JSON-RPC error" in errored["message"],
          f"a JSON-RPC error response must be reported: {errored}")

    missing_binary = fm.mcp_start_handshake(workdir, argv=[str(tmp / "does-not-exist-binary")],
                                            first_response_timeout=2, response_timeout=1)
    check(missing_binary["ok"] is False and "cannot start" in missing_binary["message"],
          f"an unstartable command must be data: {missing_binary}")

    # The managed command is the documented one; only the argv seam replaces it.
    check(fm.MANAGED_ARGS == ["run", "--quiet", "-p", "farukon_mcp", "--"],
          f"the managed cargo arguments must stay the reviewed ones: {fm.MANAGED_ARGS}")


def test_handshake_is_bounded_and_cleans_up(tmp: pathlib.Path) -> None:
    """A green handshake must leave no child process behind (the fake server blocks on stdin)."""
    workdir = tmp / "handshake-cleanup"
    workdir.mkdir()
    marker = tmp / "pid.txt"
    source = (f"import os\nopen({str(marker)!r}, 'w', encoding='utf-8').write(str(os.getpid()))\n"
              + GOOD_SERVER)
    result = fm.mcp_start_handshake(workdir, argv=fake_server(tmp, "pid", source),
                                    first_response_timeout=30, response_timeout=30)
    check(result["ok"] is True, f"the fixture server must answer: {result}")
    check(marker.is_file(), "the fixture server must have started")
    pid = int(marker.read_text(encoding="utf-8").strip())
    check(not process_alive(pid), f"the child process {pid} must be terminated after the handshake")


def process_alive(pid: int) -> bool:
    """`True` when the process still runs (Windows `os.kill(pid, 0)` would terminate it)."""
    if os.name == "nt":
        res = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True,
                             text=True, errors="replace")
        return str(pid) in (res.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# --------------------------------------------------------------------- CLI contract

def test_cli_contract() -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("decide", "merge-config", "probe", "validate-config"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")

    expect_clean_cli(run("merge-config"), 2, "merge-config without --repo")
    expect_clean_cli(run("probe"), 2, "probe without --repo")
    expect_clean_cli(run("validate-config"), 2, "validate-config without --path")
    res = run("decide", "--repo", ".")
    expect_clean_cli(res, 2, "decide without --text/--task-file")
    check("--text or --task-file" in res.stderr,
          f"decide without input must be a usage error: {res.stderr!r}")
    expect_clean_cli(run("unknown-subcommand"), 2, "unknown subcommand")

    legacy = run("--help", env={**os.environ, "PYTHONIOENCODING": "cp1251"})
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        test_decide(tmp)
        test_merge_config(tmp)
        test_merge_config_write_safety(tmp)
        test_target_confinement_follows_symlinks(tmp)
        test_diagnostics_never_echo_credentials(tmp)
        test_validate_config(tmp)
        test_probe(tmp)
        test_handshake(tmp)
        test_handshake_is_bounded_and_cleans_up(tmp)
        test_cli_contract()

    print(f"PASS - farukon_mcp.py contract holds: {COUNTER['checks']} assertions over the "
          "host-signature + task-scope applicability decision (identity vocabulary alone stays off, "
          "task metadata is not scope), the byte-preserving idempotent mcp.json merge with explicit "
          "conflicts, atomic failure-reported writes, symlink-resolved target confinement and "
          "redacted diagnostics, the managed entry invariants, the fail-soft capability probe with "
          "its injectable seams (an unproven toolchain and a cwd outside the platform root are "
          "unusable), the bounded JSON-RPC handshake for all eight Farukon tools and the argparse "
          "CLI contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
