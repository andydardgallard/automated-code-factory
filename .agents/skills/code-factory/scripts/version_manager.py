#!/usr/bin/env python3
"""
Deterministic version manager for the Code Factory (zero LLM tokens, stdlib only).

Single source of truth: a `VERSION` file (one line `X.Y.Z`). All other files that mention the
version are synchronized FROM it — never edited by hand.

Commands:
  get                        print the current version
  bump major|minor|patch     increment the version, then sync (adds a CHANGELOG section)
  sync [--date YYYY-MM-DD]   propagate the version into every file that mentions it
  validate                   exit 0 if consistent, 1 if any file disagrees with VERSION
  set <X.Y.Z>                set the version manually, then sync
  suggest <flags...>         deterministic version-type matrix (see below)

NOTE: global options (`--repo`, `--version-file`, `--date`) must come BEFORE the subcommand,
e.g. `version_manager.py --repo . validate` (not `validate --repo .`).

`sync` updates:
  - README.md                title `# Autonomous Code Factory vX.Y.Z` + footer `Current version: **X.Y.Z**`
  - CHANGELOG.md             prepends `## [X.Y.Z] — <date>` when the top section is older
  - AGENTS.md / SKILL.md / .agents/README.md   marker `<!-- code-factory-version: X.Y.Z -->`
  - Cargo.toml / <crate>/Cargo.toml   an EXISTING literal `[workspace.package] version` or
                             `[package] version` that diverges (a field is never inserted and a
                             file is never created; `version.workspace = true` is inherited, not
                             a literal)

`validate` fails on the same files; for Rust it reads every `Cargo.toml` below the repo except
the pruned `.git`, `.code-factory`, `target`, `node_modules`, `vendor`, `dist`, `build`
directories (a member that inherits the workspace version is correct and passes). A directory is
walked only while its resolved path stays inside the repo and only once, so a symlink cycle cannot
hang the scan and a symlink leaving the repository is never read.

`suggest` (the deterministic matrix — hybrid step 1, the reviewer validates in step 2):
  --new-subagent  -> minor   (new subagent)
  --new-task-type -> minor   (new task type)
  --new-field     -> minor   (new optional field in the task format)
  --breaking      -> major   (removed/renamed field, removed subagent, changed AGENTS.md section
                              count, removed task type)
  --fix           -> patch   (bug fix, prompt improvement, perf, doc fix)
  --no-change     -> none    (review / security_audit with no factory-code change)
Priority: breaking > minor-signals > fix > no-change.
"""
from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import re
import sys

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MARKER_RE = re.compile(r"<!--\s*code-factory-version:\s*(\d+\.\d+\.\d+)\s*-->")
README_TITLE_RE = re.compile(r"^(#\s+.*?\s+v)\d+\.\d+\.\d+(\s*)$")
README_FOOTER_RE = re.compile(r"(Current version:\s*\*\*)\d+\.\d+\.\d+(\*\*)")
CHANGELOG_SECTION_RE = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]")

CARGO_MANIFEST = "Cargo.toml"
CARGO_SECTION_RE = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\-]+)\s*\]\]?")
# `version = "X.Y.Z"` (or 'X.Y.Z') on one line: prefix, quote, value, quote, the rest of the line
# (a trailing comment or the line ending — never rewritten).
CARGO_VERSION_RE = re.compile(r"^(\s*version\s*=\s*)([\"'])([^\"']*)(\2)([^\r\n]*)")
# The two Cargo sections that declare a version. A member inherits the workspace one through
# `version.workspace = true` and then declares no literal at all.
CARGO_VERSION_SECTIONS = ("workspace.package", "package")
# Never searched for manifests: VCS data, the factory's runtime tree (it may hold scratch copies
# of other projects), dependency trees and build outputs.
CARGO_PRUNED_DIRS = frozenset({".git", ".code-factory", "target", "node_modules", "vendor",
                               "dist", "build"})

# The single list of version-carrying text files. Everything below is derived from it, so the
# set cannot drift between `sync`, `file_version_reprs` and `validate`.
SYNC_FILES = ["README.md", "AGENTS.md", ".agents/skills/code-factory/SKILL.md",
              ".agents/README.md", "CHANGELOG.md"]
# CHANGELOG carries a dated section, not a marker: the marker files are everything else.
MARKER_FILES = [rel for rel in SYNC_FILES if rel != "CHANGELOG.md"]
MARKER = "<!-- code-factory-version: {v} -->"


def parse_version(s: str) -> tuple[int, int, int] | None:
    m = VERSION_RE.match(s.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def read_version(vf: pathlib.Path) -> str:
    if not vf.is_file():
        raise SystemExit(f"VERSION file not found: {vf}")
    v = vf.read_text(encoding="utf-8").strip()
    if parse_version(v) is None:
        raise SystemExit(f"VERSION file is not a single X.Y.Z line: {vf}")
    return v


def write_version(vf: pathlib.Path, v: str) -> None:
    vf.write_text(v + "\n", encoding="utf-8", newline="")


def bump(v: str, kind: str) -> str:
    maj, mn, pt = parse_version(v)
    if kind == "major":
        return f"{maj + 1}.0.0"
    if kind == "minor":
        return f"{maj}.{mn + 1}.0"
    if kind == "patch":
        return f"{maj}.{mn}.{pt + 1}"
    raise SystemExit(f"unknown bump kind: {kind}")


def ensure_marker(lines: list[str], v: str, insert_at: int) -> list[str]:
    marker = MARKER.format(v=v)
    replaced = False
    out: list[str] = []
    for ln in lines:
        if MARKER_RE.search(ln):
            out.append(marker)
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.insert(insert_at, marker)
    return out


def sync_file(path: pathlib.Path, rel: str, v: str, date: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if rel == "README.md":
        lines = ensure_marker(lines, v, insert_at=1)
        # README mentions the version twice: the title heading and the footer line.
        for i, ln in enumerate(lines):
            m = README_TITLE_RE.match(ln)
            if m:
                lines[i] = m.group(1) + v + m.group(2)
                break  # only the first versioned heading is the title
        lines = [README_FOOTER_RE.sub(lambda mo: mo.group(1) + v + mo.group(2), ln) for ln in lines]
    elif rel == "CHANGELOG.md":
        # Look at the FIRST `## [X.Y.Z]` section only; prepend a new one if it is older than v.
        for i, ln in enumerate(lines):
            m = CHANGELOG_SECTION_RE.match(ln)
            if m:
                if m.group(1) != v:
                    lines[i:i] = [f"## [{v}] — {date}", ""]
                break
    elif rel == "AGENTS.md":
        lines = ensure_marker(lines, v, insert_at=0)
    elif rel.endswith("SKILL.md"):
        # insert after the YAML frontmatter (--- ... ---)
        if lines and lines[0].strip() == "---":
            end = next((j for j in range(1, len(lines)) if lines[j].strip() == "---"), 1)
            lines = ensure_marker(lines, v, insert_at=end + 1)
        else:
            lines = ensure_marker(lines, v, insert_at=0)
    elif rel == ".agents/README.md":
        lines = ensure_marker(lines, v, insert_at=0)
    # newline="" so the explicit LF line endings are not translated to CRLF on Windows.
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


def _resolved(path: pathlib.Path) -> pathlib.Path | None:
    """`path` with every link resolved, or None when it cannot be resolved.

    A dangling link, a link loop (`ELOOP`) and an unreadable parent all land here.
    """
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return None


def _beneath(root: pathlib.Path, path: pathlib.Path) -> bool:
    """True when the RESOLVED `path` is `root` itself or lies below it."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def cargo_manifests(repo: pathlib.Path) -> list[pathlib.Path]:
    """Every `Cargo.toml` below `repo`, pruning VCS, factory-state, dependency and build dirs.

    A link is never trusted on its own: a directory is walked only while its RESOLVED path stays
    inside `repo`, and only once — every real directory is recorded in `visited`. A symlink cycle
    (an endless walk) therefore terminates, and a link leaving the repository is skipped instead of
    being read or crashing the `relative_to` that names a manifest.
    """
    if not isinstance(repo, pathlib.Path):       # a str is accepted, a Path subclass is kept as is
        repo = pathlib.Path(repo)
    root = _resolved(repo) or repo
    found: list[pathlib.Path] = []
    visited: set[str] = set()
    stack = [repo]
    while stack:
        directory = stack.pop()
        real = _resolved(directory)
        if real is None or not _beneath(root, real):
            continue                             # unreadable, a looping link or a foreign dir
        key = os.path.normcase(str(real))        # one directory where the file system folds case
        if key in visited:
            continue                             # this real directory was walked already: a cycle
        visited.add(key)
        try:
            entries = sorted(directory.iterdir())
        except OSError:                     # an unreadable directory is skipped, never fatal
            continue
        for entry in entries:
            if entry.name == CARGO_MANIFEST:
                target = _resolved(entry)
                if target is not None and _beneath(root, target) and target.is_file():
                    found.append(entry)
            elif entry.is_dir():
                if entry.name not in CARGO_PRUNED_DIRS:
                    stack.append(entry)
    return sorted(found)


def cargo_version_lines(lines: list[str]) -> list[tuple[int, str, str]]:
    """Literal Cargo versions as `(line index, section, declared version)`.

    Only `[workspace.package] version` and `[package] version` are declarations; a member's
    `version.workspace = true` inherits the workspace version and yields nothing.
    """
    found: list[tuple[int, str, str]] = []
    section = ""
    for i, ln in enumerate(lines):
        m = CARGO_SECTION_RE.match(ln)
        if m:
            section = m.group(1)
            continue
        if section not in CARGO_VERSION_SECTIONS:
            continue
        m = CARGO_VERSION_RE.match(ln)
        if m:
            found.append((i, section, m.group(3)))
    return found


def validate_cargo(repo: pathlib.Path, v: str) -> list[str]:
    problems: list[str] = []
    for path in cargo_manifests(repo):
        rel = path.relative_to(repo).as_posix()
        text = path.read_text(encoding="utf-8")
        for _i, section, declared in cargo_version_lines(text.splitlines()):
            if declared != v:
                problems.append(f"{rel}: [{section}] version {declared} != VERSION {v}")
    return problems


def sync_cargo(repo: pathlib.Path, v: str) -> list[str]:
    """Rewrite a diverging literal Cargo version in an EXISTING manifest; never insert a field.

    Every other byte of the file is preserved (line endings included), so a second run finds
    nothing to rewrite and leaves the file identical.
    """
    notes: list[str] = []
    for path in cargo_manifests(repo):
        lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
        stale = [(i, section, declared) for i, section, declared
                 in cargo_version_lines(lines) if declared != v]
        if not stale:
            continue
        for i, _section, _declared in stale:
            m = CARGO_VERSION_RE.match(lines[i])
            lines[i] = m.group(1) + m.group(2) + v + m.group(4) + m.group(5) + lines[i][m.end():]
        path.write_bytes("".join(lines).encode("utf-8"))
        rel = path.relative_to(repo).as_posix()
        notes.extend(f"{rel}: [{section}] {declared} -> {v}" for _i, section, declared in stale)
    return notes


def sync(repo: pathlib.Path, v: str, date: str) -> list[str]:
    """Propagate `v` into every synced file; return the Cargo rewrites that were applied."""
    for rel in SYNC_FILES:
        p = repo / rel
        if p.is_file():
            sync_file(p, rel, v, date)
    return sync_cargo(repo, v)


def file_version_reprs(repo: pathlib.Path) -> dict[str, list[str]]:
    """Collect the version strings currently present in each synced file."""
    out: dict[str, list[str]] = {}
    for rel in MARKER_FILES:
        p = repo / rel
        found: list[str] = []
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            found = MARKER_RE.findall(text)
        out[rel] = found
    return out


def validate(repo: pathlib.Path, v: str) -> tuple[bool, list[str]]:
    problems: list[str] = []
    reprs = file_version_reprs(repo)
    for rel in MARKER_FILES:
        found = reprs[rel]
        if not found:
            problems.append(f"{rel}: missing version marker")
        elif any(f != v for f in found):
            problems.append(f"{rel}: marker(s) {found} != VERSION {v}")
    # README title/footer
    readme = repo / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        title_ok = bool(re.search(rf"#\s+.*?\s+v{v}\s*$", text, flags=re.M))
        footer_ok = f"Current version: **{v}**" in text
        if not title_ok:
            problems.append("README.md: title does not match VERSION")
        if not footer_ok:
            problems.append("README.md: footer does not match VERSION")
    # CHANGELOG top section
    cl = repo / "CHANGELOG.md"
    if cl.is_file():
        first = next((ln for ln in cl.read_text(encoding="utf-8").splitlines()
                      if CHANGELOG_SECTION_RE.match(ln)), None)
        if first:
            m = CHANGELOG_SECTION_RE.match(first)
            if m.group(1) != v:
                problems.append(f"CHANGELOG.md: top section {m.group(1)} != VERSION {v}")
        else:
            problems.append("CHANGELOG.md: no version section found")
    # Rust manifests (`Cargo.toml`) below the repo, minus the pruned directories.
    problems.extend(validate_cargo(repo, v))
    return (not problems), problems


def suggest(args) -> int:
    if args.breaking:
        print("major")
        return 0
    if args.new_subagent or args.new_task_type or args.new_field:
        print("minor")
        return 0
    if args.fix:
        print("patch")
        return 0
    if args.no_change:
        print("none")
        return 0
    print("error: no version-type signal given", file=sys.stderr)
    return 1


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries
    non-ASCII characters (the em dash `—`), which that codec cannot
    encode: `print_help()` would raise UnicodeEncodeError and the user would get a traceback
    instead of the help. `errors="replace"` keeps a stream that cannot be reconfigured from ever
    raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def print_notes(notes: list[str]) -> None:
    """Report what `sync` rewrote beyond the marker files (the Cargo manifests)."""
    for note in notes:
        print("  " + note)


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="Project root (default: cwd)")
    ap.add_argument("--version-file", default="VERSION", help="Version file (default: VERSION)")
    ap.add_argument("--date", default=None, help="Date for CHANGELOG section (default: today)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("get")
    pb = sub.add_parser("bump"); pb.add_argument("kind", choices=["major", "minor", "patch"])
    sub.add_parser("sync")
    sub.add_parser("validate")
    ps = sub.add_parser("set"); ps.add_argument("version")
    pg = sub.add_parser("suggest")
    pg.add_argument("--new-subagent", action="store_true")
    pg.add_argument("--new-task-type", action="store_true")
    pg.add_argument("--new-field", action="store_true")
    pg.add_argument("--breaking", action="store_true")
    pg.add_argument("--fix", action="store_true")
    pg.add_argument("--no-change", action="store_true")

    args = ap.parse_args()
    repo = pathlib.Path(args.repo).resolve()
    vf = repo / args.version_file

    if args.cmd == "suggest":
        return suggest(args)

    if args.cmd == "get":
        print(read_version(vf))
        return 0

    if args.cmd == "set":
        v = args.version
        if parse_version(v) is None:
            print(f"error: '{v}' is not X.Y.Z", file=sys.stderr)
            return 1
        write_version(vf, v)
        date = args.date or datetime.date.today().isoformat()
        print_notes(sync(repo, v, date))
        print(f"version set to {v} and synced")
        return 0

    if args.cmd == "bump":
        cur = read_version(vf)
        new = bump(cur, args.kind)
        write_version(vf, new)
        date = args.date or datetime.date.today().isoformat()
        print_notes(sync(repo, new, date))
        print(f"bumped {cur} -> {new} ({args.kind}) and synced")
        return 0

    if args.cmd == "sync":
        v = read_version(vf)
        date = args.date or datetime.date.today().isoformat()
        print_notes(sync(repo, v, date))
        print(f"synced version {v}")
        return 0

    if args.cmd == "validate":
        v = read_version(vf)
        ok, problems = validate(repo, v)
        if ok:
            print(f"PASS - versions are consistent ({v}).")
            return 0
        print("FAIL - version inconsistency:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
