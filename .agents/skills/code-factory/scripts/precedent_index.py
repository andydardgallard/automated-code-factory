#!/usr/bin/env python3
"""
Deterministic FTS5 precedent index of a project's memory and code base (zero LLM tokens).

Asked "how was something like this solved before?" an analyzer or diagnostician must not re-read
the whole repository: this script builds ONE SQLite FTS5 index out of the two things that answer
that question — the project memory (`memory/change-log.md` and `memory/summary.md`) and the code
base — and answers free-text queries out of it.

Usage:
  python precedent_index.py build --repo <root> [--out <db>]
  python precedent_index.py query --repo <root> "<text>" [--limit 10]

`build` writes `<repo>/.code-factory/state/precedents.db` by default and is a DETERMINISTIC
REBUILD: the previous database and its -wal/-shm sidecars are deleted, the records are collected
in sorted `(source, path, title)` order and inserted in exactly that order, so the same working
tree always yields the same table. A relative `--out` is resolved against the repo root.

Indexed sources (`source` column):
  change-log  `memory/change-log.md` — one record per `## ` heading; the text before the first
              heading is one record titled `(preamble)`
  summary     `memory/summary.md` — one record per `## ` heading, same rule
  code        text files of the code base, listed by `git ls-files` when git is available and by
              a directory walk otherwise (the walk and the binary heuristic are shared with the
              shard protocol: `repo_inventory.py`, unreadable paths and symbolic links skipped)

Never indexed as code: `.code-factory/` (runtime state — it holds this database) and
`skill-base/golden-set/` (reviewer calibration data), the two memory files already indexed above,
files larger than 200 KiB, and binaries (a NUL byte within the first 8 KiB). `path` is always
repo-relative and posix; every record's content carries its heading, so a title-only match still
shows readable context.

Schema: one FTS5 virtual table `precedents(source TEXT, path TEXT, title TEXT, content TEXT)`.
`query` runs an FTS5 MATCH over it — raw FTS5 syntax is accepted (`"a b"`, `a OR b`, `NEAR(a b)`)
— and prints, per hit, the rank, the source, the path, the title and a `snippet()` of the content
with the matched terms in brackets. Zero matches is not an error.

Exit code 0 = success (build wrote the database, query printed its hits, possibly none);
2 = usage or environment error — a missing subcommand/argument (argparse), `--repo` that is not a
directory, `--limit < 1`, an empty or syntactically invalid MATCH expression, a missing/corrupt
database, and a Python whose sqlite3 lacks FTS5 (`CREATE VIRTUAL TABLE ... USING fts5` fails:
`FTS5 unavailable`). Every error is a message on stderr, never a traceback. stdlib only.
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import subprocess
import sys

# Sibling script imported as a library: the code-base walk, the exclusion policy and the binary
# heuristic must have exactly ONE implementation, shared with the shard protocol.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import repo_inventory  # noqa: E402  (needs the sys.path line above)

TABLE = "precedents"
COLUMNS = ("source", "path", "title", "content")
CONTENT_COLUMN = COLUMNS.index("content")
SOURCES = ("change-log", "summary", "code")
DEFAULT_DB = pathlib.Path(".code-factory") / "state" / "precedents.db"
CHANGE_LOG = "memory/change-log.md"
SUMMARY = "memory/summary.md"
PREAMBLE_TITLE = "(preamble)"
# Repo-relative prefixes never indexed as code.
EXCLUDE_PREFIXES = (".code-factory/", "skill-base/golden-set/")
# The two memory files are indexed as `change-log`/`summary` records, never as code.
MEMORY_PATHS = (CHANGE_LOG, SUMMARY)
MAX_FILE_BYTES = 200 * 1024
SNIPPET_OPEN, SNIPPET_CLOSE, SNIPPET_ELLIPSIS = "[", "]", "..."
SNIPPET_TOKENS = 12
TITLE_CLIP, SNIPPET_CLIP = 100, 300


class PrecedentError(Exception):
    """A usage/environment error: the CLI reports it as `error: ...` with exit code 2."""


def fts5_error() -> str | None:
    """None when this interpreter's sqlite3 was built with FTS5, else the sqlite error text."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(x)")
    except sqlite3.Error as exc:
        return str(exc)
    finally:
        conn.close()
    return None


def fts5_supported() -> bool:
    """True when FTS5 is available — without it the precedent index cannot exist at all."""
    return fts5_error() is None


def read_text(path: pathlib.Path, max_bytes: int | None = MAX_FILE_BYTES) -> str | None:
    """Decoded text of `path`, or None when it is unreadable, binary or too large.

    `max_bytes=None` lifts the size cap: the memory files are the most valuable source and must
    never be dropped silently, while the cap keeps a stray generated blob out of the code base.
    """
    try:
        if max_bytes is not None and path.stat().st_size > max_bytes:
            return None
    except OSError:
        return None
    data = repo_inventory.read_bytes(path)
    if data is None or repo_inventory.is_binary(data):
        return None
    return data.decode("utf-8", errors="replace")


def split_sections(text: str) -> list[tuple[str | None, str]]:
    """Text split on `## ` headings into `(title, body)`; the part before the first heading is
    returned as `(None, body)` — `None` marks the preamble, a caller titles it. An empty
    preamble yields no record, so a file that starts with a heading has no empty first entry.
    """
    blocks: list[tuple[str | None, list[str]]] = []
    title: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            blocks.append((title, body))
            title, body = line[3:].strip(), []
        else:
            body.append(line)
    blocks.append((title, body))

    records: list[tuple[str | None, str]] = []
    for block_title, block_body in blocks:
        if block_title is None and not any(line.strip() for line in block_body):
            continue
        records.append((block_title, "\n".join(block_body).strip("\n")))
    return records


def section_records(path: str, text: str, source: str) -> list[tuple[str, str, str, str]]:
    """One `(source, path, title, content)` record per `## ` section of a memory file."""
    records: list[tuple[str, str, str, str]] = []
    for title, body in split_sections(text):
        heading = title if title is not None else PREAMBLE_TITLE
        content = body if title is None else f"## {title}\n{body}"
        records.append((source, path, heading, content.strip("\n")))
    return records


def git_files(root: pathlib.Path) -> list[str] | None:
    """Tracked files as sorted repo-relative posix paths, or None when git cannot answer.

    None means "no git here" (not installed, not a repository, or git refused) and sends the
    caller to the directory walk — a project without git is still fully indexed.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    listed = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return sorted(path for path in listed if path)


def walk_files(root: pathlib.Path) -> list[str]:
    """Fallback file list when git is unavailable: the shard-protocol walk, repo-relative posix."""
    return [path.relative_to(root).as_posix() for path in repo_inventory.iter_files(root)]


def indexable_code_paths(root: pathlib.Path, paths: list[str]) -> list[str]:
    """The listed repo-relative paths that are indexed as code, sorted and de-duplicated.

    Symbolic links are excluded explicitly: `is_file()` FOLLOWS a link, so the git scan — which
    lists every tracked path, a tracked symlink included — would index one while the directory walk
    of `repo_inventory.py` skips it, and `git scan == walk` would stop holding on the same tree.
    """
    return sorted({rel for rel in paths
                   if rel not in MEMORY_PATHS
                   and not rel.startswith(EXCLUDE_PREFIXES)
                   and (root / rel).is_file()
                   and not (root / rel).is_symlink()})


def collect_records(root: pathlib.Path) -> tuple[list[tuple[str, str, str, str]], str]:
    """(records sorted by source/path/title, mode of the code scan: `git` or `walk`).

    Sorting is what makes the index deterministic: the row order — and therefore every
    `rowid`-based view of it — is a function of the working tree alone, not of the filesystem.
    """
    records: list[tuple[str, str, str, str]] = []
    for rel, source in ((CHANGE_LOG, "change-log"), (SUMMARY, "summary")):
        text = read_text(root / rel, max_bytes=None)
        if text is not None:
            records.extend(section_records(rel, text, source))

    listed = git_files(root)
    mode = "git" if listed is not None else "walk"
    if listed is None:
        listed = walk_files(root)
    for rel in indexable_code_paths(root, listed):
        text = read_text(root / rel)
        if text is not None:
            records.append(("code", rel, pathlib.PurePosixPath(rel).name, text))

    records.sort(key=lambda record: (record[0], record[1], record[2]))
    return records, mode


def _create_and_fill(db: pathlib.Path, records: list[tuple[str, str, str, str]]) -> None:
    """Create the FTS5 table and insert every record in the given (sorted) order."""
    try:
        conn = sqlite3.connect(db)
    except sqlite3.Error as exc:
        raise PrecedentError(f"cannot open the precedent index {db}: {exc}") from exc
    try:
        try:
            conn.execute(f"CREATE VIRTUAL TABLE {TABLE} USING fts5({', '.join(COLUMNS)})")
        except sqlite3.OperationalError as exc:
            # An sqlite3 without FTS5 answers "no such module: fts5" right here.
            raise PrecedentError(f"FTS5 unavailable in this Python/sqlite3 build ({exc}); "
                                 f"the precedent index {db} cannot be built") from exc
        try:
            conn.executemany(f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES (?, ?, ?, ?)",
                             records)
            conn.commit()
        except sqlite3.Error as exc:
            raise PrecedentError(f"cannot fill the precedent index {db}: {exc}") from exc
    finally:
        conn.close()


def source_counts(records: list[tuple[str, str, str, str]]) -> dict[str, int]:
    """Record count per source, one key per SOURCES entry (0 when a source is empty)."""
    counts = {source: 0 for source in SOURCES}
    for record in records:
        counts[record[0]] = counts.get(record[0], 0) + 1
    return counts


def build_index(root: pathlib.Path, db: pathlib.Path) -> dict:
    """Deterministically (re)build the index at `db`; returns the counters to report.

    Raises PrecedentError when `root` is not a directory, FTS5 is missing, or the database cannot
    be written; a failed build never leaves a half-written index behind.
    """
    if not root.is_dir():
        raise PrecedentError(f"--repo is not a directory: {root}")
    reason = fts5_error()
    if reason is not None:
        raise PrecedentError(f"FTS5 unavailable in this Python/sqlite3 build ({reason}); "
                             f"the precedent index needs FTS5")
    records, mode = collect_records(root)
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        for stale in (db, pathlib.Path(f"{db}-wal"), pathlib.Path(f"{db}-shm")):
            stale.unlink(missing_ok=True)  # rebuild: the previous index never lingers
        _create_and_fill(db, records)
    except PrecedentError:
        db.unlink(missing_ok=True)
        raise
    except OSError as exc:
        db.unlink(missing_ok=True)
        raise PrecedentError(f"cannot build the precedent index {db}: {exc}") from exc
    return {"db": db, "records": records, "mode": mode}


def search(db: pathlib.Path, match: str, limit: int) -> list[dict]:
    """Up to `limit` hits for the FTS5 MATCH expression `match`, best rank first.

    Snippets are collapsed to one line so a hit never breaks the compact CLI output. An invalid
    MATCH expression or a database that is not a precedent index raises sqlite3.DatabaseError.
    """
    conn = sqlite3.connect(db)
    try:
        sql = (f"SELECT source, path, title, "
               f"snippet({TABLE}, {CONTENT_COLUMN}, ?, ?, ?, ?) AS snippet, "
               f"bm25({TABLE}) AS score "
               f"FROM {TABLE} WHERE {TABLE} MATCH ? ORDER BY score LIMIT ?")
        rows = conn.execute(sql, (SNIPPET_OPEN, SNIPPET_CLOSE, SNIPPET_ELLIPSIS, SNIPPET_TOKENS,
                                  match, limit)).fetchall()
    finally:
        conn.close()
    return [{"rank": rank, "source": source, "path": path, "title": title,
             "snippet": " ".join(snippet.split()), "score": score}
            for rank, (source, path, title, snippet, score) in enumerate(rows, 1)]


def clip(text: str, limit: int) -> str:
    """`text` shortened to `limit` characters (compact, deterministic one-line output)."""
    return text if len(text) <= limit else text[:limit - 3] + "..."


def render_build(result: dict) -> str:
    """Human-readable summary of a build: where the index is and what went into it."""
    counts = source_counts(result["records"])
    scan = "git ls-files" if result["mode"] == "git" else "directory walk"
    return (f"db: {result['db']}\n"
            f"records: {len(result['records'])} (change-log: {counts['change-log']}, "
            f"summary: {counts['summary']}, code: {counts['code']})\n"
            f"code scan: {scan}\n")


def render_hits(text: str, hits: list[dict], db: pathlib.Path) -> str:
    """Rank, source, path, title and bracketed snippet of every hit — a few lines in total."""
    lines = [f"db: {db}", f"query: {text}", f"matches: {len(hits)}"]
    for hit in hits:
        label = hit["path"]
        if hit["title"] and hit["title"] != label and not label.endswith("/" + hit["title"]):
            label = f"{label} — {clip(hit['title'], TITLE_CLIP)}"
        lines.append(f"#{hit['rank']} [{hit['source']}] {label}")
        lines.append(f"    {clip(hit['snippet'], SNIPPET_CLIP)}")
    return "\n".join(lines) + "\n"


def resolve_db(root: pathlib.Path, out: str | None) -> pathlib.Path:
    """The database path: the default under the repo, a relative `--out` resolved against it."""
    path = pathlib.Path(out) if out else DEFAULT_DB
    return path if path.is_absolute() else root / path


def cmd_build(args: argparse.Namespace) -> int:
    result = build_index(pathlib.Path(args.repo), resolve_db(pathlib.Path(args.repo), args.out))
    sys.stdout.write(render_build(result))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo)
    if not root.is_dir():
        raise PrecedentError(f"--repo is not a directory: {root}")
    if args.limit < 1:
        raise PrecedentError(f"--limit must be >= 1, got {args.limit}")
    text = args.text.strip()
    if not text:
        raise PrecedentError("the query text is empty; pass an FTS5 MATCH expression")
    db = resolve_db(root, args.out)
    if not db.is_file():
        raise PrecedentError(f"precedent index not found: {db} "
                             f"(run `build --repo {args.repo}` first)")
    try:
        hits = search(db, text, args.limit)
    except sqlite3.DatabaseError as exc:
        detail = str(exc)
        if "syntax error" in detail:
            raise PrecedentError(f"invalid FTS5 MATCH expression {text!r}: {detail}") from exc
        if "no such table" in detail:
            raise PrecedentError(f"{db} is not a precedent index (no `{TABLE}` table); "
                                 f"rebuild it with `build --repo {args.repo}`") from exc
        raise PrecedentError(f"cannot query {db}: {detail}") from exc
    sys.stdout.write(render_hits(text, hits, db))
    return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help. Indexed hits
    need the same protection. `errors="replace"` keeps a stream that cannot be reconfigured from
    ever raising.
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
    sub = ap.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="rebuild the FTS5 index of memory/ and the code base")
    p_build.add_argument("--repo", required=True, help="Repository root")
    p_build.add_argument("--out", default=None,
                         help=f"Database to write (default: <repo>/{DEFAULT_DB.as_posix()})")
    p_build.set_defaults(func=cmd_build)

    p_query = sub.add_parser("query", help="search the index with an FTS5 MATCH expression")
    p_query.add_argument("--repo", required=True, help="Repository root")
    p_query.add_argument("text", help='FTS5 MATCH expression, e.g. "a b", a OR b, NEAR(a b)')
    p_query.add_argument("--limit", type=int, default=10, help="Maximum hits (default: 10)")
    p_query.add_argument("--out", default=None,
                         help=f"Database to read (default: <repo>/{DEFAULT_DB.as_posix()})")
    p_query.set_defaults(func=cmd_query)

    args = ap.parse_args()
    try:
        return args.func(args)
    except PrecedentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (sqlite3.Error, OSError) as exc:  # backstop: a failure is a message, never a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
