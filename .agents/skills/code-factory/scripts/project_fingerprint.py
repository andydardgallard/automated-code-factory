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
   project's tracked content, read from the git index via `git ls-files -s`: the
   `mode SHA path` triple of every non-excluded index entry, sorted. It INTENTIONALLY changes
   on ANY modification of a tracked (non-excluded) file — including changes far below the
   root that level 1 cannot see. Without a usable git repository/index it falls back to
   hashing the contents of every non-excluded WORKING-TREE file, sorted by path, so the level
   still works outside git (and sees uncommitted edits). Note that the git path reads the
   INDEX, so an UNSTAGED (or untracked) edit is INVISIBLE to it: the hash does not move until the
   change is `git add`-ed. That is deliberate — the factory works through git and stages its
   changes, and AGENTS.md must be able to embed its own hash pair — so the blind spot is not
   removed but made VISIBLE instead: `--content`/`--all` print a stderr note when the worktree
   holds changes the index does not contain (`worktree_dirty`), and `check_factory_model.py`
   warns the same way. The note never changes a printed hash or an exit code. The git-less
   fallback above covers projects without a repository at all.

Because both levels exclude the same factory artifacts, AGENTS.md can embed BOTH hashes on its
first line and be committed without invalidating them:

  <!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->

The "skip regeneration" branch requires BOTH hashes to match; a content-only change (invisible
to level 1) therefore still triggers a regeneration, which is the point of the second level.

Usage:
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>]
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>] --content
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>] --all

Prints the 64-hex fingerprint(s) to stdout. In the two content modes (`--content`, `--all`) a
dirty worktree — changes not in the git index, which the content hash cannot see — adds a note on
stderr and leaves the hashes and the exit code untouched. Zero LLM tokens, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
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
# Dot-prefixed parts are skipped too, mirroring the structural top-level listing rule.
EXCLUDED_PARTS = IGNORE_TOP_LEVEL | IGNORE_PARTS


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
    """True if any part of a repo-relative path is excluded from the fingerprint signals."""
    return any(part in EXCLUDED_PARTS or part.startswith(".") for part in rel.split("/"))


def _git_index_records(root: pathlib.Path) -> list[str] | None:
    """`<mode> <sha> <path>` for every non-excluded index entry, or None if git is unusable.

    Runs `git ls-files -s -z` (NUL-separated: no C-style path quoting, so the result does not
    depend on the `core.quotepath` setting). The index is the deterministic, order-independent
    source here; the index stage is not recorded because it is always 0 in a clean tree.
    `None` (git missing, not a repository, unreadable index) makes the caller use the
    working-tree fallback instead of failing.
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


def _worktree_records(root: pathlib.Path) -> list[str]:
    """`<path>:<sha256>` for every non-excluded working-tree file (git-less fallback)."""
    records: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = _rel(p, root)
        if _is_excluded(rel):
            continue
        records.append(f"{rel}:{_sha256_file(p)}")
    return records


def worktree_dirty(root: pathlib.Path) -> list[str]:
    """Repo-relative paths of the non-excluded changes NOT in the git index — else an empty list.

    Those are exactly the edits the content fingerprint cannot see: entries whose WORKTREE column
    is dirty (` M`, `MM`, ` D`, …) plus untracked ones (`??`). A change already recorded in the
    index (`M `, `A `, …) is deliberately NOT reported — `git ls-files -s` reads it, so the content
    hash does move. `git status --porcelain -z` is NUL-separated (no C-style path quoting) and a
    rename/copy entry carries its origin path in the following NUL field, which is skipped. The
    factory's own artifacts are filtered out with the same `_is_excluded` rule the fingerprints
    use, so dirtying AGENTS.md/memory/ never looks like drift. An empty list means "no signal": a
    clean tree, only excluded changes, or no usable git repository — then there is nothing to warn
    about.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "-z"],
                              capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    dirty: list[str] = []
    skip_next = False  # a rename/copy entry carries its origin path in the NEXT NUL field
    for entry in proc.stdout.decode("utf-8", "replace").split("\0"):
        if skip_next:
            skip_next = False
            continue
        if len(entry) < 4 or entry[2] != " ":  # "XY <path>"
            continue
        status, path = entry[:2], entry[3:]
        skip_next = "R" in status or "C" in status
        if status[0] != "?" and status[1] == " ":  # index-only change: the fingerprint sees it
            continue
        if status[0] == "!" or _is_excluded(path):  # ignored entry / factory artifact
            continue
        dirty.append(path)
    return dirty


def compute_content_fingerprint(root: pathlib.Path) -> str:
    """Content fingerprint (level 2): SHA-256 over the tracked content, see module docstring.

    Reads the git INDEX (`git ls-files -s`), so unstaged edits to tracked files do not move the
    hash — `worktree_dirty` reports that blind spot to the CLI and to `check_factory_model.py`.
    """
    records = _git_index_records(root)
    if records is None:
        records = _worktree_records(root)
    return _sha256_bytes("\n".join(sorted(records)).encode("utf-8"))


def _note_dirty_worktree(root: pathlib.Path) -> None:
    """Print a stderr note when the worktree holds changes the content fingerprint cannot see.

    The content level reads the git index (see the module docstring), so unstaged and untracked
    edits leave the hash untouched; saying so keeps the documented blind spot from being silent.
    Changes already staged are not counted — the index reflects them and the hash does move. The
    note goes to stderr and changes neither the printed hash nor the exit code.
    """
    dirty = worktree_dirty(root)
    if dirty:
        print(f"note: {len(dirty)} unstaged/uncommitted change(s) not in the git index — content "
              f"fingerprint reads the git index and does not see them", file=sys.stderr)


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


def main() -> None:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="Path to the project (default: cwd)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--content", action="store_true",
                      help="Print only the content fingerprint (tracked content)")
    mode.add_argument("--all", action="store_true",
                      help="Print both fingerprints as 'structural: <hash>' / 'content: <hash>'")
    args = ap.parse_args()
    root = pathlib.Path(args.repo).resolve()
    if args.content or args.all:
        # Both modes print the index-based content hash: warn about what it cannot see.
        _note_dirty_worktree(root)
    if args.content:
        print(compute_content_fingerprint(root))
    elif args.all:
        print(f"structural: {compute_fingerprint(root)}")
        print(f"content: {compute_content_fingerprint(root)}")
    else:
        # Default stays structural-only: backwards compatible with the existing pipeline.
        print(compute_fingerprint(root))


if __name__ == "__main__":
    main()
