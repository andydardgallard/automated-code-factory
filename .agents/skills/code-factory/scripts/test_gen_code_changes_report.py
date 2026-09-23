#!/usr/bin/env python3
"""
Deterministic self-test for `gen_code_changes_report.py` (zero LLM tokens, stdlib only).

The report generator's `--help` text is Russian and carries `→`, which a Windows console whose
code page is a legacy one (cp866/cp1251) cannot encode: argparse used to die with UnicodeEncodeError
and a traceback instead of printing help. Every check below runs the tool in that torture
environment (`PYTHONIOENCODING=cp1251`) and asserts:
  - `--help` exits 0, prints the whole help (the `→` included — the text must not have been stripped
    down to ASCII) and never a traceback,
  - an unknown flag still answers with a usage error on stderr and exit 2, never a traceback,
  - a real run in a throwaway git repository (two commits: a modified line and an added file) writes
    the report to `--out`, exiting 0.

Without git on PATH the third check is skipped with a note; the encoding contract is still covered.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("gen_code_changes_report.py")
# A legacy Windows code page: it cannot represent `→` (U+2192), the character that used to blow up.
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run the tool; bytes are kept so the output can be judged exactly, not through a locale."""
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, env=env)


def decoded(res: subprocess.CompletedProcess[bytes]) -> str:
    """The tool forces UTF-8 on its own streams, so its bytes are UTF-8 whatever the console is."""
    return (res.stdout + res.stderr).decode("utf-8", "replace")


def git(repo: pathlib.Path, *args: str, commit: bool = False) -> bool:
    """Run one git command in the fixture repo; True on success."""
    cmd = ["git", "-C", str(repo)]
    if commit:  # identity and signing per command: the user's ~/.gitconfig must not decide this
        cmd += ["-c", "user.name=Self Test", "-c", "user.email=self-test@example.com",
                "-c", "commit.gpgsign=false"]
    return subprocess.run(cmd + list(args), capture_output=True).returncode == 0


def check_help() -> None:
    res = run("--help", env=LEGACY_ENV)
    text = decoded(res)
    expect(res.returncode == 0, f"--help must exit 0 under PYTHONIOENCODING=cp1251: {text!r}")
    expect("Traceback" not in text, f"--help must not raise a traceback: {text!r}")
    expect("usage:" in text and "--run-id" in text,
           f"--help must print the full help, not just a usage line: {text!r}")
    expect("\u2192" in text,
           "the help must keep its non-ASCII characters (nothing was stripped down to ASCII)")


def check_unknown_flag() -> None:
    res = run("--bogus", env=LEGACY_ENV)
    text = decoded(res)
    expect(res.returncode == 2, f"an unknown flag must exit 2: {res.returncode} {text!r}")
    expect("Traceback" not in text, f"an unknown flag must not raise a traceback: {text!r}")
    expect("usage:" in text, f"an unknown flag must print a usage error: {text!r}")


def check_report() -> None:
    """A throwaway git repo whose HEAD changes one line, so the report has a was → became row."""
    if shutil.which("git") is None:
        print("SKIP - report generation (git is not on PATH)")
        return
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        repo, out = tmp / "src", tmp / "out"
        repo.mkdir()
        expect(git(repo, "init", "-q"), "git init must succeed")
        (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        expect(git(repo, "add", "-A") and git(repo, "commit", "-q", "-m", "start", commit=True),
               "the first commit must succeed")
        (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
        (repo / "extra.py").write_text("added = True\n", encoding="utf-8")
        expect(git(repo, "add", "-A") and git(repo, "commit", "-q", "-m", "change", commit=True),
               "the second commit must succeed")

        report = out / "report_code_changes.md"
        res = run("--repo", str(repo), "--commit", "HEAD", "--out", str(report), "--run-id", "test-1")
        text = decoded(res)
        expect(res.returncode == 0, f"report generation must exit 0: {text!r}")
        expect("Traceback" not in text, f"report generation must not raise a traceback: {text!r}")
        expect(report.is_file(), f"the report must be written to --out: {report}")
        content = report.read_text(encoding="utf-8")
        expect("test-1" in content and "app.py" in content and "extra.py" in content,
               f"the report must name the run id and the changed files: {content!r}")
        expect("value = 1" in content and "value = 2" in content,
               f"both sides of the changed line must be in the report: {content!r}")
        expect("\u2192" in content,
               f"the report must keep its non-ASCII was → became header: {content!r}")


def main() -> int:
    check_help()
    check_unknown_flag()
    check_report()
    print("PASS - gen_code_changes_report.py keeps its CLI contract on a cp1251 stdout: --help "
          "prints the full (non-ASCII) help and exits 0, an unknown flag exits 2, and a real run "
          "in a git repo writes the report - never a traceback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
