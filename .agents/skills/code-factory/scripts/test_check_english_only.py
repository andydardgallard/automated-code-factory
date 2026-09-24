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
    and an unknown flag exits 2, both without a traceback.

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
        ]
    passed = sum(1 for name, fn in cases if case(name, fn))
    failed = len(cases) - passed
    if failed:
        print(f"FAIL - check_english_only.py: {failed}/{len(cases)} case(s) failed")
        return 1
    print(f"PASS - check_english_only.py behaves as expected ({passed} case(s): a clean repository "
          "passes, planted Cyrillic fails with the file named, the exception carriers and "
          "untracked files stay out of scope, an unusable root is exit 3 instead of 'clean', and "
          "the help survives a cp1251 console).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
