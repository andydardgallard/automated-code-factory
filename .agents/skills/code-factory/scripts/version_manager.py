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
  - README.md                title `# Autonomous Code Factory vX.Y.Z` + footer `Текущая версия: **X.Y.Z**`
  - CHANGELOG.md             prepends `## [X.Y.Z] — <date>` when the top section is older
  - AGENTS.md / SKILL.md / .agents/README.md   marker `<!-- code-factory-version: X.Y.Z -->`

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
import pathlib
import re
import sys

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MARKER_RE = re.compile(r"<!--\s*code-factory-version:\s*(\d+\.\d+\.\d+)\s*-->")
README_TITLE_RE = re.compile(r"^(#\s+.*?\s+v)\d+\.\d+\.\d+(\s*)$")
README_FOOTER_RE = re.compile(r"(Текущая версия:\s*\*\*)\d+\.\d+\.\d+(\*\*)")
CHANGELOG_SECTION_RE = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]")

SYNC_FILES = ["README.md", "AGENTS.md", ".agents/skills/code-factory/SKILL.md", ".agents/README.md"]
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
    vf.write_text(v + "\n", encoding="utf-8")


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
        for i, ln in enumerate(lines):
            m = README_TITLE_RE.match(ln)
            if m:
                lines[i] = m.group(1) + v + m.group(2)
            lines[i] = README_FOOTER_RE.sub(lambda mo: mo.group(1) + v + mo.group(2), lines[i])
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
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync(repo: pathlib.Path, v: str, date: str) -> None:
    for rel in SYNC_FILES + ["CHANGELOG.md"]:
        p = repo / rel
        if p.is_file():
            sync_file(p, rel, v, date)


def file_version_reprs(repo: pathlib.Path) -> dict[str, list[str]]:
    """Collect the version strings currently present in each synced file."""
    out: dict[str, list[str]] = {}
    for rel in ["README.md", "AGENTS.md", ".agents/skills/code-factory/SKILL.md", ".agents/README.md"]:
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
    for rel in ["README.md", "AGENTS.md", ".agents/skills/code-factory/SKILL.md", ".agents/README.md"]:
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
        footer_ok = f"Текущая версия: **{v}**" in text
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


def main() -> int:
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
        sync(repo, v, date)
        print(f"version set to {v} and synced")
        return 0

    if args.cmd == "bump":
        cur = read_version(vf)
        new = bump(cur, args.kind)
        write_version(vf, new)
        date = args.date or datetime.date.today().isoformat()
        sync(repo, new, date)
        print(f"bumped {cur} -> {new} ({args.kind}) and synced")
        return 0

    if args.cmd == "sync":
        v = read_version(vf)
        date = args.date or datetime.date.today().isoformat()
        sync(repo, v, date)
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
