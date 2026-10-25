#!/usr/bin/env python3
r"""
Deterministic self-test for `check_english_only.py` (zero LLM tokens, stdlib only).

Every repository case builds a throwaway git repository, because the tool scans exactly what the
repository ships (`git ls-files`):

  - a clean repository exits 0 and the summary counts the scanned files,
  - Cyrillic planted in a tracked file exits 1 and is printed as `<path>:<lineno>: <line>`,
  - Cyrillic inside the allowed carriers (`CHANGELOG.md`, `memory/x.md`, `task.yaml`,
    `.code-factory/`) is not a hit — including a nested `sub/task-2.yaml`, which the `task*.yaml`
    pattern catches by basename,
  - an extra `--exclude` pattern is honoured in both accepted forms (path prefix and fnmatch),
  - an untracked file is out of scope, exactly as `git ls-files` defines the scope,
  - a `--root` git cannot answer for is an infrastructure error: exit 3 with an `error:` line on
    stderr and no traceback, never a clean verdict,
  - the checker's OWN source, committed into a repository, scans clean: it detects the Cyrillic
    block through `\u` escapes, so the proof never has to exempt its own tool,
  - the CLI contract holds under a legacy console: `--help` exits 0 (also with
    `PYTHONIOENCODING=cp1251`, where a non-ASCII help would otherwise raise UnicodeEncodeError)
    and an unknown flag exits 2, both without a traceback,
  - the MEMORY PASS (on by default) scans only the records that are NEW by the documented v2
    predicate: a v2 record with Cyrillic exits 1 and names `memory/change-log.md`, the same text in
    a pre-v2 record (`factory_version: 12.8.0`, no v2 field) exits 0, a heading listed in
    `memory/.english-freeze` stays silent while a new heading does not, `--freeze` writes that file
    from the current journal, `--no-memory` is the documented escape, and a repository without
    `memory/` keeps the generic behaviour plus a stderr note (never a silent "clean"),
  - `memory/summary.md` is scanned WHOLE (every run rewrites it): a Russian paragraph appended to a
    committed summary exits 1 and is printed as `<path>:<lineno>: <line>`, the same repository is
    green under `--no-memory`, and a repository whose `memory/` exists but whose `memory_project`
    sibling cannot be imported exits 3 (`FAIL - the memory pass could not run`), never `ok`.

Cases are printed as `PASS <case>` / `FAIL <case>: <reason>` and summarised at the end.
Exit code 0 = every case passed, 1 = a case did not behave as expected.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("check_english_only.py")
# A legacy Windows code page: it cannot represent `—` (U+2014, the em dash in the help text), the
# character that used to blow the help up with UnicodeEncodeError.
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}
# Cyrillic written with `\u` escapes on purpose: this test file is a tracked file as well, and the
# checker it drives counts a Cyrillic literal here as a hit.
RU = "\u041f\u0440\u0438\u0432\u0435\u0442"                      # "Privet" (Hello)
RU_NEW = "\u041f\u043e\u043a\u0430"                              # "Poka" (Bye) — a second marker
MEMORY = "memory/change-log.md"
SUMMARY = "memory/summary.md"
FREEZE = "memory/.english-freeze"
JOURNAL_HEAD = "# Change Log - Test\n\n<!-- code-factory-memory: change-log -->\n\n"


def v2_record(title: str, *, stamp: str = "2026-01-01T00:00:00+0300",
              text: str = "") -> str:
    """One journal record NEW by the documented v2 predicate (`run_id` + provenance marks).

    `text` lands inside `results:`; the heading and the other fields stay ASCII, so a hit can be
    attributed to exactly one line.
    """
    return (f"## {stamp} \u2014 {title}\n"
            "title: a test record\n"
            "project: repo\n"
            f"timestamp: {stamp}\n"
            "run_id: 20260101-1a2b3c4d\n"
            f"results: integration=PASS [verified: log] {text}\n"
            "decisions: kept the record [verified: log]\n"
            "factory_version: 12.14.3\n"
            "unfinished: none\n")


def pre_v2_record(title: str, *, stamp: str = "2026-01-01T00:00:00+0300",
                  text: str = "") -> str:
    """One PRE-v2 record: `factory_version: 12.8.0` and no v2 field, i.e. history by contract."""
    return (f"## {stamp} \u2014 {title}\n"
            "title: a legacy record\n"
            "project: repo\n"
            f"timestamp: {stamp}\n"
            f"goal: {text}\n"
            "factory_version: 12.8.0\n"
            "unfinished: none\n")


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run the tool; bytes are kept so the output can be judged exactly, not through a locale."""
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, env=env)


def decoded(res: subprocess.CompletedProcess[bytes]) -> str:
    """The tool forces UTF-8 on its own streams, so its bytes are UTF-8 whatever the console is."""
    return (res.stdout + res.stderr).decode("utf-8", "replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def git(repo: pathlib.Path, *args: str, commit: bool = False) -> bool:
    """Run one git command in the fixture repo; True on success."""
    cmd = ["git", "-C", str(repo)]
    if commit:  # identity and signing per command: the user's ~/.gitconfig must not decide this
        cmd += ["-c", "user.name=Self Test", "-c", "user.email=self-test@example.com",
                "-c", "commit.gpgsign=false"]
    return subprocess.run(cmd + list(args), capture_output=True).returncode == 0


def make_repo(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Throwaway repository with `files` committed as the base revision."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    expect(git(repo, "init", "-q"), "git init must succeed")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    expect(git(repo, "add", "-A"), "git add must succeed")
    expect(git(repo, "commit", "-q", "-m", "base", commit=True), "the base commit must succeed")
    return repo


def check_help() -> None:
    """`--help` exits 0 with the full help — also on a cp1251 console (the UTF-8 guard)."""
    for env in (None, LEGACY_ENV):
        res = run("--help", env=env)
        text = decoded(res)
        expect(res.returncode == 0, f"--help must exit 0 (env={env is not None}): {text!r}")
        expect("usage:" in text and "--exclude" in text,
               f"--help must print the full help, not just a usage line: {text!r}")
        expect("\u2014" in text,
               f"the help must keep its non-ASCII characters: {text!r}")
        expect("Traceback" not in text, f"--help must not raise a traceback: {text!r}")
    res = run("--bogus", env=LEGACY_ENV)
    text = decoded(res)
    expect(res.returncode == 2, f"an unknown flag must exit 2: {res.returncode} {text!r}")
    expect("usage:" in text, f"an unknown flag must print a usage error: {text!r}")
    expect("Traceback" not in text, f"an unknown flag must not raise a traceback: {text!r}")


def check_clean_repo() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"app.py": "value = 1\n"})
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"a clean repository must exit 0: {text!r}")
        expect("ok - no cyrillic outside exceptions (scanned 1 files)" in text,
               f"the summary must count the scanned files: {text!r}")


def check_planted_cyrillic() -> None:
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp),
                         {"app.py": "value = 1\n", "notes.md": f"# Notes\n\n{RU}!\n"})
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"Cyrillic in a tracked file must exit 1: {text!r}")
        expect("notes.md:3: " in text,
               f"the hit must be printed as <path>:<lineno>: <line>: {text!r}")
        expect("FAIL - 1 cyrillic line(s) in 1 file(s)" in text,
               f"the verdict must count the hit lines and files: {text!r}")
        expect("app.py" not in text, f"a clean file must not be listed: {text!r}")
        expect("Traceback" not in text, f"a hit must not raise a traceback: {text!r}")


def check_exceptions() -> None:
    """Cyrillic inside the allowed carriers is not a hit; only `app.py` is scanned."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            "CHANGELOG.md": f"# Changelog\n\n- {RU}\n",
            "memory/x.md": f"{RU}\n",
            "task.yaml": f"title: {RU}\n",
            "sub/task-2.yaml": f"description: {RU}\n",
            ".code-factory/state/pipeline.yaml": f"phase: {RU}\n",
        })
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"the exception carriers must not be hits: {text!r}")
        expect("scanned 1 files" in text,
               f"the exceptions must be skipped, not scanned: {text!r}")


def check_extra_exclude() -> None:
    """`--exclude` is repeatable and accepts both a path prefix and an fnmatch pattern."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp),
                         {"app.py": "value = 1\n", "notes/todo.md": f"{RU}\n",
                          "task.yaml": f"title: {RU}\n"})
        res = run("--root", str(repo))
        expect(res.returncode == 1, f"without --exclude the file must be a hit: {decoded(res)!r}")
        res = run("--root", str(repo), "--exclude", "notes/", "--exclude", "task*.yaml")
        text = decoded(res)
        expect(res.returncode == 0, f"both --exclude forms must be honoured: {text!r}")
        expect("scanned 1 files" in text, f"only app.py is left to scan: {text!r}")
        res = run("--root", str(repo), "--exclude", "*.md", "--exclude", "task.yaml")
        expect(res.returncode == 0, f"an fnmatch pattern must be honoured: {decoded(res)!r}")


def check_untracked_out_of_scope() -> None:
    """The scan covers what the repository ships (`git ls-files`), not untracked scratch files."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"app.py": "value = 1\n"})
        (repo / "scratch.md").write_text(f"{RU}\n", encoding="utf-8")   # never added: not shipped
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"an untracked file must not fail the scan: {text!r}")
        expect("scanned 1 files" in text, f"the untracked file must not be scanned: {text!r}")


def check_infrastructure_error() -> None:
    """A root git cannot answer for is exit 3 — never a clean verdict, never a traceback."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        res = run("--root", str(pathlib.Path(raw_tmp) / "missing"))
        text = decoded(res)
        expect(res.returncode == 3, f"an unusable --root must exit 3: {res.returncode} {text!r}")
        expect("error:" in text, f"an unusable --root must print an error: {text!r}")
        expect("FAIL" not in text and "ok -" not in text,
               f"an unusable --root must not print a verdict: {text!r}")
        expect("Traceback" not in text, f"an unusable --root must not raise a traceback: {text!r}")


def check_tool_source_is_clean() -> None:
    """The checker's own source is Cyrillic-free, so the proof never exempts its own tool."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        source = TOOL.read_text(encoding="utf-8")
        repo = make_repo(pathlib.Path(raw_tmp), {TOOL.name: source})
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"{TOOL.name} must scan clean in a repository: {text!r}")
        expect("scanned 1 files" in text, f"the committed copy must be scanned: {text!r}")


def check_memory_v2_hit() -> None:
    """A v2 record with Cyrillic is NEW memory: the memory pass fails and names the journal."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            MEMORY: JOURNAL_HEAD + v2_record("Fresh record", text=RU),
        })
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a v2 record with Cyrillic must exit 1: {text!r}")
        expect(f"{MEMORY}:" in text,
               f"the memory hit must be printed as <path>:<lineno>: <line>: {text!r}")
        expect("memory: 1 v2 record(s) + summary scanned, 1 hit(s)" in text,
               f"the memory pass must report its own counts: {text!r}")
        expect("FAIL - 1 cyrillic line(s) in 1 file(s)" in text,
               f"a memory hit must join the shared FAIL verdict: {text!r}")


def check_memory_pre_v2_exempt() -> None:
    """The same text in a pre-v2 record is history: never scanned, so the run stays green."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            MEMORY: JOURNAL_HEAD + pre_v2_record("Old record", text=RU),
        })
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"a pre-v2 record is history and must pass: {text!r}")
        expect("memory: 0 v2 record(s) + summary scanned, 0 hit(s)" in text,
               f"a pre-v2 record must not be scanned at all: {text!r}")
        expect(f"{MEMORY}:" not in text, f"a pre-v2 record must not be reported: {text!r}")


def check_memory_freeze() -> None:
    """`--freeze` covers the CURRENT journal; a later Cyrillic record is still a hit."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            MEMORY: JOURNAL_HEAD + v2_record("Accepted record", stamp="2026-01-01T00:00:00+0300",
                                             text=RU),
        })
        res = run("--root", str(repo), "--freeze")
        text = decoded(res)
        expect(res.returncode == 0, f"--freeze must succeed: {text!r}")
        freeze_file = repo / FREEZE
        expect(freeze_file.is_file(), f"--freeze must write {FREEZE}: {text!r}")
        entries = freeze_file.read_text(encoding="utf-8")
        expect("## 2026-01-01T00:00:00+0300" in entries,
               f"the frozen record heading must be listed: {entries!r}")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"a frozen heading must stay silent: {text!r}")
        expect("memory: 0 v2 record(s) + summary scanned, 0 hit(s)" in text,
               f"a frozen record must not be scanned: {text!r}")
        expect(f"{MEMORY}:" not in text, f"a frozen record must not be reported: {text!r}")
        # A NEW Cyrillic record written after the freeze is not covered by it.
        journal = repo / MEMORY
        journal.write_text(JOURNAL_HEAD
                           + v2_record("Accepted record", stamp="2026-01-01T00:00:00+0300",
                                       text=RU)
                           + v2_record("New record", stamp="2026-02-02T00:00:00+0300",
                                       text=RU_NEW),
                           encoding="utf-8")
        expect(git(repo, "add", "-A"), "git add must succeed")
        expect(git(repo, "commit", "-q", "-m", "new record", commit=True),
               "the follow-up commit must succeed")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a new Cyrillic record must exit 1: {text!r}")
        expect(RU_NEW in text, f"the new record must be reported: {text!r}")
        expect(RU not in text, f"the frozen record must stay silent: {text!r}")
        expect("memory: 1 v2 record(s) + summary scanned, 1 hit(s)" in text,
               f"only the new record may be scanned: {text!r}")


def check_memory_opt_out() -> None:
    """`--no-memory` is the deliberate escape: the same repository is red by default and green."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            MEMORY: JOURNAL_HEAD + v2_record("Fresh record", text=RU),
        })
        res = run("--root", str(repo), "--no-memory")
        text = decoded(res)
        expect(res.returncode == 0, f"--no-memory must skip the memory pass: {text!r}")
        expect("memory:" not in text, f"--no-memory must print no memory count: {text!r}")
        expect("deliberate escape" in text,
               f"--no-memory must say that the escape is deliberate: {text!r}")
        res = run("--root", str(repo))
        expect(res.returncode == 1,
               f"without the escape the same repository must fail: {decoded(res)!r}")


def check_memory_absent() -> None:
    """No `memory/`: the generic scan is unchanged, with a note instead of a silent pass."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"app.py": "value = 1\n"})
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"a repository without memory/ must pass: {text!r}")
        expect("ok - no cyrillic outside exceptions (scanned 1 files)" in text,
               f"the generic scan must be unchanged: {text!r}")
        expect("memory:" not in text,
               f"a skipped memory pass must not print a count: {text!r}")
        expect("memory pass skipped" in text,
               f"a skipped memory pass must say so on stderr: {text!r}")


def check_summary_hit() -> None:
    """`memory/summary.md` is REWRITTEN by every run, so it is scanned whole — no freeze, no v2 rule."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            SUMMARY: ("# Project Summary\n\n<!-- code-factory-memory: summary -->\n"
                      "project: repo\n\n## Current state\n"
                      f"{RU} {RU} {RU}\n"),
        })
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a Russian paragraph in the summary must exit 1: {text!r}")
        expect(f"{SUMMARY}:7: " in text,
               f"the summary hit must be printed as <path>:<lineno>: <line>: {text!r}")
        expect("memory: 0 v2 record(s) + summary scanned, 1 hit(s)" in text,
               f"the summary hit must be counted by the memory pass: {text!r}")
        expect("FAIL - 1 cyrillic line(s) in 1 file(s)" in text,
               f"the summary hit must join the shared FAIL verdict: {text!r}")


def check_summary_opt_out() -> None:
    """`--no-memory` disables BOTH halves of the memory pass, the summary included."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {
            "app.py": "value = 1\n",
            SUMMARY: ("# Project Summary\n\n<!-- code-factory-memory: summary -->\n"
                      "project: repo\n\n## Current state\n"
                      f"{RU} {RU} {RU}\n"),
        })
        expect(run("--root", str(repo)).returncode == 1,
               f"without the escape the summary must fail the gate: {decoded(run('--root', str(repo)))!r}")
        res = run("--root", str(repo), "--no-memory")
        text = decoded(res)
        expect(res.returncode == 0, f"--no-memory must skip the summary scan as well: {text!r}")
        expect(f"{SUMMARY}:" not in text, f"no summary hit may be printed: {text!r}")
        expect("memory:" not in text, f"--no-memory must print no memory count: {text!r}")


def check_memory_infra_error() -> None:
    """An internal reason the memory pass cannot run is INFRASTRUCTURE (exit 3), never a proof."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        repo = make_repo(tmp, {"app.py": "value = 1\n",
                               MEMORY: JOURNAL_HEAD + v2_record("Fresh record", text=RU)})
        # A copy of the checker WITHOUT its sibling `memory_project.py`: the import fails, exactly
        # like a broken deployment. The `memory/` of the repository exists, so the pass has to run.
        lonely = tmp / "lonely"
        lonely.mkdir()
        (lonely / TOOL.name).write_text(TOOL.read_text(encoding="utf-8"), encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        res = subprocess.run([sys.executable, str(lonely / TOOL.name), "--root", str(repo)],
                             capture_output=True, cwd=str(lonely), env=env)
        text = decoded(res)
        expect(res.returncode == 3,
               f"an unimportable memory pass must exit 3: {res.returncode} {text!r}")
        expect("FAIL - the memory pass could not run" in text,
               f"the infrastructure error must be named: {text!r}")
        expect("memory_project" in text,
               f"the error must name the reason (the missing sibling): {text!r}")
        expect("ok - no cyrillic" not in text,
               f"an impossible memory pass must never print the language proof: {text!r}")
        expect("Traceback" not in text, f"an import failure must not raise a traceback: {text!r}")


def case(name: str, fn) -> bool:
    """Run one case; report PASS/FAIL instead of aborting the whole suite on the first failure."""
    try:
        fn()
    except AssertionError as exc:
        print(f"FAIL {name}: {exc}")
        return False
    print(f"PASS {name}")
    return True


def main() -> int:
    if shutil.which("git") is None:
        print("SKIP - git is not on PATH: every repository case is skipped")
        cases = [("help", check_help)]
    else:
        cases = [
            ("help", check_help),
            ("clean_repo", check_clean_repo),
            ("planted_cyrillic", check_planted_cyrillic),
            ("exceptions", check_exceptions),
            ("extra_exclude", check_extra_exclude),
            ("untracked_out_of_scope", check_untracked_out_of_scope),
            ("infrastructure_error", check_infrastructure_error),
            ("tool_source_is_clean", check_tool_source_is_clean),
            ("memory_v2_hit", check_memory_v2_hit),
            ("memory_pre_v2_exempt", check_memory_pre_v2_exempt),
            ("memory_freeze", check_memory_freeze),
            ("memory_opt_out", check_memory_opt_out),
            ("memory_absent", check_memory_absent),
            ("summary_hit", check_summary_hit),
            ("summary_opt_out", check_summary_opt_out),
            ("memory_infra_error", check_memory_infra_error),
        ]
    passed = sum(1 for name, fn in cases if case(name, fn))
    failed = len(cases) - passed
    if failed:
        print(f"FAIL - check_english_only.py: {failed}/{len(cases)} case(s) failed")
        return 1
    print(f"PASS - check_english_only.py behaves as expected ({passed} case(s): a clean repository "
          "passes, planted Cyrillic fails with the file named, the exception carriers and "
          "untracked files stay out of scope, an unusable root is exit 3 instead of 'clean', the "
          "memory pass catches only NEW (v2, unfrozen) records AND scans the whole summary, an "
          "internal reason the memory pass cannot run is exit 3 instead of 'ok', and the help "
          "survives a cp1251 console).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
