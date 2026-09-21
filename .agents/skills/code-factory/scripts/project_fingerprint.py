#!/usr/bin/env python3
"""
Deterministic project fingerprint for the Code Factory's Scout pipeline.

The fingerprint is a SHA-256 over structural signals of the project's WORKING TREE
(not only committed state), so it changes when the project's structure/stack/entry
points change — and stays stable when nothing relevant changed. It is used to decide
whether to skip re-analysis + AGENTS.md regeneration ("skip Scout if unchanged").

Signals (all read from disk, so uncommitted edits to them are caught too):
  1. stack manifests (fixed candidate list + *.csproj / *.sln at root and one level deep),
  2. CI configs (.github/workflows/**, .gitlab-ci.yml, Jenkinsfile, .circleci/**),
  3. README (README.md / README.rst / README / readme.md),
  4. sorted top-level directory listing (dirs/files, minus build/VCS/editor noise and the
     factory's own artifacts — AGENTS.md, memory/, task.yaml, and the deployer/launcher
     scripts: start.sh, start.cmd, prepare_factory.cmd, prepare_factory.ps1).

NOTE: the fingerprint deliberately does NOT include the git tree SHA. AGENTS.md and memory/ are
factory artifacts excluded from the signals, so committing them does not change the fingerprint.
Including the tree SHA would make the embedded fingerprint stale immediately after the very
commit that carries it, making the "skip Scout when unchanged" branch unreachable.

Usage:
  python3 project_fingerprint.py [--repo <path>]

Prints the 64-hex fingerprint to stdout. Zero LLM tokens, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib

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

# Top-level entries skipped in the directory-listing signal (build/VCS/editor noise,
# plus the factory's own artifacts — they are not project structure). The generated
# launchers (start.sh and its Windows counterpart start.cmd) and the Windows deployer
# (prepare_factory.cmd → prepare_factory.ps1) are excluded alongside AGENTS.md/memory/,
# so committing them does not shift the fingerprint of the deployed project.
IGNORE_TOP_LEVEL = {
    ".git", ".code-factory", ".venv", "venv", "__pycache__",
    "node_modules", "target", "dist", "build", ".idea", ".vscode", ".DS_Store",
    "AGENTS.md", "memory", "task.yaml", "start.sh", "start.cmd",
    "prepare_factory.cmd", "prepare_factory.ps1",
}

# Sub-path segments that are never traversed for the *.{csproj,sln} glob.
IGNORE_PARTS = {".git", ".code-factory", ".venv", "venv", "__pycache__",
                "node_modules", "target", "dist", "build"}


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="Path to the project (default: cwd)")
    args = ap.parse_args()
    print(compute_fingerprint(pathlib.Path(args.repo).resolve()))


if __name__ == "__main__":
    main()
