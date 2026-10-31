#!/usr/bin/env python3
"""
Deterministic project fingerprints for the Code Factory's Scout pipeline (two levels).

The two levels are independent and complementary; together they decide whether to skip
re-analysis + AGENTS.md regeneration ("skip Scout if unchanged").

1. STRUCTURAL fingerprint (`compute_fingerprint`, the default CLI mode) — SHA-256 over the
   structural signals of the project's WORKING TREE:
     a. stack manifests (fixed candidate list + *.csproj / *.sln at root and one level deep),
     b. CI configs (.github/workflows/**, .gitlab-ci.yml, Jenkinsfile, .circleci/**),
     c. README (README.md / README.rst / README / readme.md),
     d. sorted top-level directory listing.
   It is COMMIT-stable: the factory's own artifacts are excluded (see EXCLUDED_PARTS), so
   committing them does not shift the value and the hash embedded in AGENTS.md stays valid
   after the very commit that carries it — otherwise the "skip Scout when unchanged" branch
   would be unreachable. Its known blind spot: an edit to an existing file deeper than the
   signal list (e.g. `src/a/b/c.py`) is invisible while no root manifest, CI config, README
   or top-level entry changes. Level 2 exists to close exactly that hole.

2. CONTENT fingerprint (`compute_content_fingerprint`, `--content`) — SHA-256 over the
   project's tracked content, read from the WORKING TREE of the tracked set: one
   `<mode> <sha256(worktree content)> <path>` record for every non-excluded file of
   `git ls-files -s`, sorted. It INTENTIONALLY changes on ANY modification of a tracked
   (non-excluded) file — an UNSTAGED edit included, which the index-blob variant of this level
   used to miss — and on changes far below the root that level 1 cannot see. Content is
   CRLF→LF normalized before hashing, so the value does not depend on the checkout's line
   endings (`.cmd`/`.ps1` are pinned to eol=crlf by .gitattributes and would otherwise hash
   differently from an LF checkout). A tracked file ABSENT from the worktree (deleted but not
   staged) or unreadable is recorded with an explicit `MISSING` marker in the digest field
   (`<mode> MISSING <path>`) — never with its index record: losing the content is a change too,
   and a marker keeps the value free of any git object id that could already sit in a stale
   AGENTS.md. UNTRACKED
   files are outside `git ls-files` and therefore outside the hash; that boundary is not hidden
   but made VISIBLE: `--content`/`--all` print a stderr note with their count (`untracked_files`,
   the factory's own artifacts excluded), and `check_factory_model.py` warns the same way. The
   note never changes a printed hash or an exit code. Without a usable git repository the level
   falls back to hashing every non-excluded WORKING-TREE file with the same LF normalization and
   exclusions (`<path>:<sha256>` records), so it works outside git just as well.

   Committing does not change any tracked file's worktree content, so the value embedded in
   AGENTS.md survives the very commit that carries it and the "skip regeneration" branch stays
   reachable. The semantics above are pinned by `test_factory_model.py` case 29.

Because both levels exclude the same factory artifacts, AGENTS.md can embed BOTH hashes on its
first line and be committed without invalidating them:

  <!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->

The "skip regeneration" branch requires BOTH hashes to match; a content-only change (invisible
to level 1) therefore still triggers a regeneration, which is the point of the second level.

Usage:
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>]
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>] --content
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>] --all

Prints the 64-hex fingerprint(s) to stdout. In the two content modes (`--content`, `--all`)
UNTRACKED files — outside the tracked content the hash covers — add a note on stderr and leave the
hashes and the exit code untouched.

AGENTS.md SIZE GATE (both paths share `agents_size_issues`): every mode measures `<repo>/AGENTS.md`
and says so on stderr — a WARNING over 28 KB (28672 bytes), a hard ERROR over 32 KB (32768 bytes)
that turns the exit code into 1. The printed hashes never change. `check_factory_model.py` runs the
same gate on the validation path, so an oversized instruction file cannot be generated, committed or
accepted silently; the factory's own hand-authored manual is subject to it as well.
Zero LLM tokens, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess
import sys

# Fixed candidate stack-manifest filenames (same signals as tech-stack-detection.md §1).
MANIFEST_FILES = [
    "Cargo.toml", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "Pipfile", "poetry.lock", "uv.lock", "package.json", "go.mod", "pom.xml",
    "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile",
    "Gemfile", "composer.json", "mix.exs", "Package.swift",
]

CI_FILES = [".gitlab-ci.yml", "Jenkinsfile"]
CI_DIRS = [".github/workflows", ".circleci"]

README_NAMES = ["README.md", "README.rst", "README", "readme.md", "Readme.md"]

# Top-level entries skipped in the structural directory-listing signal (build/VCS/editor noise,
# plus the factory's own artifacts — they are not project structure). The deployer/launcher
# scripts (start.sh/start.cmd and prepare_factory.sh/.cmd/.ps1) are excluded alongside
# AGENTS.md/memory/, so committing them does not shift the fingerprint of the deployed project.
IGNORE_TOP_LEVEL = {
    ".git", ".code-factory", ".venv", "venv", "__pycache__",
    "node_modules", "target", "dist", "build", ".idea", ".vscode", ".DS_Store",
    "AGENTS.md", "memory", "task.yaml", "start.sh", "start.cmd",
    "prepare_factory.sh", "prepare_factory.cmd", "prepare_factory.ps1",
}

# Sub-path segments that are never traversed for the *.{csproj,sln} glob.
IGNORE_PARTS = {".git", ".code-factory", ".venv", "venv", "__pycache__",
                "node_modules", "target", "dist", "build"}

# Path parts excluded from BOTH fingerprint levels: build/VCS/editor noise plus the factory's
# own artifacts (AGENTS.md, memory/, task.yaml, .code-factory/, the deployer/launcher scripts).
# The exclusion is EXPLICIT, not "any dot-prefixed part": tracked dot-directories that hold
# project content (.agents/, .github/, .kimi-code/) must stay in the hash, or an edit under
# them would move neither level and the "skip regeneration" branch could fire on a changed
# project. Only the noise above is meant to be invisible.
EXCLUDED_PARTS = IGNORE_TOP_LEVEL | IGNORE_PARTS

# The AGENTS.md SIZE gate (generation path here, validation path in check_factory_model.py): the
# instruction file every agent reads must stay a reference, not a book. Over 28 KB it is warned
# about loudly, over 32 KB it is a hard error — the CLI warns that such a file exceeds its
# instruction budget, and the bulk of an oversized AGENTS.md is always verbatim text that belongs
# in `references/` behind a pointer.
AGENTS_SIZE_WARN_BYTES = 28 * 1024
AGENTS_SIZE_FAIL_BYTES = 32 * 1024

# The digest-field value of a tracked file that is ABSENT from the worktree (deleted but not
# staged) or unreadable. It replaces the digest instead of the file's index record: a git object id
# in a content-hash record is a different KIND of value (and a stable one across the deletion), so
# the explicit marker is what makes losing the content show up as a change.
MISSING_CONTENT = "MISSING"


def agents_size_issues(size: int) -> tuple[str, str]:
    """(warning, error) for an AGENTS.md of `size` bytes — at most one of them is non-empty.

    The single implementation of the size gate, shared by the generation path (`main` below, which
    fails when the file it fingerprints is already over the hard limit) and the validation path
    (`check_factory_model.check_agents_model`), so the two cannot drift apart.
    """
    if size > AGENTS_SIZE_FAIL_BYTES:
        return "", (f"AGENTS.md is {size} bytes, over the hard limit of {AGENTS_SIZE_FAIL_BYTES} "
                    f"bytes (32 KB): trim it — move verbatim rule text into references/ and keep "
                    f"a one-line pointer (see references/factory-rules.md)")
    if size > AGENTS_SIZE_WARN_BYTES:
        return (f"AGENTS.md is {size} bytes, over the {AGENTS_SIZE_WARN_BYTES}-byte (28 KB) warning "
                f"line (hard limit {AGENTS_SIZE_FAIL_BYTES} bytes / 32 KB) — it is drifting into a "
                f"book; keep verbatim text in references/", "")
    return "", ""


def _note_agents_size(root: pathlib.Path) -> bool:
    """Print the size verdict for `<root>/AGENTS.md`; True when it is over the hard limit.

    The note goes to stderr so the printed fingerprints stay machine-readable; it is printed in
    every mode, because a generator that emits the hash of an unusable instruction file is worse
    than useless. A project without AGENTS.md has nothing to measure (exit code untouched).
    """
    path = root / "AGENTS.md"
    try:
        size = path.stat().st_size
    except OSError:
        return False
    warning, error = agents_size_issues(size)
    if error:
        print(f"error: {error}", file=sys.stderr)
    elif warning:
        print(f"warning: {warning}", file=sys.stderr)
    return bool(error)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _rel(path: pathlib.Path, root: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def _clean(p: pathlib.Path) -> bool:
    """True if no path part is in the ignore set."""
    return not any(part in IGNORE_PARTS for part in p.parts)


def collect_manifest_signals(root: pathlib.Path) -> list[str]:
    out: list[str] = []
    for name in MANIFEST_FILES:
        f = root / name
        if f.is_file():
            out.append(f"{name}:{_sha256_file(f)}")
    # *.csproj / *.sln at root and one level deep (C# / .NET).
    candidates = sorted(root.glob("*.csproj")) + sorted(root.glob("*.sln"))
    candidates += sorted(root.glob("*/*.csproj")) + sorted(root.glob("*/*.sln"))
    seen: set[str] = set()
    for p in candidates:
        if p.is_file() and _clean(p):
            rel = _rel(p, root)
            if rel not in seen:
                seen.add(rel)
                out.append(f"{rel}:{_sha256_file(p)}")
    return out


def collect_ci_signals(root: pathlib.Path) -> list[str]:
    out: list[str] = []
    for name in CI_FILES:
        f = root / name
        if f.is_file():
            out.append(f"{name}:{_sha256_file(f)}")
    for d in CI_DIRS:
        dd = root / d
        if dd.is_dir():
            for p in sorted(dd.rglob("*")):
                if p.is_file():
                    out.append(f"{_rel(p, root)}:{_sha256_file(p)}")
    return out


def collect_readme_signal(root: pathlib.Path) -> str:
    for name in README_NAMES:
        f = root / name
        if f.is_file():
            return f"README:{_sha256_file(f)}"
    return "README:(none)"


def collect_dir_signal(root: pathlib.Path) -> str:
    entries: list[str] = []
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        name = p.name
        if name in IGNORE_TOP_LEVEL or name.startswith("."):
            continue
        entries.append(f"{'dir' if p.is_dir() else 'file'}:{name}")
    return "\n".join(entries)


def compute_fingerprint(root: pathlib.Path) -> str:
    """Structural fingerprint (level 1): commit-stable, does not include file content."""
    parts: list[str] = [
        "== MANIFESTS ==",
        *collect_manifest_signals(root),
        "== CI ==",
        *collect_ci_signals(root),
        "== README ==",
        collect_readme_signal(root),
        "== DIRS ==",
        collect_dir_signal(root),
    ]
    return _sha256_bytes("\n".join(parts).encode("utf-8"))


def _is_excluded(rel: str) -> bool:
    """True if any part of a repo-relative path is in the explicit EXCLUDED_PARTS set.

    Dot-prefixed parts as such are NOT excluded: a tracked file below a dot-directory that
    holds project content (.agents/, .kimi-code/) is covered by the content fingerprint, as
    AGENTS.md and .agents/README.md promise; only the explicit noise set (.git, .code-factory,
    editor/VCS drop-ins, the factory's own artifacts) is invisible.
    """
    return any(part in EXCLUDED_PARTS for part in rel.split("/"))


def _git_index_records(root: pathlib.Path) -> list[str] | None:
    """`<mode> <sha> <path>` for every non-excluded index entry, or None if git is unusable.

    Runs `git ls-files -s -z` (NUL-separated: no C-style path quoting, so the result does not
    depend on the `core.quotepath` setting). It defines the TRACKED SET and the file modes used by
    the content fingerprint (which hashes the files' WORKING-TREE content, see `_content_records`);
    the index stage is not recorded because it is always 0 in a clean tree. `None` (git missing,
    not a repository, unreadable index) makes the caller use the working-tree fallback instead of
    failing.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                              capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    records: list[str] = []
    for entry in proc.stdout.decode("utf-8", "replace").split("\0"):
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if len(fields) < 2 or not path or _is_excluded(path):
            continue
        records.append(f"{fields[0]} {fields[1]} {path}")
    return records


def _worktree_content_sha(path: pathlib.Path, mode: str) -> str:
    """SHA-256 of a tracked file's WORKING-TREE content, CRLF→LF normalized.

    Normalization makes the digest platform-neutral: a checkout that materialized CRLF (`.cmd`/`.ps1`
    are pinned to eol=crlf by .gitattributes) hashes like the LF checkout of the same commit. A
    symlink (git mode 120000) is hashed by its link TARGET — exactly what git stores as the blob —
    so the digest never escapes the repository through the link.
    """
    data = os.fsencode(os.readlink(path)) if mode == "120000" else path.read_bytes()
    return _sha256_bytes(data.replace(b"\r\n", b"\n"))


def _worktree_records(root: pathlib.Path) -> list[str]:
    """`<path>:<sha256>` for every non-excluded working-tree file (git-less fallback).

    Uses the same LF normalization as the git path, so a project hashed without a repository gets
    the same per-file digest a git checkout of it would produce. A file that cannot be read
    (unreadable link target, permission) is skipped — without an index there is no record to fall
    back to.
    """
    records: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = _rel(p, root)
        if _is_excluded(rel):
            continue
        try:
            digest = _worktree_content_sha(p, "120000" if p.is_symlink() else "100644")
        except OSError:
            continue
        records.append(f"{rel}:{digest}")
    return records


def _content_records(root: pathlib.Path) -> list[str] | None:
    """`<mode> <sha256(worktree content)> <path>` per tracked non-excluded file, or None (no git).

    The tracked set and the file modes come from the index (`git ls-files -s`, see
    `_git_index_records`), the hash from the WORKING TREE — that is what makes an UNSTAGED edit move
    the content fingerprint. A tracked file ABSENT from the worktree (deleted but not staged) or
    unreadable is recorded with the explicit `MISSING_CONTENT` marker instead of a digest — never
    with its index record: losing the content is a change too, and the marker keeps the hash free
    of a git object id.
    """
    index = _git_index_records(root)
    if index is None:
        return None
    records: list[str] = []
    for record in index:
        mode, _index_sha, path = record.split(" ", 2)
        try:
            digest = _worktree_content_sha(root / path, mode)
        except OSError:                    # tracked but not in the worktree (or unreadable)
            digest = MISSING_CONTENT
        records.append(f"{mode} {digest} {path}")
    return records


def untracked_files(root: pathlib.Path) -> list[str]:
    """Repo-relative paths of the non-excluded UNTRACKED files — else an empty list.

    Untracked files are not part of `git ls-files`, so they are exactly the content the
    tracked-content fingerprint does NOT cover. `git status --porcelain -z` is NUL-separated (no
    C-style path quoting) and a rename/copy entry carries its origin path in the following NUL
    field, which is skipped. The factory's own artifacts are filtered out with the same
    `_is_excluded` rule the fingerprints use, so dropping a file into memory/ or .code-factory/
    never looks like drift. An empty list means "no signal": no untracked file, only excluded ones,
    or no usable git repository — then there is nothing to warn about. Staged and unstaged edits of
    TRACKED files are deliberately NOT reported: the fingerprint hashes their worktree content, so
    the hash does move.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "-z"],
                              capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    untracked: list[str] = []
    skip_next = False  # a rename/copy entry carries its origin path in the NEXT NUL field
    for entry in proc.stdout.decode("utf-8", "replace").split("\0"):
        if skip_next:
            skip_next = False
            continue
        if len(entry) < 4 or entry[2] != " ":  # "XY <path>"
            continue
        status, path = entry[:2], entry[3:]
        skip_next = "R" in status or "C" in status
        if status != "??" or _is_excluded(path):  # tracked change / ignored entry / factory artifact
            continue
        untracked.append(path)
    return untracked


def compute_content_fingerprint(root: pathlib.Path) -> str:
    """Content fingerprint (level 2): SHA-256 over the tracked WORKING-TREE content, see docstring.

    Hashes each tracked non-excluded file's worktree content (`git ls-files -s`, CRLF→LF
    normalized), so an UNSTAGED edit moves the hash; a file missing from the worktree is recorded
    with the explicit `MISSING_CONTENT` marker (its index record is never used). Untracked files are
    outside the tracked set and thus outside the hash — `untracked_files` reports them to the CLI and
    to `check_factory_model.py`.
    """
    records = _content_records(root)
    if records is None:
        records = _worktree_records(root)
    return _sha256_bytes("\n".join(sorted(records)).encode("utf-8"))


def _note_untracked(root: pathlib.Path) -> None:
    """Print a stderr note when the worktree holds untracked files the content fingerprint misses.

    The content level hashes the tracked working-tree content, so untracked files are outside it by
    definition; saying so keeps that boundary from being silent. Tracked edits (staged or not) are
    not counted — the hash does cover them. The note goes to stderr and changes neither the printed
    hash nor the exit code.
    """
    untracked = untracked_files(root)
    if untracked:
        print(f"note: {len(untracked)} untracked file(s) — not covered by the content fingerprint "
              f"(it hashes tracked working-tree content)", file=sys.stderr)


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
    ap.add_argument("--repo", default=".", help="Path to the project (default: cwd)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--content", action="store_true",
                      help="Print only the content fingerprint (tracked working-tree content)")
    mode.add_argument("--all", action="store_true",
                      help="Print both fingerprints as 'structural: <hash>' / 'content: <hash>'")
    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    if args.content or args.all:
        # Both content modes hash TRACKED content: note the untracked files they cannot cover.
        _note_untracked(root)
    if args.content:
        print(compute_content_fingerprint(root))
    elif args.all:
        print(f"structural: {compute_fingerprint(root)}")
        print(f"content: {compute_content_fingerprint(root)}")
    else:
        # Default stays structural-only: backwards compatible with the existing pipeline.
        print(compute_fingerprint(root))
    # The generation path enforces the AGENTS.md size gate too: an oversized instruction file must
    # not be (re-)generated and committed silently. The hashes above stay byte-identical.
    return 1 if _note_agents_size(root) else 0


if __name__ == "__main__":
    sys.exit(main())
