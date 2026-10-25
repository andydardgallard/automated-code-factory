#!/usr/bin/env python3
"""
Deterministic FTS5 precedent index of a project's memory and code base (zero LLM tokens).

Asked "how was something like this solved before?" an analyzer or diagnostician must not re-read
the whole repository: this script builds ONE SQLite FTS5 index out of the two things that answer
that question — the project memory (`memory/change-log.md` and `memory/summary.md`) and the code
base — and answers free-text queries out of it.

Usage:
  python precedent_index.py build --repo <root> [--db <path>] [--quiet]
  python precedent_index.py status --repo <root> [--db <path>]
  python precedent_index.py query --repo <root> [--fresh] <terms...> [--limit 10]

`build` writes `<repo>/.code-factory/state/precedents.db` by default (`--db` overrides it, the
legacy alias `--out` still works, a relative path is resolved against the repo root) and is an
IDEMPOTENT, DETERMINISTIC REBUILD: the previous database and its -wal/-shm sidecars are deleted,
the records are collected in sorted `(source, path, title)` order and inserted in exactly that
order, so the same working tree always yields the same table — the same row count and the same
content hash (`status` prints it) — a second build over unchanged sources changes nothing, and a
source that disappeared takes its rows with it. A factory-sized repository rebuilds in well under a
second, so a run rebuilds instead of trusting an index somebody built once.

Freshness is recorded, not assumed: the `meta` table of the index holds, per source, the sha256 of
`memory/change-log.md`, the sha256 of `memory/summary.md`, the sha256 of the manifest of the
indexed code tree (repo-relative path, size, `mtime_ns` and content sha256 of every indexed file)
and the build time. The content digest is part of the manifest on purpose: a same-size edit that
preserves the mtime (os.utime, a filesystem with a coarse mtime) is invisible to a size+mtime
signature, and it must still be STALE. `status` compares them with the sources as they are NOW and
prints
`FRESH - <n> records, <m> files (built <time>)` plus `hash: <sha256 of the rows>` with exit 0, or
`STALE - <reason>` with exit 1, the reason naming the cause: the journal changed after the last
build, the summary changed, the tracked tree changed, the meta record is missing, or the database
is absent. `query --fresh` refuses to answer a stale index — `STALE - <reason> (run:
precedent_index.py build --repo <root>)`, exit 3 — so a stale index can never quietly report
`matches: 0`.

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

Schema: the FTS5 virtual table `precedents(source TEXT, path TEXT, title TEXT, content TEXT)` plus
the key/value table `meta(key TEXT, value TEXT)` that carries the freshness record described above.
`query` runs an FTS5 MATCH over `precedents` — raw FTS5 syntax is accepted (`"a b"`, `a OR b`,
`NEAR(a b)`); an expression FTS5 cannot parse is retried with every non-bareword token quoted, so a
hyphenated term such as a `run_id` (`20261025-634bc01b`, which FTS5 would read as `20261025` MINUS
a column named `634bc01b`) is searched as a phrase instead of failing. `query` prints, per hit, the
rank, the source, the path, the title and a `snippet()` of the content with the matched terms in
brackets, best rank first. Zero matches is not an error.

Exit code 0 = success (build wrote the database, status reported FRESH, query printed its hits,
possibly none); 1 = `status` found a STALE index; 2 = usage or environment error — a missing
subcommand/argument (argparse), `--repo` that is not a directory, `--limit < 1`, an empty or
unparseable MATCH expression, a missing/corrupt database, and a Python whose sqlite3 lacks FTS5
(`CREATE VIRTUAL TABLE ... USING fts5` fails: `FTS5 unavailable`); 3 = `query --fresh` refused to
answer a stale index. Every error is a message on stderr, never a traceback. stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

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
# The freshness record of a build, as a key/value table inside the same database.
META_TABLE = "meta"
SCHEMA_VERSION = "1"
FRESH, STALE = "fresh", "stale"
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


def code_paths(root: pathlib.Path) -> tuple[list[str], str]:
    """(indexed code paths sorted, scan mode `git` or `walk`).

    One listing feeds both the index and its manifest hash, so what is hashed is exactly what is
    indexed — a source that is not in the index can never make it stale.
    """
    listed = git_files(root)
    if listed is None:
        return indexable_code_paths(root, walk_files(root)), "walk"
    return indexable_code_paths(root, listed), "git"


def file_sha(path: pathlib.Path) -> str:
    """sha256 of a file's bytes, or "" when it is absent or unreadable — absence is a value too."""
    data = repo_inventory.read_bytes(path)
    return "" if data is None else hashlib.sha256(data).hexdigest()


def content_sha(path: pathlib.Path) -> str:
    """Streamed sha256 of a file's content, or "" when it is unreadable — never raises."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def tree_manifest(root: pathlib.Path, paths: list[str], skip: set[pathlib.Path]) -> str:
    """sha256 over `path\\0size\\0mtime_ns\\0content sha256` of the indexed files: the tree signature.

    Size and modification time keep a plain edit visible at a glance; the content digest is what
    closes the hole a same-size edit with a preserved mtime (os.utime, a coarse-mtime filesystem)
    would otherwise slip through — such an edit is STALE too. `skip` drops the live database and
    its sidecars, so the index is never its own source.
    """
    hasher = hashlib.sha256()
    for rel in sorted(paths):
        full = root / rel
        try:
            if full.resolve() in skip:
                continue
            stat = full.stat()
        except OSError:
            continue  # a vanished or unreadable file is not part of the tree either
        hasher.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\0{content_sha(full)}\n"
                      .encode("utf-8"))
    return hasher.hexdigest()


def signature(root: pathlib.Path, db: pathlib.Path | None = None) -> dict[str, str]:
    """The sha256 signature of every indexed source: both memory files and the code tree."""
    paths, _ = code_paths(root)
    skip: set[pathlib.Path] = set() if db is None else {
        db.resolve(), pathlib.Path(f"{db}-wal").resolve(), pathlib.Path(f"{db}-shm").resolve()}
    return {"journal_sha": file_sha(root / CHANGE_LOG),
            "summary_sha": file_sha(root / SUMMARY),
            "tree_sha": tree_manifest(root, paths, skip)}


def utc_now() -> str:
    """The build time as `YYYY-MM-DDTHH:MM:SSZ` (UTC, second resolution)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    paths, mode = code_paths(root)
    for rel in paths:
        text = read_text(root / rel)
        if text is not None:
            records.append(("code", rel, pathlib.PurePosixPath(rel).name, text))

    records.sort(key=lambda record: (record[0], record[1], record[2]))
    return records, mode


def index_meta(root: pathlib.Path, db: pathlib.Path, mode: str) -> dict[str, str]:
    """The `meta` record of a build: the per-source signatures, the scan mode and the build time."""
    return {**signature(root, db), "schema_version": SCHEMA_VERSION, "scan_mode": mode,
            "built_at": utc_now()}


def _create_and_fill(db: pathlib.Path, records: list[tuple[str, str, str, str]],
                     meta: dict[str, str]) -> None:
    """Create the FTS5 and meta tables and insert every record in the given (sorted) order."""
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
            conn.execute(f"CREATE TABLE {META_TABLE} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.executemany(f"INSERT INTO {META_TABLE} (key, value) VALUES (?, ?)",
                             sorted(meta.items()))
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
    # The signature is taken AFTER the records were read: a source edited in between makes the next
    # `status` STALE (a false STALE costs one rebuild) instead of falsely FRESH (which would answer
    # out of a stale index — the defect this record exists to prevent).
    meta = index_meta(root, db, mode)
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        for stale in (db, pathlib.Path(f"{db}-wal"), pathlib.Path(f"{db}-shm")):
            stale.unlink(missing_ok=True)  # rebuild: the previous index never lingers
        _create_and_fill(db, records, meta)
    except PrecedentError:
        db.unlink(missing_ok=True)
        raise
    except OSError as exc:
        db.unlink(missing_ok=True)
        raise PrecedentError(f"cannot build the precedent index {db}: {exc}") from exc
    return {"db": db, "records": records, "mode": mode, "meta": meta, "hash": index_hash(db)}


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


def is_bareword(token: str) -> bool:
    """True when FTS5 reads `token` as a bareword (alphanumerics, `_`, non-ASCII only)."""
    return bool(token) and all(char.isalnum() or char == "_" or ord(char) >= 0x80
                               for char in token)


def quote_nonbarewords(text: str) -> str:
    """`text` with every token FTS5 cannot read as a bareword turned into a quoted phrase."""
    tokens = []
    for token in text.split():
        if not is_bareword(token) and any(char.isalnum() or ord(char) >= 0x80 for char in token):
            tokens.append('"' + token.replace('"', '""') + '"')
        else:
            tokens.append(token)
    return " ".join(tokens)


def search_any(db: pathlib.Path, text: str, limit: int) -> list[dict]:
    """`search`, retrying an unparseable expression with its non-bareword tokens quoted.

    FTS5 reads `20261025-634bc01b` as `20261025` MINUS a column named `634bc01b` and answers
    "no such column" — and that hyphenated shape is a run_id, a file name or a path fragment, i.e.
    the most likely thing a caller greps for. Quoting such a token searches it as a phrase and
    finds the record; an expression that stays unparseable raises the original error unchanged.
    """
    try:
        return search(db, text, limit)
    except sqlite3.OperationalError as exc:
        quoted = quote_nonbarewords(text)
        if quoted == text:
            raise
        try:
            return search(db, quoted, limit)
        except sqlite3.OperationalError:
            raise exc


def read_meta(db: pathlib.Path) -> dict[str, str] | None:
    """The meta record of the index at `db`, or None when it carries none (an older build).

    A file that is not a precedent index at all — corrupt, foreign, unreadable — raises
    PrecedentError, so a broken database is reported and never mistaken for a stale one.
    """
    conn = sqlite3.connect(db)
    try:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if TABLE not in names:
            raise PrecedentError(f"{db} is not a precedent index (no `{TABLE}` table); "
                                 f"rebuild it with `build`")
        if META_TABLE not in names:
            return None
        return dict(conn.execute(f"SELECT key, value FROM {META_TABLE}"))
    finally:
        conn.close()


def index_counts(db: pathlib.Path) -> tuple[int, int]:
    """(records, files) of the index at `db`: every row, and the distinct indexed code paths."""
    conn = sqlite3.connect(db)
    try:
        records = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        files = conn.execute(f"SELECT COUNT(DISTINCT path) FROM {TABLE} "
                             f"WHERE source = 'code'").fetchone()[0]
    finally:
        conn.close()
    return int(records), int(files)


def record_hash(rows: list[tuple[str, str, str, str]]) -> str:
    """sha256 over the rows as `len:field` pairs — the content hash two builds are compared by.

    Length-prefixing keeps the encoding unambiguous: no separator can be forged from a record.
    """
    hasher = hashlib.sha256()
    for row in rows:
        for field in row:
            hasher.update(f"{len(field)}:".encode("ascii") + field.encode("utf-8", "replace"))
    return hasher.hexdigest()


def index_hash(db: pathlib.Path) -> str:
    """The content hash of the rows of `db`, ordered by content so it is rebuild-order free."""
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM {TABLE} "
                            f"ORDER BY {', '.join(COLUMNS)}").fetchall()
    finally:
        conn.close()
    return record_hash(rows)


def freshness(root: pathlib.Path, db: pathlib.Path) -> tuple[str, dict]:
    """(FRESH|STALE, details) of the index at `db` against the sources of `root` as they are NOW.

    `details` always carries `reason` (None when fresh), `records`, `files`, `built_at` and `hash`
    (None when they cannot be read). A missing database is STALE — an absent index is a fact, not a
    crash; a corrupt one raises PrecedentError, because that is an environment error.
    """
    details: dict = {"reason": None, "records": None, "files": None, "built_at": None,
                     "hash": None}
    if not db.is_file():
        return STALE, {**details, "reason": f"database absent: {db}"}
    try:
        meta = read_meta(db)
        details["records"], details["files"] = index_counts(db)
        details["hash"] = index_hash(db)
    except sqlite3.Error as exc:
        raise PrecedentError(f"cannot read the precedent index {db}: {exc}") from exc
    if meta is None:
        return STALE, {**details, "reason": "meta missing: the index carries no freshness record"}
    details["built_at"] = meta.get("built_at")
    current = signature(root, db)
    for key, reason in (("journal_sha", f"journal changed after the last build ({CHANGE_LOG})"),
                        ("summary_sha", f"summary changed after the last build ({SUMMARY})"),
                        ("tree_sha", "tracked tree changed after the last build")):
        if meta.get(key) != current[key]:
            return STALE, {**details, "reason": reason}
    return FRESH, details


def clip(text: str, limit: int) -> str:
    """`text` shortened to `limit` characters (compact, deterministic one-line output)."""
    return text if len(text) <= limit else text[:limit - 3] + "..."


def render_build(result: dict) -> str:
    """Human-readable summary of a build: where the index is and what went into it."""
    counts = source_counts(result["records"])
    scan = "git ls-files" if result["mode"] == "git" else "directory walk"
    meta = result["meta"]
    return (f"db: {result['db']}\n"
            f"records: {len(result['records'])} (change-log: {counts['change-log']}, "
            f"summary: {counts['summary']}, code: {counts['code']})\n"
            f"code scan: {scan}\n"
            f"meta: journal {meta['journal_sha'][:12] or '-'}, "
            f"summary {meta['summary_sha'][:12] or '-'}, tree {meta['tree_sha'][:12]}\n"
            f"built: {meta['built_at']}\n"
            f"hash: {result['hash']}\n")


def render_status(state: str, details: dict) -> str:
    """The `FRESH` line with the content hash, or the one-line `STALE - <reason>` verdict."""
    if state == FRESH:
        return (f"FRESH - {details['records']} records, {details['files']} files "
                f"(built {details['built_at']})\n"
                f"hash: {details['hash']}\n")
    return f"STALE - {details['reason']}\n"


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
    """The database path: the default under the repo, a relative `--db` resolved against it."""
    path = pathlib.Path(out) if out else DEFAULT_DB
    return path if path.is_absolute() else root / path


def cmd_build(args: argparse.Namespace) -> int:
    result = build_index(pathlib.Path(args.repo), resolve_db(pathlib.Path(args.repo), args.out))
    if not args.quiet:
        sys.stdout.write(render_build(result))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo)
    if not root.is_dir():
        raise PrecedentError(f"--repo is not a directory: {root}")
    state, details = freshness(root, resolve_db(root, args.out))
    sys.stdout.write(render_status(state, details))
    return 0 if state == FRESH else 1


def cmd_query(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.repo)
    if not root.is_dir():
        raise PrecedentError(f"--repo is not a directory: {root}")
    if args.limit < 1:
        raise PrecedentError(f"--limit must be >= 1, got {args.limit}")
    text = " ".join(args.text).strip()
    if not text:
        raise PrecedentError("the query text is empty; pass an FTS5 MATCH expression")
    db = resolve_db(root, args.out)
    if args.fresh:
        # A stale index must never answer "matches: 0" as if the history had nothing to say.
        state, details = freshness(root, db)
        if state == STALE:
            sys.stdout.write(f"STALE - {details['reason']} "
                             f"(run: precedent_index.py build --repo {args.repo})\n")
            return 3
    elif not db.is_file():
        raise PrecedentError(f"precedent index not found: {db} "
                             f"(run `build --repo {args.repo}` first)")
    try:
        hits = search_any(db, text, args.limit)
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


def add_db_argument(parser: argparse.ArgumentParser, verb: str) -> None:
    """`--db` plus its legacy alias `--out` — one destination, so both name the same file."""
    parser.add_argument("--db", dest="out", default=None,
                        help=f"{verb} (default: <repo>/{DEFAULT_DB.as_posix()})")
    parser.add_argument("--out", dest="out", default=None, help="Legacy alias of --db")


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build",
                             help="(re)build the FTS5 index of memory/ and the code base")
    p_build.add_argument("--repo", required=True, help="Repository root")
    add_db_argument(p_build, "Database to write")
    p_build.add_argument("--quiet", action="store_true", help="Report nothing on success")
    p_build.set_defaults(func=cmd_build)

    p_status = sub.add_parser("status",
                              help="FRESH/STALE verdict of the index against the sources")
    p_status.add_argument("--repo", required=True, help="Repository root")
    add_db_argument(p_status, "Database to read")
    p_status.set_defaults(func=cmd_status)

    p_query = sub.add_parser("query", help="search the index with an FTS5 MATCH expression")
    p_query.add_argument("--repo", required=True, help="Repository root")
    p_query.add_argument("text", nargs="+",
                         help='FTS5 MATCH expression, e.g. "a b", a OR b, NEAR(a b)')
    p_query.add_argument("--limit", type=int, default=10, help="Maximum hits (default: 10)")
    p_query.add_argument("--fresh", action="store_true",
                         help="Refuse to answer a stale index (exit 3) instead of guessing")
    add_db_argument(p_query, "Database to read")
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
