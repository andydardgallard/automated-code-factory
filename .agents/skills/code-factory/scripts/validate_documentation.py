#!/usr/bin/env python3
"""
Deterministic documentation validator for the factory-documenter subagent (zero LLM tokens).

Checks that the documenter touched ONLY documentation:
  1. No protected file (tests, configs, build manifests, lockfiles) may be modified. A test/spec
     file is recognized by a path SEGMENT (a `tests/`, `spec/` directory) AND by its file NAME/STEM,
     so the `test_*.py` files that live next to the code they test are protected too.
  2. Markdown/plain-text files are documentation by definition and are allowed.
  3. Source files may change only doc-comment/docstring lines — any changed code line is a
     violation. Lines are classified by their POSITION in the two versions (the diff hunk maps
     old↔new), so duplicated text (a code line repeated inside a docstring) cannot mask a change.
     A line counts as documentation only when nothing outside a comment SPAN sits on it: code
     before/after a `/* ... */` span — `/* doc */ return x;`, or the `*/ return x;` closing line
     of a block — is a code line, not documentation. The same span rule governs Python docstrings:
     a line that carries code after (or before) a triple-quoted span is a code line.

Usage:
  python3 validate_documentation.py check --repo <root> --baseline <dir> --files f1 f2 ... \
      [--derive [--baseline-files path=sha256hex ...]]
  python3 validate_documentation.py snapshot --repo <root> --baseline <dir> --files f1 f2 ...
  python3 validate_documentation.py baseline --repo <root> --files f1 f2 ...

`snapshot` copies the listed files into <dir> preserving relative paths (the documenter runs it
BEFORE editing). `check` compares the current files against that snapshot.

`baseline` prints the state the orchestrator has to capture BEFORE the documenter starts: one
`<path>=<sha256hex>` line per existing file, `<path>=-` for a file that does not exist (a deletion
the run already made). Its output is exactly the `--baseline-files` input.

The doc-line classifier is LANGUAGE-AWARE: a leading `#` counts as a comment only in the languages
where it is one (shell/python/ruby/...), never in the C family (a changed `#define`/`#include` is a
code change); `;` counts only where it is a comment (Clojure), `%` only in MATLAB-style `.m`, `--`
only in SQL/Lua/Haskell, and `//` only in the C/Java/JS family.

With `check --derive` the validator does not take the declared file list on faith: it computes the
changed files itself from `git -C <repo> status --porcelain` — modified TRACKED files plus
UNTRACKED (`??`) new ones, ignored (`!!`) entries excluded — and FAILS when a changed file is
missing from `--files` (an edit to, or a brand-new, unlisted source/test/config file cannot hide).
When git is unavailable or <repo> is not a git repository the mode degrades with a message and
exit code 2 (never a traceback).

`--derive --baseline-files <path>=<sha256hex>` names the run's OWN changes WITH their state,
captured by the orchestrator BEFORE the documenter started (on an implement run: the manifest's
changed+created files, plus anything else git reports as already changed; the `baseline` subcommand
prints exactly the entries to pass). A baseline path is exempted from the UNDECLARED-file comparison
ONLY while the file still is in the state that was captured: its current sha256 must equal the
recorded one (`-` records an absent file). An entry whose file changed since capture is NOT
exempted — an undeclared documenter edit to a file the run had already touched therefore fails
exactly like an undeclared edit to a file it had not, protected files included. That comparison and
nothing else is scoped: the explicit `--files` documentation-only checks are untouched, so a declared
protected file still fails. The baseline is orchestrator-supplied, never documenter-chosen.
The option is only meaningful with `--derive` (using it alone is a usage error, exit 2). Every entry
must be `<repository-relative path>=<state>`: separators are normalized, duplicates dropped, and a
blank, absolute (POSIX root, Windows drive, UNC share) or `..`-escaping entry is rejected with exit 2.
A name-only entry (no `=`) is a usage error too — name-only exemption is exactly the hole the content
hash closes — as is a malformed hash (not 64 hex characters) or one path given two different hashes.
An EMPTY list is legitimate — a run may have no pre-DOC2 changes.

Exit code 0 = PASS, 1 = FAIL (each violation printed to stderr), 2 = the deriving mode could not
run (git unavailable / not a repository). stdlib only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

PROTECTED_SUFFIXES = {
    ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".lock", ".csproj", ".sln", ".gradle", ".pom", ".xml", ".cargo",
}
TEST_PATH_PARTS = {"test", "tests", "spec", "specs", "__tests__", "conftest"}
# File-NAME markers of a test/spec file. Directory segments alone missed every `test_*.py` living
# next to the code it tests (e.g. `scripts/test_validate_documentation.py`), so a protected file is
# recognized by its name/stem too: `test_x.py`, `conftest.py`, `conftest_extra.py` (stem prefix),
# `x_test.go`, `x_spec.rb`, `x.test.ts`, `x.spec.js` (stem / name suffix).
TEST_STEM_PREFIXES = ("test_", "spec_", "conftest")
TEST_NAME_SUFFIXES = ("_test", "_spec", ".test", ".spec")

MARKDOWN_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc", ".textile"}

SOURCE_SUFFIXES = {
    ".py", ".rs", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".c", ".h", ".cpp",
    ".hpp", ".cc", ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".sql", ".lua", ".ex", ".exs", ".hs", ".clj", ".r", ".m", ".zig", ".nim",
}

# Line-comment / doc markers recognized for "this changed line is documentation", PER LANGUAGE:
# a `#define`/`#include` in a C file is a preprocessor (code) line, not a comment, so `#` counts
# only where it is one; the same holds for `;` (Clojure), `%` (MATLAB-style .m) and `--`
# (SQL/Lua/Haskell). Markup tags are language-neutral (no source code line starts with one).
_MARKUP_DOC_PREFIXES = ("<!--", "-->")
_HASH_COMMENT_SUFFIXES = {".py", ".sh", ".bash", ".rb", ".r", ".nim", ".ex", ".exs", ".php"}
_SLASH_COMMENT_SUFFIXES = {".rs", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".c", ".h",
                           ".cpp", ".hpp", ".cc", ".cs", ".swift", ".kt", ".scala", ".php",
                           ".zig", ".m"}
_DASHDASH_COMMENT_SUFFIXES = {".sql", ".lua", ".hs"}
_SEMI_COMMENT_SUFFIXES = {".clj"}
_PERCENT_COMMENT_SUFFIXES = {".m"}  # MATLAB flavour of .m; Objective-C is covered by `//`


def _doc_prefixes(rel: str) -> tuple[str, ...]:
    """Line-comment prefixes valid for the language `rel` is written in (by suffix)."""
    suffix = pathlib.PurePosixPath(rel).suffix.lower()
    prefixes = list(_MARKUP_DOC_PREFIXES)
    if suffix in _HASH_COMMENT_SUFFIXES:
        prefixes.append("#")
    if suffix in _SLASH_COMMENT_SUFFIXES:
        prefixes += ["//", "///", "//!"]
    if suffix in _DASHDASH_COMMENT_SUFFIXES:
        prefixes.append("--")
    if suffix in _SEMI_COMMENT_SUFFIXES:
        prefixes.append(";")
    if suffix in _PERCENT_COMMENT_SUFFIXES:
        prefixes.append("%")
    return tuple(prefixes)

_DOCSTRING_DELIMS = ('"""', "'''")
_BLOCK_START = "/*"          # `/*`, `/**` and `/*!` all open a C-style comment block
_BLOCK_END = "*/"


def _is_protected(rel: str) -> bool:
    """A file is out of scope for the documenter when a path SEGMENT marks a test/spec directory,
    when its NAME/STEM marks a test/spec file, or when its suffix is a config/build kind."""
    p = pathlib.PurePosixPath(rel)
    if {x.lower() for x in p.parts[:-1]} & TEST_PATH_PARTS:
        return True
    name = p.name.lower()
    stem = p.stem.lower()
    if stem in TEST_PATH_PARTS or stem.startswith(TEST_STEM_PREFIXES):
        return True
    # `x_test.go` / `x_spec.rb` / `x.test.ts` / `x.spec.js` end the STEM once the language suffix
    # is dropped; a file literally named `x.test` / `x.spec` ends the name.
    if name.endswith(TEST_NAME_SUFFIXES) or stem.endswith(TEST_NAME_SUFFIXES):
        return True
    return p.suffix.lower() in PROTECTED_SUFFIXES


def _is_markdown(rel: str) -> bool:
    return pathlib.PurePosixPath(rel).suffix.lower() in MARKDOWN_SUFFIXES


def _is_source(rel: str) -> bool:
    return pathlib.PurePosixPath(rel).suffix.lower() in SOURCE_SUFFIXES


def _c_comment_residual(s: str, in_block: bool) -> tuple[str, bool]:
    """Split `s` into C-style comment SPANS and the text outside them.

    Returns `(residual, in_block)`: `residual` is the line's text outside every `/* ... */` span
    (concatenated), `in_block` is the state for the NEXT line. A caller treats the line as
    documentation only when the residual is blank — so `/* doc */ return x;` and the closing line
    `*/ return x;` of a block are code, while a comment-only line stays documentation. The state
    is entered only by a line that OPENS a block (the caller decides), never by a stray `*/`.
    """
    out: list[str] = []
    i = 0
    if in_block:
        j = s.find(_BLOCK_END, i)
        if j < 0:
            return "", True
        i = j + len(_BLOCK_END)
    while True:
        k = s.find(_BLOCK_START, i)
        if k < 0:
            out.append(s[i:])
            return "".join(out), False
        out.append(s[i:k])
        j = s.find(_BLOCK_END, k + len(_BLOCK_START))
        if j < 0:
            return "".join(out), True
        i = j + len(_BLOCK_END)


def _next_delim(s: str, i: int) -> tuple[int, str]:
    """Position of the earliest triple quote at or after `i` plus the delimiter that matched it."""
    best, best_d = -1, ""
    for d in _DOCSTRING_DELIMS:
        k = s.find(d, i)
        if k >= 0 and (best < 0 or k < best):
            best, best_d = k, d
    return best, best_d


def _docstring_residual(s: str, in_triple: bool) -> tuple[str, bool]:
    """Split `s` into triple-quoted SPANS and the text outside them, like `_c_comment_residual`.

    Returns `(residual, in_triple)`: `residual` is the line's text outside every docstring span
    (concatenated), `in_triple` is the state for the NEXT line. A caller treats the line as
    documentation only when the residual is blank: a one-line docstring followed by `safe = 1`, and
    the closing line of a multi-line docstring followed by `+ x`, both carry code and are code
    lines, while a docstring-only line stays documentation. A span is opened and closed by the
    SAME delimiter, so a triple-double-quoted span may contain a triple-single-quote sequence.
    """
    out: list[str] = []
    i = 0
    if in_triple:
        j, d = _next_delim(s, i)
        if j < 0:
            return "", True
        i = j + len(d)
    while True:
        k, d = _next_delim(s, i)
        if k < 0:
            out.append(s[i:])
            return "".join(out), False
        out.append(s[i:k])
        j = s.find(d, k + len(d))       # the span ends with the delimiter that opened it
        if j < 0:
            return "".join(out), True
        i = j + len(d)


def _doc_mask(lines: list[str], rel: str = "") -> list[bool]:
    """Return, per line, whether that line is inside a doc comment/docstring (or is a line
    comment). Heuristic but conservative: a changed non-doc, non-blank line is treated as code.
    `rel` selects the language: a `#`/`;`/`%`/`--` prefix only counts as a comment where it is one."""
    mask: list[bool] = []
    prefixes = _doc_prefixes(rel)
    in_triple = False
    in_block = False
    for raw in lines:
        s = raw.strip()
        if not s:
            mask.append(True)  # blank lines never count as a code change
            continue
        is_doc = False
        # C-style block comment SPANS: `/*`, `/**`, `/*!` open the state, `*/` closes it. The line
        # counts as documentation only when nothing but whitespace sits OUTSIDE the comment spans:
        # `/* doc */ return x;` and the `*/ return x;` closing line carry executable code and are
        # therefore code lines (a whole-line `startswith` test let a documenter swap that code).
        if in_triple:
            residual, in_triple = _docstring_residual(s, True)
            is_doc = not residual.strip()
        elif in_block or s.startswith(_BLOCK_START):
            residual, in_block = _c_comment_residual(s, in_block)
            is_doc = not residual.strip()
        # Python triple-quoted docstring SPANS, by the same rule: `"""doc"""; safe = 1` and the
        # closing line `""" + x` carry code outside the string and are code lines.
        elif s.startswith(_DOCSTRING_DELIMS):
            residual, in_triple = _docstring_residual(s, False)
            is_doc = not residual.strip()
        elif s.startswith(prefixes):
            is_doc = True
        # No fallback for a bare `*` or `|` line: outside a block/docstring/markdown file it
        # is code (`*ptr = 1;`, `| mask = 2;`), and treating it as documentation let a code
        # edit through.
        mask.append(is_doc)
    return mask


def _changed_lines(old: list[str], new: list[str]) -> list[tuple[str, int, int]]:
    """Return the changed lines as `(text, old_index, new_index)` triples.

    The indices are taken from the diff opcodes themselves: a removed line carries its index in
    `old`, an added line its index in `new`, the other index is -1. A changed line is therefore
    located by POSITION, never by a content search: the same text may occur several times in a file
    (for example once as real code and once inside a docstring) and only the diff knows which
    occurrence changed.
    """
    out: list[tuple[str, int, int]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.extend((old[i], i, -1) for i in range(i1, i2))
        out.extend((new[j], -1, j) for j in range(j1, j2))
    return out


def snapshot(root: pathlib.Path, baseline: pathlib.Path, files: list[str]) -> None:
    for rel in files:
        src = root / rel
        if not src.is_file():
            continue
        dst = baseline / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def check(root: pathlib.Path, baseline: pathlib.Path, files: list[str]) -> list[str]:
    errors: list[str] = []
    for rel in files:
        if _is_protected(rel):
            errors.append(f"{rel}: PROTECTED file modified (tests/configs/build manifests are out of scope)")
            continue
        if _is_markdown(rel):
            continue
        if not _is_source(rel):
            errors.append(f"{rel}: unknown file kind (neither markdown nor known source suffix)")
            continue
        cur = root / rel
        base = baseline / rel
        if not cur.is_file():
            errors.append(f"{rel}: documented file does not exist after edit")
            continue
        if not base.is_file():
            # Untracked/new source file: allow only if every non-blank line is a doc line.
            mask = _doc_mask(cur.read_text(encoding="utf-8", errors="replace").splitlines(), rel)
            bad = [i + 1 for i, d in enumerate(mask) if not d]
            if bad:
                errors.append(f"{rel}: new source file contains non-doc lines {bad[:5]}")
            continue
        old = base.read_text(encoding="utf-8", errors="replace").splitlines()
        new = cur.read_text(encoding="utf-8", errors="replace").splitlines()
        changed = _changed_lines(old, new)
        if not changed:
            continue
        # A changed line is a code change if it is non-blank and not a doc line in BOTH versions.
        old_mask = _doc_mask(old, rel)
        new_mask = _doc_mask(new, rel)
        for ln, oi, ni in changed:
            if not ln.strip():
                continue
            # conservatively treat a line as code if it is code in either version; the indices
            # come from the diff hunk, so a duplicate of the same text elsewhere (e.g. inside a
            # docstring, or a doc copy inside code) can neither hide nor invent a code change.
            in_old = oi >= 0 and not old_mask[oi]
            in_new = ni >= 0 and not new_mask[ni]
            if in_old or in_new:
                errors.append(f"{rel}: code line changed: {ln.strip()[:80]}")
                break
    return errors


def derive_changed_files(root: pathlib.Path) -> tuple[list[str], str]:
    """Return the changed files of `root` from `git status --porcelain`.

    The second tuple element is "" on success, otherwise a human-readable reason (git missing,
    `root` not a repository) — the caller degrades with a message, never a traceback. UNTRACKED
    (`??`) files are part of the set: a new source/config/test file the documenter created is
    exactly as much an edit as a modified one, so leaving it out of `--files` must not hide it.
    Ignored (`!!`) entries stay out of scope — they are not the run's deliverable. `-uall` makes
    git list the files of an untracked directory separately instead of the bare `dir/` entry,
    so every entry names a file that `check()` can classify.
    """
    try:
        # `-z` + an explicit UTF-8 decode: NUL-separated and never C-quoted, so a non-ASCII path
        # arrives as the real name. `text=True` would decode git's output with the LOCALE code page
        # (cp1251 on a Russian Windows), so a name with a diacritic would come back as mojibake
        # that no declared path can match.
        proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "-z",
                               "--untracked-files=all"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git status could not run: {exc}"
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        return [], f"git status failed (rc={proc.returncode}): {stderr}"
    changed: list[str] = []
    entries = (proc.stdout or b"").decode("utf-8", "replace").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4 or entry[:2] == "!!":
            continue            # only IGNORED entries are out of scope; `??` is a new file
        path = entry[3:]
        if entry[0] in "RC" and index < len(entries):
            index += 1          # `-z` puts the ORIGINAL path in the next record
        if path:
            changed.append(path)
    return changed, ""


def _is_absolute(rel: str) -> bool:
    """True for a POSIX root path, a Windows drive path or a UNC share (already `/`-normalized)."""
    return (rel.startswith("/")                       # `/x` and `//server/share`
            or (len(rel) > 1 and rel[1] == ":" and rel[0].isalpha()))   # `C:/x`


def normalize_path_list(values: list[str]) -> tuple[list[str], list[str]]:
    """Normalize an orchestrator-supplied repository-relative path list.

    Returns `(paths, problems)`: `paths` are forward-slash, `./`-free and deduplicated (input order
    kept); `problems` names every entry the caller must reject. An EMPTY list is legitimate and
    yields no problem — a run may have no pre-DOC2 changes, and a blanket "must not be empty" rule
    would reject that real case. An entry is rejected when it is blank, absolute (POSIX root, a
    Windows drive letter, a UNC share) or carries a `..` segment: the baseline decides which files
    escape the undeclared-file comparison, so a malformed entry is a usage error, never a silent
    no-op, and `..` is refused outright rather than resolved, because resolving it would make the
    option's meaning depend on the cwd.
    """
    paths: list[str] = []
    problems: list[str] = []
    for raw in values:
        rel = raw.strip().replace("\\", "/")          # Windows and POSIX spellings compare equal
        if not rel:
            problems.append(f"{raw!r} is an empty path")
            continue
        if _is_absolute(rel):
            problems.append(f"{raw} is absolute (the list must be repository-relative)")
            continue
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if ".." in parts:
            problems.append(f"{raw} escapes the repository (`..` segment)")
            continue
        norm = "/".join(parts)
        if not norm:
            problems.append(f"{raw!r} is an empty path")
            continue
        if norm not in paths:                          # dedupe, keep the first spelling
            paths.append(norm)
    return paths, problems


# A baseline entry is `<path>=<state>`: the sha256 of the file's content at capture time, or this
# sentinel for a file that did not exist then (a deletion the run had already made). An exemption
# may therefore never be granted by NAME alone.
BASELINE_ABSENT = "-"
_SHA256_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")


def baseline_state(root: pathlib.Path, rel: str) -> str:
    """The state a baseline entry records for `rel` NOW: its sha256, `-`, or "" when unreadable.

    "" is never a valid recorded state, so an unreadable file can never match any entry and is never
    exempted — an unverifiable state is not an unchanged one.
    """
    target = root / rel
    if not target.is_file():
        return BASELINE_ABSENT
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return ""


def parse_baseline_entries(values: list[str]) -> tuple[dict[str, str], list[str]]:
    """Parse orchestrator-supplied `<path>=<sha256hex>` (or `<path>=-`) baseline entries.

    Returns `(entries, problems)`: `entries` maps a repository-relative path to the state captured
    before DOC2, `problems` names every entry the caller must reject. The hash is what makes the
    exemption sound — a path that was already changed pre-DOC2 is exempted only while its content is
    STILL the captured one, so an undeclared documenter edit there cannot hide behind the name. A
    name-only entry is therefore a usage error, not a silent "exempt forever". An entry is rejected
    when it carries no `=`, when its path is blank/absolute/`..`-escaping (see
    `normalize_path_list`), when its state is neither 64 hex characters nor the `-` sentinel, and
    when it contradicts an earlier hash for the same path. An EMPTY list is legitimate.
    """
    entries: dict[str, str] = {}
    problems: list[str] = []
    for raw in values:
        rel, sep, state = raw.strip().rpartition("=")
        if not sep:
            problems.append(f"{raw!r} carries no content state (expected "
                            f"<path>=<sha256hex>): a name-only exemption would hide an undeclared "
                            "edit to a file the run changed before DOC2")
            continue
        paths, path_problems = normalize_path_list([rel])
        if path_problems:
            problems.extend(path_problems)
            continue
        norm, state = paths[0], state.strip()
        if state != BASELINE_ABSENT and not _SHA256_RE.match(state):
            problems.append(f"{raw!r}: the state must be a sha256 (64 hex characters) or "
                            f"{BASELINE_ABSENT!r} for an absent file")
            continue
        state = state.lower()
        if norm in entries and entries[norm] != state:
            problems.append(f"{raw!r} contradicts the earlier state recorded for {norm}")
            continue
        entries.setdefault(norm, state)
    return entries, problems


def baseline_entries(root: pathlib.Path, files: list[str]) -> tuple[list[str], list[str]]:
    """Render the `<path>=<state>` entries of `files` as the orchestrator must capture them.

    Returns `(entries, problems)`; a file whose state cannot be read becomes a problem instead of an
    entry, because a baseline nobody can verify must not be passed off as captured.
    """
    entries: list[str] = []
    problems: list[str] = []
    for rel in files:
        state = baseline_state(root, rel)
        if not state:
            problems.append(f"{rel} cannot be read (the baseline must describe a verifiable state)")
            continue
        entries.append(f"{rel}={state}")
    return entries, problems


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("check", "snapshot"):
        sp = sub.add_parser(name)
        sp.add_argument("--repo", default=".", help="Project root (default: cwd)")
        sp.add_argument("--baseline", required=True, help="Baseline snapshot directory")
        sp.add_argument("--files", nargs="+", required=True, help="Files touched by the documenter")
        if name == "check":
            sp.add_argument("--derive", action="store_true",
                            help="Do not take --files on faith: compute the changed files (tracked "
                                 "edits plus untracked new ones, ignored excluded) from "
                                 "`git -C <repo> status --porcelain` and FAIL when a changed file "
                                 "is missing from --files (exit 2 when git cannot answer)")
            sp.add_argument("--baseline-files", nargs="*", metavar="PATH=STATE", default=None,
                            help="Repository-relative files the run changed BEFORE the documenter "
                                 "started, WITH the state captured then: `path=sha256hex`, or "
                                 "`path=-` for a file absent at capture (the `baseline` subcommand "
                                 "prints exactly these entries). A path is exempted from the "
                                 "--derive undeclared-file comparison ONLY while its current state "
                                 "equals the recorded one; the --files documentation-only checks are "
                                 "unaffected. Requires --derive; a name-only entry is a usage "
                                 "error; an empty list is legitimate")

    sp = sub.add_parser("baseline")
    sp.add_argument("--repo", default=".", help="Project root (default: cwd)")
    sp.add_argument("--files", nargs="+", required=True,
                    help="Files the run changed before the documenter starts (the pre-DOC2 manifest "
                         "set); their `path=state` entries are printed, one per line")

    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()

    if args.cmd == "baseline":
        rels, path_problems = normalize_path_list(args.files)
        if path_problems:
            ap.error("--files: " + "; ".join(path_problems))
        entries, entry_problems = baseline_entries(root, rels)
        if entry_problems:
            ap.error("--files: " + "; ".join(entry_problems))
        for entry in entries:
            print(entry)
        return 0

    baseline = pathlib.Path(args.baseline).resolve()

    if args.cmd == "snapshot":
        snapshot(root, baseline, args.files)
        print(f"PASS - snapshot of {len(args.files)} file(s) saved to {baseline}")
        return 0

    if args.baseline_files is not None and not args.derive:
        ap.error("--baseline-files requires --derive (it only scopes the derived changed set)")
    recorded, entry_problems = parse_baseline_entries(args.baseline_files or [])
    if entry_problems:
        ap.error("--baseline-files: " + "; ".join(entry_problems))

    errors = check(root, baseline, args.files)
    if args.derive:
        changed, reason = derive_changed_files(root)
        if reason:
            print(f"error: --derive cannot compute the changed set: {reason}", file=sys.stderr)
            return 2
        declared = {pathlib.PurePath(f).as_posix() for f in args.files}
        for rel in sorted(set(changed) - declared):
            if rel in recorded:
                # A baseline path is exempt only while it still IS what the orchestrator captured:
                # an undeclared documenter edit changes the state, so the name cannot hide it.
                if baseline_state(root, rel) == recorded[rel]:
                    continue
                errors.append(f"{rel}: changed in the repository but not declared via --files, and "
                              "modified since the pre-DOC2 baseline was captured")
                continue
            errors.append(f"{rel}: changed in the repository but not declared via --files")
    if errors:
        print("FAIL - documentation validation:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    print(f"PASS - documentation changes are documentation-only ({len(args.files)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
