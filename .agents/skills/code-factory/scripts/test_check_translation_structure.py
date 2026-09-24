#!/usr/bin/env python3
r"""
Deterministic self-test for `check_translation_structure.py` (zero LLM tokens, stdlib only).

Every case builds a throwaway git repository with a committed skeleton (markdown + Python, and a
shell script for the text family), then translates the prose or breaks the structure in the
worktree:

  - a text-only translation (prose translated, one markdown line even carrying Cyrillic) exits 0
    and names the number of compared files — `--base HEAD` behaves like the default, and two runs
    print the same bytes,
  - a removed markdown heading (`.md`) and a removed `def`/`class` (`.py`) each exit 1 with the
    marker named as `<path>: <marker> old=N new=M`,
  - a new file (absent at the base, staged so git lists it) is skipped with a stderr note and the
    run still exits 0, and a changed file whose type has no skeleton (`.json`) is skipped with a
    note as well,
  - a deleted file fails the check instead of passing silently — including a deleted file whose
    type has no skeleton (`.json`), which used to be counted as merely "skipped",
  - the text family compares non-empty lines and `#` comment lines: translated comment text keeps
    the counts (exit 0), a removed comment line does not (exit 1, both markers named),
  - a deliberately added factory rule fails without `--allow-added-rule` and passes with it (its
    markers and heading are stripped from BOTH sides), while a flag naming a different rule does
    not neutralize the addition,
  - a declared `--exclude` skips a file that is SUPPOSED to grow (history) and counts it on
    stderr, while the same growth without the flag fails the check,
  - an unusable `--root` or an unknown `--base` is an infrastructure error: exit 3 with an
    `error:` line and no traceback, never "structure preserved",
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

TOOL = pathlib.Path(__file__).with_name("check_translation_structure.py")
# A legacy Windows code page: it cannot represent `—` (U+2014), the character that used to blow
# the help up with UnicodeEncodeError.
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}
# Cyrillic written with `\u` escapes on purpose: a test file is a tracked file as well, and the
# sibling checker `check_english_only.py` counts a Cyrillic literal here as a hit.
RU = "\u041f\u0435\u0440\u0435\u0432\u043e\u0434"                # "Perevod" (translation)

# Base skeleton: 2 headings, 2 unordered items, 1 ordered item, 2 code fences, 2 factory-rule
# markers, 3 arrows (one mermaid edge + the two HTML comment closings).
DOC_BASE = """\
# Title

Intro text.

## Section

- first item
- second item

1. ordered item

<!-- factory-rule: sample-rule begin -->
Rule body.
<!-- factory-rule: sample-rule end -->

```mermaid
graph TD
  A --> B
```
"""
# Same skeleton, translated prose — the counts of every marker must be identical.
DOC_TRANSLATED = f"""\
# Title in English

Intro text translated.

## Section translated

- first item translated
- {RU} item

1. ordered item translated

<!-- factory-rule: sample-rule begin -->
Rule body translated.
<!-- factory-rule: sample-rule end -->

```mermaid
graph TD
  A --> B
```
"""
# The same document without its `## Section` heading: headings 2 -> 1, everything else unchanged.
DOC_NO_HEADING = DOC_BASE.replace("## Section\n\n", "")

# Base Python skeleton: 2 defs (one async), 1 class, 1 add_argument, 1 raise, 2 prints.
PY_BASE = '''\
"""Sample module."""
import argparse


def build() -> None:
    """Build it."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="")
    print(parser)


class Runner:
    """A runner."""

    async def run(self) -> None:
        if not self:
            raise RuntimeError("no runner")
        print(self)
'''
# Same skeleton, translated docstrings/messages and an extra comment line (comments carry no
# Python marker, so the counts must stay identical).
PY_TRANSLATED = '''\
"""Sample module, translated."""
import argparse


def build() -> None:
    """Build the thing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="")
    print(parser)  # translated comment


class Runner:
    """A translated runner."""

    async def run(self) -> None:
        if not self:
            raise RuntimeError("no runner at all")
        print(self)
'''
# The class and the async def are gone: defs 2 -> 1, classes 1 -> 0.
PY_ONE_DEF = '''\
"""Sample module."""
import argparse


def build() -> None:
    """Build it."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="")
    print(parser)
'''
# Text family: 4 non-empty lines, 3 of them `#` comments.
SH_BASE = "#!/bin/sh\n# Step one\necho hi\n# Step two\n"
SH_TRANSLATED = "#!/bin/sh\n# First step\necho hi\n# Second step\n"
SH_SHORT = "#!/bin/sh\n# Step one\necho hi\n"
# A new file deliberately carrying a DIFFERENT skeleton: a tool that compared it against an empty
# base would report every marker as a mismatch.
NEW_DOC = "# New\n\n## Also new\n\n### Third\n\n- item\n- item\n"
# The translated document plus a DELIBERATELY added rule (2 markers + their 2 arrows and, in the
# rulebook style, a `## english-only` heading): without --allow-added-rule this must fail the
# check, with the flag the added block is neutralized on both sides and the run passes.
DOC_WITH_ADDED_RULE = DOC_TRANSLATED + (
    "\n## english-only\n\n<!-- factory-rule: english-only begin -->\n"
    "New rule body.\n<!-- factory-rule: english-only end -->\n"
)


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
        expect("usage:" in text and "--base" in text,
               f"--help must print the full help, not just a usage line: {text!r}")
        expect("\u2014" in text, f"the help must keep its non-ASCII characters: {text!r}")
        expect("Traceback" not in text, f"--help must not raise a traceback: {text!r}")
    res = run("--bogus", env=LEGACY_ENV)
    text = decoded(res)
    expect(res.returncode == 2, f"an unknown flag must exit 2: {res.returncode} {text!r}")
    expect("usage:" in text, f"an unknown flag must print a usage error: {text!r}")
    expect("Traceback" not in text, f"an unknown flag must not raise a traceback: {text!r}")


def check_translation_preserved() -> None:
    """Translated prose with an untouched skeleton: exit 0, deterministic, `--base HEAD` equal."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"doc.md": DOC_BASE, "mod.py": PY_BASE})
        (repo / "doc.md").write_text(DOC_TRANSLATED, encoding="utf-8")
        (repo / "mod.py").write_text(PY_TRANSLATED, encoding="utf-8")
        expect(RU in (repo / "doc.md").read_text(encoding="utf-8"),
               "the fixture must really have been translated (a markdown line carries Cyrillic)")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"a text-only translation must exit 0: {text!r}")
        expect("ok - structure preserved (checked 2 changed files)" in text,
               f"both changed files must be compared: {text!r}")
        expect("FAIL" not in text, f"a preserved skeleton must not be reported: {text!r}")
        expect(run("--root", str(repo)).stdout == res.stdout,
               "two runs on one repository must print the same bytes")
        res_base = run("--root", str(repo), "--base", "HEAD")
        expect(res_base.returncode == 0 and decoded(res_base) == text,
               f"--base HEAD must behave like the default: {decoded(res_base)!r}")


def check_heading_removed() -> None:
    """A dropped markdown heading (structure) must fail, naming the marker and both counts."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"doc.md": DOC_BASE, "mod.py": PY_BASE})
        (repo / "doc.md").write_text(DOC_NO_HEADING, encoding="utf-8")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a removed heading must exit 1: {text!r}")
        expect("doc.md: headings old=2 new=1" in text,
               f"the mismatch must name the marker and both counts: {text!r}")
        expect("mod.py" not in text, f"an unchanged file must not be reported: {text!r}")
        expect("FAIL - 1 structural mismatch(es), 0 deleted file(s)" in text,
               f"the verdict must count the mismatches: {text!r}")
        expect("Traceback" not in text, f"a mismatch must not raise a traceback: {text!r}")


def check_def_removed() -> None:
    """A dropped `def`/`class` must fail: the Python skeleton is compared per occurrence too."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"doc.md": DOC_BASE, "mod.py": PY_BASE})
        (repo / "mod.py").write_text(PY_ONE_DEF, encoding="utf-8")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a removed def must exit 1: {text!r}")
        expect("mod.py: defs old=2 new=1" in text,
               f"the removed def must be named: {text!r}")
        expect("mod.py: classes old=1 new=0" in text,
               f"the removed class must be named: {text!r}")
        expect("doc.md" not in text, f"an unchanged file must not be reported: {text!r}")


def check_skipped_files() -> None:
    """A new file and a type without a skeleton are skipped with notes; the run still exits 0."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp),
                         {"doc.md": DOC_BASE, "data.json": '{"a": 1}\n'})
        (repo / "doc.md").write_text(DOC_TRANSLATED, encoding="utf-8")
        (repo / "data.json").write_text('{"a": 2}\n', encoding="utf-8")
        (repo / "new.md").write_text(NEW_DOC, encoding="utf-8")
        expect(git(repo, "add", "-A"), "staging the new file must succeed")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"skipped files must not fail the check: {text!r}")
        expect("ok - structure preserved (checked 1 changed files)" in text,
               f"only the comparable file must be counted: {text!r}")
        expect("note: skipped 1 new file(s) (absent at HEAD)" in text,
               f"the new file must be reported as skipped: {text!r}")
        expect("note: skipped 1 changed file(s) of a type without a skeleton" in text,
               f"the unsupported type must be reported as skipped: {text!r}")
        expect("new.md" not in text and "data.json" not in text,
               f"a skipped file must not be reported as a mismatch: {text!r}")


def check_deleted_file_fails() -> None:
    """A deleted file fails the check: a translation never removes a file."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"doc.md": DOC_BASE, "mod.py": PY_BASE})
        (repo / "mod.py").unlink()
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a deleted file must exit 1: {text!r}")
        expect("mod.py: deleted" in text, f"the deleted file must be named: {text!r}")
        expect("FAIL - 0 structural mismatch(es), 1 deleted file(s)" in text,
               f"the verdict must count the deleted file: {text!r}")
        expect("doc.md" not in text, f"an unchanged file must not be reported: {text!r}")


def check_deleted_no_skeleton_file_fails() -> None:
    """A deleted file of a type WITHOUT a skeleton fails too: skipping must not hide the removal.

    The deletion probe cannot live behind the family check: a `.json` has no skeleton, so the
    comparison is skipped, but the file is still GONE — `skipped` must never outrank `deleted`.
    """
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp),
                         {"doc.md": DOC_BASE, "data.json": '{"a": 1}\n'})
        (repo / "doc.md").write_text(DOC_TRANSLATED, encoding="utf-8")
        (repo / "data.json").unlink()
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a deleted no-skeleton file must exit 1: {text!r}")
        expect("data.json: deleted" in text, f"the deleted file must be named: {text!r}")
        expect("FAIL - 0 structural mismatch(es), 1 deleted file(s)" in text,
               f"the verdict must count the deleted file: {text!r}")
        expect("note: skipped 1 changed file(s) of a type without a skeleton" not in text,
               f"a deleted file must not be counted as merely skipped: {text!r}")
        expect("ok - structure preserved" not in text,
               f"a deleted file must never print the preserved verdict: {text!r}")


def check_text_family() -> None:
    """`.sh` files are compared by non-empty lines and `#` comment lines."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"run.sh": SH_BASE})
        (repo / "run.sh").write_text(SH_TRANSLATED, encoding="utf-8")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 0, f"translated comment text must keep the counts: {text!r}")
        expect("ok - structure preserved (checked 1 changed files)" in text,
               f"the shell script must be compared: {text!r}")
        (repo / "run.sh").write_text(SH_SHORT, encoding="utf-8")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"a removed comment line must exit 1: {text!r}")
        expect("run.sh: comment_lines old=3 new=2" in text,
               f"the comment count must be named: {text!r}")
        expect("run.sh: non_empty_lines old=4 new=3" in text,
               f"the non-empty line count must be named: {text!r}")


def check_allow_added_rule() -> None:
    """A deliberately added rule fails without the flag and passes with it (stripped both sides)."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"doc.md": DOC_BASE})
        (repo / "doc.md").write_text(DOC_WITH_ADDED_RULE, encoding="utf-8")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"an undeclared added rule must exit 1: {text!r}")
        expect("doc.md: factory_rules old=2 new=4" in text,
               f"the added markers must be named without the flag: {text!r}")
        res = run("--root", str(repo), "--allow-added-rule", "english-only")
        text = decoded(res)
        expect(res.returncode == 0, f"a declared added rule must exit 0: {text!r}")
        expect("ok - structure preserved (checked 1 changed files)" in text,
               f"the declared addition must be neutralized on both sides: {text!r}")
        res = run("--root", str(repo), "--allow-added-rule", "other-rule")
        expect(res.returncode == 1,
               f"a flag naming a DIFFERENT rule must not neutralize the addition: {decoded(res)!r}")


def check_exclude() -> None:
    """A declared --exclude skips a legitimately grown file; without it the same growth fails."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        repo = make_repo(pathlib.Path(raw_tmp), {"CHANGELOG.md": DOC_BASE})
        (repo / "CHANGELOG.md").write_text(DOC_BASE + "\n## v2\n\n- new entry\n",
                                           encoding="utf-8")
        res = run("--root", str(repo))
        text = decoded(res)
        expect(res.returncode == 1, f"an undeclared history growth must exit 1: {text!r}")
        res = run("--root", str(repo), "--exclude", "CHANGELOG.md")
        text = decoded(res)
        expect(res.returncode == 0, f"a declared --exclude must exit 0: {text!r}")
        expect("note: skipped 1 excluded file(s) (declared --exclude)" in text,
               f"the excluded file must be counted on stderr: {text!r}")
        expect("ok - structure preserved (checked 0 changed files)" in text,
               f"an excluded file must not be compared: {text!r}")


def check_infrastructure_error() -> None:
    """An unusable root or base is exit 3 — never "structure preserved", never a traceback."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        res = run("--root", str(tmp / "missing"))
        text = decoded(res)
        expect(res.returncode == 3, f"an unusable --root must exit 3: {res.returncode} {text!r}")
        expect("error:" in text and "ok -" not in text,
               f"an unusable --root must print an error and no verdict: {text!r}")
        expect("Traceback" not in text, f"an unusable --root must not raise a traceback: {text!r}")
        repo = make_repo(tmp, {"doc.md": DOC_BASE})
        res = run("--root", str(repo), "--base", "nosuch")
        text = decoded(res)
        expect(res.returncode == 3, f"an unknown --base must exit 3: {res.returncode} {text!r}")
        expect("error:" in text and "ok -" not in text,
               f"an unknown --base must print an error and no verdict: {text!r}")
        expect("Traceback" not in text, f"an unknown --base must not raise a traceback: {text!r}")


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
            ("translation_preserved", check_translation_preserved),
            ("heading_removed", check_heading_removed),
            ("def_removed", check_def_removed),
            ("skipped_files", check_skipped_files),
            ("deleted_file_fails", check_deleted_file_fails),
            ("deleted_no_skeleton_file_fails", check_deleted_no_skeleton_file_fails),
            ("text_family", check_text_family),
            ("allow_added_rule", check_allow_added_rule),
            ("exclude", check_exclude),
            ("infrastructure_error", check_infrastructure_error),
        ]
    passed = sum(1 for name, fn in cases if case(name, fn))
    failed = len(cases) - passed
    if failed:
        print(f"FAIL - check_translation_structure.py: {failed}/{len(cases)} case(s) failed")
        return 1
    print(f"PASS - check_translation_structure.py behaves as expected ({passed} case(s): a "
          "text-only translation passes, a removed heading/def fails with the marker named, new "
          "and unsupported files are skipped with notes, a deleted file fails, and the help "
          "survives a cp1251 console).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
