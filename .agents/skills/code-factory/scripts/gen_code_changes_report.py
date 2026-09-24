#!/usr/bin/env python3
"""
Generate `.code-factory/report_code_changes.md` — a visual "was → became" report
of file changes in a git commit (only changed lines, no context).

Usage:
  python3 scripts/gen_code_changes_report.py [--repo <path>] [--commit <sha|HEAD>] [--out <path>] \\
          [--run-id <id>]

Defaults:
  --repo    current working directory
  --commit  HEAD (last commit)
  --out     <repo>/.code-factory/report_code_changes.md
  --run-id  empty: the report header is unchanged; when given, the line `run_id: <id>` is added

The report is deterministic (parses `git show --unified=0`), costs zero LLM tokens,
and is written next to report.md so the factory run is fully auditable.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

MAX_BLOCK = 30  # max lines shown for a pure add/remove block

# One path token of a `diff --git` header: either C-quoted ("a/my file.txt") or a plain run.
PATH_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')


def git_show_diff(repo: pathlib.Path, commit: str) -> str:
    """Return the diff of a commit with zero context (only changed lines)."""
    proc = subprocess.run(
        ["git", "show", commit, "--unified=0", "--format="],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show {commit} failed: {proc.stderr.strip()}")
    return proc.stdout


def unquote_path(token: str) -> str:
    """Decode one git path token: C-quoting (spaces, non-ASCII as octal bytes) is undone."""
    if not token.startswith('"') or not token.endswith('"') or len(token) < 2:
        return token
    body = token[1:-1]
    if "\\" not in body:
        return body
    # unicode_escape gives byte semantics for \ooo; latin-1 glues the bytes back together.
    raw = body.encode("latin-1", "replace").decode("unicode_escape").encode("latin-1", "replace")
    return raw.decode("utf-8", "replace")


def header_paths(raw: str) -> tuple[str, str] | None:
    """Return (old, new) repo-relative paths of a `diff --git ...` header, or None."""
    tokens = PATH_TOKEN_RE.findall(raw[len("diff --git "):] if raw.startswith("diff --git ") else raw)
    if len(tokens) != 2:
        return None
    old, new = (unquote_path(t) for t in tokens)
    return (old[2:] if old.startswith("a/") else old,
            new[2:] if new.startswith("b/") else new)


def parse_diff(diff: str) -> list[dict]:
    """Parse a zero-context diff into per-file lists of ('-'|'+', text)."""
    files: list[dict] = []
    cur: dict | None = None
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            if cur:
                files.append(cur)
            paths = header_paths(raw)
            cur = {"path": paths[1] if paths else raw, "lines": []}
        elif raw.startswith("new file"):
            cur["status"] = "new"
        elif raw.startswith("deleted file"):
            cur["status"] = "deleted"
        elif raw.startswith("index ") or raw.startswith("@@") or raw.startswith("diff "):
            continue
        elif raw.startswith("--- ") or raw.startswith("+++ "):
            continue
        else:
            if raw.startswith("-") and not raw.startswith("---"):
                cur["lines"].append(("-", raw[1:]))
            elif raw.startswith("+") and not raw.startswith("+++"):
                cur["lines"].append(("+", raw[1:]))
    if cur:
        files.append(cur)
    return files


def build_report(files: list[dict], commit: str, branch: str, run_id: str = "") -> str:
    out: list[str] = ["# Report of Code Changes — commit `%s`" % commit, ""]
    if run_id:  # run provenance: the artifact names the run it belongs to (see run_id.py)
        out += ["run_id: %s" % run_id, ""]
    out += [
        "**Branch:** `%s`  ·  **Files:** %d  ·  Generated from `git show %s --unified=0`"
        % (branch, len(files), commit),
        "",
        "Only the changed lines are shown (no context): was → became.",
        "",
        "---",
        "",
    ]
    for f in files:
        out.append("## `%s`" % f["path"])
        status = f.get("status")
        lines = f["lines"]

        if status == "new":
            out += ["", "**New file** (%d lines added)" % len(lines), "", "```"]
            shown = lines[:MAX_BLOCK]
            out += [l for _, l in shown]
            if len(lines) > MAX_BLOCK:
                out.append("... (+%d lines, full code in git)" % (len(lines) - MAX_BLOCK))
            out += ["```", "", "---", ""]
            continue

        if status == "deleted":
            out += ["", "**File deleted** (%d lines)" % len(lines), "", "---", ""]
            continue

        # group consecutive '-' '+' into pairs
        pairs: list[tuple[str, str]] = []
        removes: list[str] = []
        adds: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            kind, text = lines[i]
            if kind == "-" and i + 1 < n and lines[i + 1][0] == "+":
                pairs.append((text, lines[i + 1][1]))
                i += 2
            elif kind == "-":
                removes.append(text)
                i += 1
            else:
                adds.append(text)
                i += 1

        # Skip trivial pairs (identical text = only newline/EOL change)
        pairs = [(o, nw) for o, nw in pairs if o != nw]

        if pairs:
            out += ["", "### Changed lines (was → became)", "",
                    "| Was | Became |", "|------|-------|"]
            for old, new in pairs:
                out.append("| `%s` | `%s` |" % (old.strip(), new.strip()))
            out.append("")

        if removes:
            out += ["", "### Removed", "", "```"]
            shown = removes[:MAX_BLOCK]
            out += shown
            if len(removes) > MAX_BLOCK:
                out.append("... (-%d lines)" % (len(removes) - MAX_BLOCK))
            out += ["```", ""]

        if adds:
            out += ["", "### Added", "", "```"]
            shown = adds[:MAX_BLOCK]
            out += shown
            if len(adds) > MAX_BLOCK:
                out.append("... (+%d lines, full code in git)" % (len(adds) - MAX_BLOCK))
            out += ["```", ""]

        out += ["---", ""]
    return "\n".join(out)


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the non-ASCII help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and argparse's `--help` text
    carries non-ASCII characters (the `→` arrows), which that codec cannot encode:
    `print_help()` would raise UnicodeEncodeError and the user would get a traceback instead of
    the help. `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> None:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="Path to the git repository (default: cwd)")
    ap.add_argument("--commit", default="HEAD", help="Commit to report (default: HEAD)")
    ap.add_argument("--out", default=None, help="Output path (default: <repo>/.code-factory/report_code_changes.md)")
    ap.add_argument("--run-id", default="",
                    help="Run id (see run_id.py); when given it is recorded in the report header")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"Not a git repository: {repo}")

    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip() or "(detached)"

    diff = git_show_diff(repo, args.commit)
    files = parse_diff(diff)
    report = build_report(files, args.commit, branch, args.run_id)

    out = pathlib.Path(args.out) if args.out else repo / ".code-factory" / "report_code_changes.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Written: {out} ({len(files)} files, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
