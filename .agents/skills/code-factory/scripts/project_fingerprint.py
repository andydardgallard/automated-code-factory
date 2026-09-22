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
   INDEX, so a modification that was neither staged nor committed is out of scope there —
   the factory works through git and stages its changes, while the git-less fallback above
   covers projects without a repository at all.

Because both levels exclude the same factory artifacts, AGENTS.md can embed BOTH hashes on its
first line and be committed without invalidating them:

  <!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->

The "skip regeneration" branch requires BOTH hashes to match; a content-only change (invisible
to level 1) therefore still triggers a regeneration, which is the point of the second level.

Usage:
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>]
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>] --content
  python .agents/skills/code-factory/scripts/project_fingerprint.py [--repo <path>] --all

Prints the 64-hex fingerprint(s) to stdout. Zero LLM tokens, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess

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


def compute_content_fingerprint(root: pathlib.Path) -> str:
    """Content fingerprint (level 2): SHA-256 over the tracked content, see module docstring."""
    records = _git_index_records(root)
    if records is None:
        records = _worktree_records(root)
    return _sha256_bytes("\n".join(sorted(records)).encode("utf-8"))


def main() -> None:
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
