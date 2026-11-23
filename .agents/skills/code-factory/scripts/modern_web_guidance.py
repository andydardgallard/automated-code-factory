#!/usr/bin/env python3
"""
Local, pinned Modern Web Guidance adapter (zero LLM tokens, no network, no package manager, no
execution of any downloaded code).

The upstream corpus is a directory of Markdown guides shipped from exactly one reviewed commit.
Upstream asks agents to resolve and run a published command-line tool at call time, which installs
a moving `latest` and runs third-party code — the opposite of a reviewed, reproducible source. The
factory therefore materializes the reviewed tree once into the run cache and reads it as DATA with
this stdlib adapter: the guide text is inert reference material, never a command.

Catalog layout (the safe reference cache, `<repo>/.code-factory/cache/reference-docs/
modern-web-guidance`; `--catalog <dir>` overrides it):

  catalog.json  {"source": <canonical HTTPS Git URL>, "revision": <full 40-hex commit sha>,
                 "entries": [{"id", "title", "summary", "body",
                              "stability": "stable"|"unstable", "tags": [...],
                              "fallback": <text, optional>}]}
  pin.json      {"source": ..., "revision": ...}   the reviewed pin the catalog must agree with

Freshness is deterministic and fail-closed: FRESH only when the catalog and its pin agree on the
canonical source AND the exact full commit sha. A divergent, short, moving or absent revision, a
foreign source, a missing pin and malformed JSON are never FRESH, and every read refuses to answer.

Commands (JSON on stdout; usage errors exit 2, data/configuration errors exit 1 as `ERROR: ...`):

  status        report FRESH / STALE / MALFORMED / MISSING without answering any query
  search        bounded text query ranked over the catalog's own text; matches only, so no match
                is an empty result and not an error
  retrieve      lowercase catalog identifiers (never a path), deduplicated; unstable guidance is
                gated behind an explicit `.mwgrc` boolean AND a declared safe fallback
  legacy-scan   obsolete web-platform patterns in a target confined to the repository; zero
                findings is SUCCESS, never a claim that the code is modern, while an input the
                scan cannot read is a refusal instead of a silent hole in its own coverage
  check-session require the EVIDENCE itself: a recorded search followed by a retrieval, and no
                retrieval without a preceding search in this repository — a missing journal, an
                empty journal and an unfollowed search all fail closed
  build         derive catalog.json + pin.json from a materialized pinned tree (the only writer)

Usage evidence is recorded in `.code-factory/state/modern-web-guidance/usage.json`, bound to the
CURRENT run: the journal and every event carry the `run_id` of the WIP checkpoint
(`.code-factory/state/pipeline.yaml`) and each event carries the catalog revision it was recorded
against, so an unbound, stale-run, mixed-run or stale-revision journal is refused instead of being
accepted as this run's proof. One journal holds ONE run: when the checkpoint's run_id changes, the
prior run's evidence is moved aside as `usage.<run_id>.json` (history is preserved on disk, never
deleted) and an empty current-run journal starts, so earlier runs' events can never make
`check-session` reject evidence this run really recorded. Retrieving a guide without a preceding
search invalidates the session (`check-session` exits 1 naming the id).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

CANONICAL_SOURCE = "https://github.com/GoogleChrome/modern-web-guidance.git"

CACHE_SUBDIR = (".code-factory", "cache", "reference-docs", "modern-web-guidance")
STATE_SUBDIR = (".code-factory", "state", "modern-web-guidance")
CATALOG_FILENAME = "catalog.json"
PIN_FILENAME = "pin.json"
USAGE_FILENAME = "usage.json"

REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

MAX_QUERY_CHARS = 200
# The documented query shape ("one to five plain words"): a search addresses ONE capability, so a
# sixth word is the boundary that is refused, while a single word is legitimate.
MAX_QUERY_WORDS = 5
DEFAULT_LIMIT = 5
MAX_LIMIT = 50
MAX_BODY_CHARS = 400_000
MAX_FALLBACK_CHARS = 2_000
MAX_FILES_SCANNED = 5_000
MAX_FINDINGS = 500
MAX_USAGE_EVENTS = 1_000

FIELD_WEIGHTS = {"id": 6, "tags": 4, "title": 3, "summary": 2, "body": 1}

SCAN_SUFFIXES = frozenset({
    ".html", ".htm", ".xhtml", ".css", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".vue", ".svelte", ".astro",
})
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".code-factory", "node_modules", "bower_components", "vendor",
    "dist", "build", "out", "coverage", ".next", ".nuxt", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".cache",
})

STATUS_FRESH = "FRESH"
STATUS_STALE = "STALE"
STATUS_MALFORMED = "MALFORMED"
STATUS_MISSING = "MISSING"

STABILITY_STABLE = "stable"
STABILITY_UNSTABLE = "unstable"

CONSENT_KEY = "allow_unstable_features"


class CliError(Exception):
    """A refusal the caller must see as `ERROR: ...` on stderr with no traceback."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so help and messages never crash a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def default_catalog_dir(repo) -> pathlib.Path:
    """The safe reference cache holding the pinned catalog of one repository."""
    return pathlib.Path(repo).joinpath(*CACHE_SUBDIR)


def usage_path(repo: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(repo).joinpath(*STATE_SUBDIR) / USAGE_FILENAME


# --------------------------------------------------------------------------- catalog reads


def _read_json(path: pathlib.Path):
    """Return (data, problem); `problem` is a human-readable reason or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"{path.name} does not exist"
    except OSError as exc:
        return None, f"{path.name} cannot be read: {exc}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"{path.name} is not valid JSON ({exc.msg} at line {exc.lineno})"


def _entry_stability(entry: dict) -> str:
    """Unknown or absent stability is treated as UNSTABLE: the gate fails closed."""
    value = entry.get("stability")
    if isinstance(value, str) and value.strip().lower() == STABILITY_STABLE:
        return STABILITY_STABLE
    return STABILITY_UNSTABLE


def _validated_entries(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CliError("the catalog's `entries` must be a list of guide records")
    entries: list[dict] = []
    seen: set[str] = set()
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CliError(f"catalog entry #{position + 1} is not a JSON object")
        guide_id = item.get("id")
        if not isinstance(guide_id, str) or not ID_RE.match(guide_id):
            raise CliError(f"catalog entry #{position + 1} has no lowercase identifier: "
                           f"{guide_id!r}")
        if guide_id in seen:
            raise CliError(f"catalog entry #{position + 1} repeats the identifier {guide_id!r}")
        seen.add(guide_id)
        for key in ("title", "summary", "body"):
            if not isinstance(item.get(key), str):
                raise CliError(f"catalog entry {guide_id!r} has no {key}")
        tags = item.get("tags")
        if tags is not None and not isinstance(tags, list):
            raise CliError(f"catalog entry {guide_id!r} has non-list tags")
        fallback = item.get("fallback")
        if fallback is not None and not isinstance(fallback, str):
            raise CliError(f"catalog entry {guide_id!r} has a non-text fallback")
        entries.append(item)
    return entries


def inspect_catalog(directory: pathlib.Path) -> dict:
    """Classify a catalog directory without ever answering a query from an unproven one."""
    report = {
        "status": STATUS_MISSING,
        "reason": "",
        "catalog": str(directory),
        "source": None,
        "revision": None,
        "entries": [],
    }
    if not directory.is_dir():
        report["reason"] = "the catalog directory does not exist"
        return report
    catalog_path = directory / CATALOG_FILENAME
    if not catalog_path.is_file():
        report["reason"] = f"{CATALOG_FILENAME} does not exist"
        return report
    catalog, problem = _read_json(catalog_path)
    if problem:
        report["status"] = STATUS_MALFORMED
        report["reason"] = problem
        return report
    if not isinstance(catalog, dict):
        report["status"] = STATUS_MALFORMED
        report["reason"] = f"{CATALOG_FILENAME} must hold a JSON object"
        return report
    try:
        report["entries"] = _validated_entries(catalog.get("entries"))
    except CliError as exc:
        report["status"] = STATUS_MALFORMED
        report["reason"] = str(exc)
        return report
    source = catalog.get("source")
    revision = catalog.get("revision")
    report["source"] = source if isinstance(source, str) else None
    report["revision"] = revision if isinstance(revision, str) else None
    report["status"] = STATUS_STALE

    pin, pin_problem = _read_json(directory / PIN_FILENAME)
    if pin_problem:
        report["reason"] = f"{pin_problem} — an unpinned catalog is never FRESH"
        return report
    if not isinstance(pin, dict):
        report["status"] = STATUS_MALFORMED
        report["reason"] = f"{PIN_FILENAME} must hold a JSON object"
        return report
    for label, value in (("catalog", source), ("pin", pin.get("source"))):
        if value != CANONICAL_SOURCE:
            report["reason"] = (f"the {label} source is {value!r}, not the reviewed "
                                f"{CANONICAL_SOURCE!r}")
            return report
    for label, value in (("catalog", revision), ("pin", pin.get("revision"))):
        if not isinstance(value, str) or not REVISION_RE.match(value):
            report["reason"] = (f"the {label} revision is {value!r}, not a full 40-hex commit "
                                f"sha — a branch, a tag and an abbreviated sha are never reviewed")
            return report
    if pin.get("revision") != revision:
        report["reason"] = (f"the pin names {pin.get('revision')!r} but the catalog holds "
                            f"{revision!r} — the cache diverged from its pin")
        return report
    report["status"] = STATUS_FRESH
    report["reason"] = "the catalog and its pin agree on the canonical source and the exact commit"
    return report


def load_fresh_catalog(directory: pathlib.Path) -> dict:
    """Return the FRESH catalog report or refuse: every read of stale/missing data fails closed."""
    report = inspect_catalog(directory)
    if report["status"] == STATUS_FRESH:
        return report
    if report["status"] == STATUS_MISSING:
        raise CliError(
            f"the pinned Modern Web Guidance catalog is missing at {directory}: "
            f"{report['reason']}. Materialize the reviewed tree and derive its catalog with "
            f"`modern_web_guidance.py build`, or the GUI specialist cannot consult guidance")
    raise CliError(
        f"the Modern Web Guidance catalog at {directory} is {report['status']}: "
        f"{report['reason']}. Every read refuses to answer from it — re-pin it with a reviewed "
        f"full commit sha instead of guessing or substituting another source")


def index_entries(report: dict) -> dict[str, dict]:
    return {entry["id"]: entry for entry in report["entries"]}


# --------------------------------------------------------------------------- search


def _fields_of(entry: dict) -> dict[str, str]:
    tags = entry.get("tags") or []
    return {
        "id": str(entry.get("id") or ""),
        "tags": " ".join(str(tag) for tag in tags if isinstance(tag, (str, int, float))),
        "title": str(entry.get("title") or ""),
        "summary": str(entry.get("summary") or ""),
        "body": str(entry.get("body") or ""),
    }


def query_terms(query: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", query.lower())


def score_entry(entry: dict, terms: list[str]) -> tuple[int, int]:
    """(matched terms, weighted score) — the strongest deterministic evidence of relevance."""
    lowered = {name: text.lower() for name, text in _fields_of(entry).items()}
    matched = 0
    total = 0
    for term in terms:
        best = 0
        for name, weight in FIELD_WEIGHTS.items():
            if term in lowered[name]:
                best = max(best, weight)
        if best:
            matched += 1
            total += best
    # A guide whose whole identifier IS a query term is the canonical guide for that capability
    # (the discipline/overview guide a specific guide should be paired with), so it outranks a
    # longer identifier that merely mentions the term.
    if lowered["id"] in set(terms):
        total += 4
    return matched, total


def rank_entries(entries: list[dict], terms: list[str], limit: int) -> list[dict]:
    scored = []
    for entry in entries:
        matched, total = score_entry(entry, terms)
        if matched:
            scored.append((matched, total, entry["id"], entry))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    matches = []
    for matched, total, guide_id, entry in scored[:limit]:
        matches.append({
            "id": guide_id,
            "title": str(entry.get("title") or ""),
            "summary": str(entry.get("summary") or ""),
            "stability": _entry_stability(entry),
            "tags": list(entry.get("tags") or []),
            "score": total,
            "matched_terms": matched,
        })
    return matches


def clean_query(raw: str | None) -> str:
    """The search query: ONE to `MAX_QUERY_WORDS` plain words, trimmed, within the char bound.

    The word bound is the documented shape of a search ("one to five plain words"): a run searches
    ONE capability at a time, so a single word is legitimate and a sixth is an input error naming
    the fix instead of a silently widened search.
    """
    if raw is None:
        raise CliError("search needs a --query with one to five plain words", 2)
    trimmed = raw.strip()
    if not trimmed:
        raise CliError("search needs a non-empty --query (whitespace is not a search)", 2)
    if len(trimmed) > MAX_QUERY_CHARS:
        raise CliError(f"the search query is {len(trimmed)} characters; the bound is "
                       f"{MAX_QUERY_CHARS} — search one capability at a time", 2)
    words = trimmed.split()
    if len(words) > MAX_QUERY_WORDS:
        raise CliError(f"the search query has {len(words)} words; the bound is one to five plain "
                       f"words — search one capability at a time", 2)
    return trimmed


# --------------------------------------------------------------------------- .mwgrc consent


def read_consent(repo: pathlib.Path) -> bool:
    """The repository's `.mwgrc` unstable decision: JSON booleans only, absent means false."""
    path = repo / ".mwgrc"
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"the .mwgrc of {repo} cannot be read: {exc}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f".mwgrc is not valid JSON ({exc.msg} at line {exc.lineno}); the unstable "
                       f"decision must be a JSON boolean")
    if not isinstance(data, dict):
        raise CliError(".mwgrc must hold a JSON object whose "
                       f"`{CONSENT_KEY}` is a JSON boolean")
    if CONSENT_KEY not in data:
        return False
    value = data[CONSENT_KEY]
    if not isinstance(value, bool):
        raise CliError(f".mwgrc `{CONSENT_KEY}` must be a JSON boolean (true or false), got "
                       f"{type(value).__name__} {value!r} — only an explicit boolean is consent")
    return value


# --------------------------------------------------------------------------- usage evidence


def current_run_id(repo: pathlib.Path) -> str:
    """The CURRENT run, read from the WIP checkpoint (`run_id:` of `.code-factory/state/pipeline.yaml`).

    Guidance evidence is only proof for the run that recorded it, so this is what the journal and
    every event are bound to. An absent or empty run_id is an unbound journal, never a wildcard.
    """
    path = pathlib.Path(repo).joinpath(".code-factory", "state", "pipeline.yaml")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        match = re.match(r"^run_id:\s*(.*)$", line)
        if match:
            value = match.group(1).strip()
            if value[:1] in {'"', "'"}:
                quote = value[0]
                closing = value.find(quote, 1)
                value = value[1:closing] if closing > 0 else value[1:]
            else:
                value = value.split("#", 1)[0].strip()
            return value
    return ""


def _load_usage(repo: pathlib.Path) -> dict:
    path = usage_path(repo)
    data, problem = _read_json(path)
    if problem or not isinstance(data, dict):
        return {"run_id": "", "events": []}
    events = data.get("events")
    if not isinstance(events, list):
        events = []
    run_id = data.get("run_id")
    return {"run_id": run_id if isinstance(run_id, str) else "",
            "events": [e for e in events if isinstance(e, dict)]}


def _archive_token(run_id: str) -> str:
    """A run_id reduced to a filename-safe token: the id is read from a file, never a path."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id).strip("._-")
    return token[:64] or "unbound"


def _archive_prior_journal(path: pathlib.Path, state: dict) -> None:
    """Move a prior run's journal aside as `usage.<run_id>.json`, keeping it as history.

    Nothing is deleted: a run that already has an archive keeps it, and a run_id seen twice takes
    the next free name. An archive that cannot be written is a warning — the current run still
    records its own evidence — but it is never silent.
    """
    if not state["events"]:
        return
    token = _archive_token(state["run_id"])
    candidate = path.with_name(f"{path.stem}.{token}.json")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.{token}-{counter}.json")
        counter += 1
    try:
        os.replace(path, candidate)
    except OSError as exc:
        print(f"warning: cannot archive the prior guidance journal {path}: {exc}",
              file=sys.stderr)


def record_usage(repo: pathlib.Path, event: dict) -> None:
    """Append one ordered event bound to the current run; a read-only tree warns, never fails.

    One journal holds ONE run's evidence: when the checkpoint's run_id differs from the journal's,
    the prior journal is archived as `usage.<run_id>.json` and an empty current-run journal starts.
    Prior events stay on disk as history but can never mix into the current run, so a sequential
    run proves its own guidance usage instead of failing on its predecessor's events.
    """
    run_id = current_run_id(repo)
    path = usage_path(repo)
    state = _load_usage(repo)
    if state["run_id"] != run_id:
        _archive_prior_journal(path, state)
        state = {"run_id": run_id, "events": []}
    events = state["events"]
    highest = 0
    for existing in events:
        seq = existing.get("seq")
        if isinstance(seq, int) and seq > highest:
            highest = seq
    event = dict(event)
    event["seq"] = highest + 1
    event["run_id"] = run_id
    events.append(event)
    if len(events) > MAX_USAGE_EVENTS:
        events = events[-MAX_USAGE_EVENTS:]
    payload = {"run_id": run_id, "events": events}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        print(f"warning: cannot record guidance usage evidence at {path}: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- legacy patterns


LEGACY_PATTERNS = (
    {
        "name": "center-element",
        "regex": re.compile(r"<\s*center\b", re.IGNORECASE),
        "candidates": ("css-layout", "responsive-design", "css"),
        "keywords": ("layout", "css", "grid", "responsive", "flex"),
    },
    {
        "name": "font-element",
        "regex": re.compile(r"<\s*font\b", re.IGNORECASE),
        "candidates": ("typography", "color", "improve-text-layout-and-legibility"),
        "keywords": ("typography", "font", "text", "color"),
    },
    {
        "name": "marquee-element",
        "regex": re.compile(r"<\s*marquee\b", re.IGNORECASE),
        "candidates": ("motion", "animate-element-entry-exit", "scroll-completion-effects"),
        "keywords": ("animation", "motion", "scroll"),
    },
    {
        "name": "inline-event-handler",
        "regex": re.compile(r"<[a-z][^>]*?\son(?:click|change|input|submit|load|mouseover|keyup|"
                            r"keydown|focus|blur)\s*=", re.IGNORECASE),
        "candidates": ("custom-button-actions", "coordinate-global-events",
                       "declarative-dialog-popover-control"),
        "keywords": ("event", "events", "handler", "javascript"),
    },
    {
        "name": "presentational-layout-attributes",
        "regex": re.compile(r"<[a-z][^>]*?\s(?:align|valign|bgcolor|cellpadding|cellspacing|"
                            r"hspace|vspace)\s*=", re.IGNORECASE),
        "candidates": ("css-layout", "responsive-design", "css"),
        "keywords": ("layout", "css", "responsive"),
    },
    {
        "name": "document-write",
        "regex": re.compile(r"document\s*\.\s*write(?:ln)?\s*\("),
        "candidates": ("out-of-order-html-streaming", "html", "prerendering-custom-elements"),
        "keywords": ("html", "streaming", "parsing", "document"),
    },
    {
        "name": "innerhtml-assignment",
        "regex": re.compile(r"\.\s*innerHTML\s*="),
        "candidates": ("html", "custom-elements", "accessible-web-components"),
        "keywords": ("html", "dom", "custom", "elements"),
    },
    {
        "name": "jquery-ready",
        "regex": re.compile(r"\$\(\s*document\s*\)\s*\.\s*ready\s*\("),
        "candidates": ("js", "coordinate-global-events"),
        "keywords": ("javascript", "events", "dom"),
    },
    {
        "name": "xmlhttprequest",
        "regex": re.compile(r"new\s+XMLHttpRequest\b"),
        "candidates": ("js", "performance", "deprioritize-background-fetches"),
        "keywords": ("fetch", "network", "requests"),
    },
    {
        "name": "legacy-vendor-prefix",
        "regex": re.compile(r"(?:-webkit-|-moz-|-ms-)(?:border-radius|box-shadow|transform|"
                            r"transition|flex)\s*:", re.IGNORECASE),
        "candidates": ("css", "css-layout"),
        "keywords": ("css", "properties", "support"),
    },
)


def resolve_guidance_id(entries: list[dict], pattern: dict) -> str:
    """The catalog guide a finding points at: reviewed candidates, then text, then order."""
    if not entries:
        raise CliError("the pinned catalog holds no entries: a legacy-scan finding has no guidance "
                       "to point at — re-pin a catalog that was not derived empty instead of "
                       "scanning against nothing")
    available = {entry["id"] for entry in entries}
    for candidate in pattern["candidates"]:
        if candidate in available:
            return candidate
    terms = [term.lower() for term in pattern["keywords"]]
    best_id = ""
    best_score = 0
    for entry in sorted(entries, key=lambda item: item["id"]):
        matched, total = score_entry(entry, terms)
        if matched and total > best_score:
            best_id = entry["id"]
            best_score = total
    if best_id:
        return best_id
    return entries[0]["id"]


def resolve_target(repo: pathlib.Path, raw: str) -> pathlib.Path:
    candidate = pathlib.Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = repo / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise CliError(f"the legacy-scan target does not exist: {raw!r}")
    except RuntimeError:
        raise CliError(f"the legacy-scan target cannot be resolved (symlink loop?): {raw!r}")
    if resolved != repo and repo not in resolved.parents:
        raise CliError(f"the legacy-scan target {raw!r} resolves to {resolved}, outside the "
                       f"repository {repo} — scanning is confined to the repository")
    return resolved


def iter_scan_files(target: pathlib.Path, repo: pathlib.Path):
    if target.is_file():
        yield target
        return
    for path in sorted(target.rglob("*")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(repo) if repo in path.parents else path
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        yield path


def scan_file(path: pathlib.Path, repo: pathlib.Path, findings: list[dict],
              patterns: list[dict]) -> dict:
    """Scan one input and REPORT whether it was read: an unreadable input is not coverage.

    Returns `{"ok": bool, "path": <repo-relative>, "reason": <text|None>}`. A file this scan cannot
    read comes back `ok: False` with its reason — the caller must refuse the scan rather than
    count the file as scanned and report a hole as success.
    """
    relative = path.relative_to(repo) if repo in path.parents else path
    display = relative.as_posix()
    if path.suffix.lower() not in SCAN_SUFFIXES:
        return {"ok": True, "path": display, "reason": None, "skipped": True}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "path": display,
                "reason": f"cannot read it ({exc}) — the scan refuses to report coverage it does "
                          f"not have instead of silently skipping the file"}
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS]
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if not pattern["regex"].search(line):
                continue
            findings.append({
                "path": display,
                "line": number,
                "pattern": pattern["name"],
                "guidance_id": pattern["guidance_id"],
                "excerpt": line.strip()[:200],
            })
            if len(findings) >= MAX_FINDINGS:
                return {"ok": True, "path": display, "reason": None, "truncated": True}
    return {"ok": True, "path": display, "reason": None}


# --------------------------------------------------------------------------- command handlers


def emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=True))


def cmd_status(args) -> int:
    repo = resolve_repo(args.repo)
    directory = catalog_argument(args, repo)
    report = inspect_catalog(directory)
    emit({
        "command": "status",
        "status": report["status"],
        "reason": report["reason"],
        "catalog": report["catalog"],
        "source": report["source"],
        "revision": report["revision"],
        "entries": len(report["entries"]) if report["entries"] else 0,
        "canonical_source": CANONICAL_SOURCE,
    })
    return 0


def cmd_search(args) -> int:
    repo = resolve_repo(args.repo)
    directory = catalog_argument(args, repo)
    report = load_fresh_catalog(directory)
    query = clean_query(args.query)
    limit = args.limit
    if limit is None:
        limit = DEFAULT_LIMIT
    if limit < 1 or limit > MAX_LIMIT:
        raise CliError(f"--limit must be between 1 and {MAX_LIMIT}, got {limit}", 2)
    matches = rank_entries(report["entries"], query_terms(query), limit)
    record_usage(repo, {"command": "search", "query": query,
                        "revision": report["revision"],
                        "matches": [match["id"] for match in matches]})
    emit({
        "command": "search",
        "query": query,
        "catalog": report["catalog"],
        "revision": report["revision"],
        "count": len(matches),
        "matches": matches,
    })
    return 0


def cmd_retrieve(args) -> int:
    repo = resolve_repo(args.repo)
    directory = catalog_argument(args, repo)
    report = load_fresh_catalog(directory)
    requested = [value for value in (args.id or [])]
    if not requested:
        raise CliError("retrieve needs at least one --id naming a lowercase guide identifier "
                       "(search the catalog first)", 2)
    for value in requested:
        if not isinstance(value, str) or not ID_RE.match(value):
            raise CliError(f"{value!r} is not a catalog identifier: guides are addressed by a "
                           f"lowercase hyphenated id, never by a path or a title")
    unique: list[str] = []
    for value in requested:
        if value not in unique:
            unique.append(value)
    entries = index_entries(report)
    unknown = [value for value in unique if value not in entries]
    if unknown:
        raise CliError(f"the catalog holds no guide with the id(s) {', '.join(unknown)} — search "
                       f"the pinned catalog for a valid identifier")
    unstable = [value for value in unique if _entry_stability(entries[value]) != STABILITY_STABLE]
    consent = read_consent(repo) if unstable else False
    delivered_entries = []
    for value in unique:
        entry = entries[value]
        fallback = str(entry.get("fallback") or "").strip()
        unstable_entry = _entry_stability(entry) != STABILITY_STABLE
        record = {
            "id": value,
            "title": str(entry.get("title") or ""),
            "summary": str(entry.get("summary") or ""),
            "stability": _entry_stability(entry),
            "tags": list(entry.get("tags") or []),
            "delivered": True,
            "gated": False,
        }
        if unstable_entry:
            if not fallback:
                raise CliError(f"the guide {value!r} is unstable and declares no safe fallback "
                               f"(no fallback section in its pinned text): unstable guidance is "
                               f"delivered only with an explicit .mwgrc opt-in AND a declared "
                               f"fallback, so it is refused")
            record["gated"] = True
            record["delivered"] = bool(consent)
            record["fallback"] = fallback[:MAX_FALLBACK_CHARS]
            if consent:
                record["body"] = str(entry.get("body") or "")
        else:
            record["body"] = str(entry.get("body") or "")
            if fallback:
                record["fallback"] = fallback[:MAX_FALLBACK_CHARS]
        delivered_entries.append(record)
    record_usage(repo, {"command": "retrieve", "ids": unique, "revision": report["revision"],
                        "delivered": [e["id"] for e in delivered_entries if e["delivered"]],
                        "gated": [e["id"] for e in delivered_entries if e["gated"]]})
    emit({
        "command": "retrieve",
        "catalog": report["catalog"],
        "revision": report["revision"],
        "count": len(delivered_entries),
        "entries": delivered_entries,
    })
    return 0


def cmd_legacy_scan(args) -> int:
    repo = resolve_repo(args.repo)
    directory = catalog_argument(args, repo)
    report = load_fresh_catalog(directory)
    target = resolve_target(repo, args.target)
    patterns = []
    for pattern in LEGACY_PATTERNS:
        resolved = dict(pattern)
        resolved["guidance_id"] = resolve_guidance_id(report["entries"], pattern)
        patterns.append(resolved)
    findings: list[dict] = []
    scanned = 0
    truncated = False
    for path in iter_scan_files(target, repo):
        if scanned >= MAX_FILES_SCANNED:
            truncated = True
            break
        scanned += 1
        outcome = scan_file(path, repo, findings, patterns)
        if not outcome.get("ok"):
            raise CliError(f"the legacy-scan input {outcome['path']} could not be read: "
                           f"{outcome['reason']}. The scan reports no result rather than a count "
                           f"that hides an unread file")
        if len(findings) >= MAX_FINDINGS:
            truncated = True
            break
    findings.sort(key=lambda item: (item["path"], item["line"], item["pattern"]))
    relative_target = target.relative_to(repo).as_posix() if repo in target.parents else "."
    record_usage(repo, {"command": "legacy-scan", "target": relative_target,
                        "revision": report["revision"], "findings": len(findings)})
    emit({
        "command": "legacy-scan",
        "catalog": report["catalog"],
        "revision": report["revision"],
        "target": relative_target,
        "scanned_files": scanned,
        "truncated": truncated,
        "count": len(findings),
        "findings": findings,
        "note": ("zero findings means no known obsolete pattern was found, never that the code "
                 "is modern; verify each finding against its guide before modernizing"),
    })
    return 0


def cmd_check_session(args) -> int:
    """The session is valid only when THIS run actually consulted guidance in that order.

    The usage journal IS the deliverable, so the evidence must be bound: the journal and every
    event carry the run that recorded it (the current `run_id` of the WIP checkpoint) and each
    event carries the catalog revision it was recorded against. A missing journal, an empty one, an
    unbound/stale/mixed-run journal, an unrecorded or stale revision and a search nobody followed
    up with a retrieval all fail closed — a run that consulted no guidance must not pass its own
    precondition, and the refusal names the evidence that is missing.
    """
    repo = resolve_repo(args.repo)
    directory = catalog_argument(args, repo)
    run_id = current_run_id(repo)
    path = usage_path(repo)
    journal_exists = path.is_file()
    state = _load_usage(repo)
    journal_run = state["run_id"]
    searches = 0
    retrievals: list[str] = []
    violations: list[str] = []
    events = sorted(state["events"], key=lambda item: item.get("seq") or 0)
    for event in events:
        command = event.get("command")
        if command == "search":
            searches += 1
        elif command == "retrieve":
            ids = [value for value in (event.get("ids") or []) if isinstance(value, str)]
            retrievals.extend(ids)
            if searches == 0:
                violations.extend(ids)
    catalog = inspect_catalog(directory)
    pinned_revision = catalog["revision"] if catalog["status"] == STATUS_FRESH else ""

    reasons: list[str] = []
    if not run_id:
        reasons.append("the WIP checkpoint .code-factory/state/pipeline.yaml carries no run_id: "
                       "guidance evidence cannot be bound to the current run")
    if not journal_exists:
        reasons.append(f"no guidance usage evidence exists at {path}: the run must consult the "
                       f"pinned catalog (search, then retrieve) before touching UI code")
    else:
        if journal_run != run_id:
            if not journal_run:
                reasons.append(f"the usage journal at {path} carries no run_id binding: guidance "
                               f"evidence is only proof for the run that recorded it, never a "
                               f"wildcard for the current run {run_id!r}")
            else:
                reasons.append(f"the usage journal at {path} was recorded by run {journal_run!r}, "
                               f"not the current run {run_id!r} — stale evidence from another run "
                               f"is never current proof")
        unbound = [event for event in events if not event.get("run_id")]
        foreign = sorted({str(event.get("run_id")) for event in events
                          if event.get("run_id") and event.get("run_id") != run_id})
        if unbound:
            reasons.append(f"{len(unbound)} of {len(events)} recorded guidance event(s) carry no "
                           f"run_id binding: every event must be bound to the run that recorded it")
        if foreign:
            if len(foreign) == 1 and not any(event.get("run_id") == run_id for event in events):
                reasons.append(f"every recorded guidance event belongs to another run "
                               f"({foreign[0]!r}), not the current run {run_id!r} — stale evidence")
            else:
                reasons.append(f"the usage journal mixes runs: event(s) recorded by "
                               f"{', '.join(repr(value) for value in foreign)} alongside the "
                               f"current run {run_id!r}, so no single run's evidence is provable")
        unrecorded = [event for event in events if not event.get("revision")]
        if not pinned_revision:
            reasons.append(f"the catalog at {directory} is {catalog['status']}: the recorded "
                           f"guidance revisions cannot be checked against a pin")
        elif unrecorded:
            reasons.append(f"{len(unrecorded)} of {len(events)} recorded guidance event(s) carry "
                           f"no revision: every event must record the catalog revision it was "
                           f"recorded against")
        else:
            stale = sorted({str(event.get("revision")) for event in events
                            if event.get("revision") and event.get("revision") != pinned_revision})
            if stale:
                reasons.append(f"the usage journal was recorded against catalog revision(s) "
                               f"{', '.join(repr(value) for value in stale)}, but the pinned "
                               f"catalog holds {pinned_revision!r} — stale-revision evidence is "
                               f"refused")
        if not events:
            reasons.append(f"the guidance usage evidence at {path} records no event: nothing "
                           f"proves the pinned catalog was consulted")
    if violations:
        reasons.append("guidance was retrieved without a preceding search of the pinned catalog: "
                       + ", ".join(sorted(set(violations))))
    if not retrievals:
        reasons.append("no guide was retrieved from the pinned catalog"
                       + (f" (searches: {searches}, retrievals: 0)" if searches else "")
                       + ": a search must be followed by `retrieve`, otherwise the guidance never "
                         "shaped the change")
    ok = not reasons
    payload = {
        "command": "check-session",
        "catalog": str(directory),
        "usage": str(path),
        "run_id": run_id,
        "revision": pinned_revision or None,
        "ok": ok,
        "searches": searches,
        "events": len(events),
        "retrievals": retrievals,
        "violations": violations,
        "note": ("guidance is consulted before UI code is edited: this run carries a recorded "
                 "search that was followed by a retrieval of the pinned catalog"),
    }
    emit(payload)
    if not ok:
        raise CliError("; ".join(reasons) + " — search, then retrieve, before editing UI code")
    return 0


# --------------------------------------------------------------------------- catalog build


FALLBACK_HEADING = re.compile(r"^(#{1,4})\s*(.*?fallback.*?)\s*$", re.IGNORECASE)
H1 = re.compile(r"^#\s+(.+?)\s*$")
README_LINE = re.compile(
    r"^-\s+\*\*\[(?P<id>[^\]]+)\]\((?P<url>[^)]*/guides/(?P<discipline>[^/)]+)/(?P=id)\.md)\)"
    r"\*\*:\s*(?P<description>.+)$"
)
UNSTABLE_MARKERS = (
    re.compile(r"\borigin\s+trial\b", re.IGNORECASE),
    re.compile(r"\bvolatile\b", re.IGNORECASE),
)


def read_descriptions(readme: pathlib.Path) -> dict[str, str]:
    """The corpus's own one-line summaries: `- **[id](…/guides/<d>/<id>.md)**: <text>`."""
    descriptions: dict[str, str] = {}
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return descriptions
    for line in text.splitlines():
        match = README_LINE.match(line.strip())
        if match:
            descriptions[match.group("id")] = match.group("description").strip()
    return descriptions


def guide_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        match = H1.match(line)
        if match:
            return match.group(1).strip()
    return fallback


def guide_summary(text: str, description: str | None) -> str:
    if description:
        return description
    lines = text.splitlines()
    seen_heading = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if H1.match(stripped):
            seen_heading = True
            continue
        if not seen_heading:
            continue
        if stripped.startswith("#") or stripped.startswith("---"):
            continue
        return stripped[:400]
    return ""


def detect_fallback(text: str) -> str:
    """The guide's own fallback section, bounded: the safe path for a non-ubiquitous feature."""
    lines = text.splitlines()
    for position, line in enumerate(lines):
        match = FALLBACK_HEADING.match(line)
        if not match:
            continue
        level = len(match.group(1))
        collected = [match.group(2)]
        for following in lines[position + 1:]:
            heading = re.match(r"^(#{1,6})\s+(.*)$", following)
            if heading and len(heading.group(1)) <= level:
                break
            collected.append(following)
        body = "\n".join(part.rstrip() for part in collected).strip()
        if body:
            return body[:MAX_FALLBACK_CHARS]
    return ""


def detect_stability(text: str) -> str:
    for marker in UNSTABLE_MARKERS:
        if marker.search(text):
            return STABILITY_UNSTABLE
    return STABILITY_STABLE


def cmd_build(args) -> int:
    repo = resolve_repo(args.repo)
    source_root = pathlib.Path(args.source_root).expanduser()
    if not source_root.is_dir():
        raise CliError(f"--source-root is not a directory: {source_root}")
    guides_root = source_root / "skills" / "modern-web-guidance" / "guides"
    if not guides_root.is_dir():
        raise CliError(f"the materialized tree holds no guides at {guides_root}")
    revision = (args.revision or "").strip()
    if not REVISION_RE.match(revision):
        raise CliError(f"--revision must be a full 40-hex commit sha, got {args.revision!r}")
    source = (args.source or CANONICAL_SOURCE).strip()
    if source != CANONICAL_SOURCE:
        raise CliError(f"--source must be the reviewed {CANONICAL_SOURCE!r}, got {source!r}")
    descriptions = read_descriptions(source_root / "README.md")
    entries: list[dict] = []
    for path in sorted(guides_root.rglob("*.md")):
        guide_id = path.stem
        if not ID_RE.match(guide_id):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise CliError(f"cannot read the guide {path}: {exc}")
        entry = {
            "id": guide_id,
            "discipline": path.parent.name,
            "title": guide_title(text, guide_id),
            "summary": guide_summary(text, descriptions.get(guide_id)),
            "body": text,
            "stability": detect_stability(text),
            "tags": [path.parent.name],
        }
        fallback = detect_fallback(text)
        if fallback:
            entry["fallback"] = fallback
        entries.append(entry)
    entries.sort(key=lambda item: item["id"])
    directory = catalog_argument(args, repo)
    catalog = {"source": source, "revision": revision,
               "generated_by": "modern_web_guidance.py build", "entries": entries}
    pin = {"source": source, "revision": revision}
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / CATALOG_FILENAME).write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (directory / PIN_FILENAME).write_text(
            json.dumps(pin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write the catalog at {directory}: {exc}")
    unstable = [entry["id"] for entry in entries if entry["stability"] == STABILITY_UNSTABLE]
    emit({
        "command": "build",
        "catalog": str(directory),
        "source": source,
        "revision": revision,
        "entries": len(entries),
        "unstable": unstable,
        "with_fallback": sum(1 for entry in entries if entry.get("fallback")),
    })
    return 0


# --------------------------------------------------------------------------- CLI


def resolve_repo(raw: str) -> pathlib.Path:
    candidate = pathlib.Path(raw).expanduser()
    if not candidate.exists():
        raise CliError(f"--repo is not an existing directory: {raw!r}")
    if not candidate.is_dir():
        raise CliError(f"--repo must be a directory, not a file: {raw!r}")
    return candidate.resolve()


def catalog_argument(args, repo: pathlib.Path) -> pathlib.Path:
    raw = getattr(args, "catalog", None)
    if raw:
        return pathlib.Path(raw).expanduser()
    return default_catalog_dir(repo)


def add_common(parser: argparse.ArgumentParser, *, catalog: bool = True) -> None:
    parser.add_argument("--repo", required=True,
                        help="repository root holding the safe reference cache and the .mwgrc")
    if catalog:
        parser.add_argument("--catalog", default=None,
                            help="catalog directory (default: "
                                 "<repo>/.code-factory/cache/reference-docs/modern-web-guidance)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modern_web_guidance.py",
        description="Local, pinned Modern Web Guidance adapter: read the reviewed cached catalog "
                    "as data, never run downloaded code.",
        epilog="Every read refuses to answer from a catalog that is not FRESH against its pin.",
    )
    sub = parser.add_subparsers(dest="command", required=True,
                                metavar="{status,search,retrieve,legacy-scan,check-session,build}")

    status = sub.add_parser("status", help="report whether the pinned catalog is FRESH")
    add_common(status)
    status.set_defaults(handler=cmd_status)

    search = sub.add_parser("search", help="rank catalog guides for bounded query text")
    add_common(search)
    search.add_argument("--query", default=None, help="one to five plain words, max 200 characters")
    search.add_argument("--limit", type=int, default=None,
                        help=f"maximum matches (1..{MAX_LIMIT}, default {DEFAULT_LIMIT})")
    search.set_defaults(handler=cmd_search)

    retrieve = sub.add_parser("retrieve", help="return guide bodies by lowercase identifier")
    add_common(retrieve)
    retrieve.add_argument("--id", dest="id", action="append", default=None,
                          help="catalog guide identifier (repeatable; deduplicated)")
    retrieve.set_defaults(handler=cmd_retrieve)

    legacy = sub.add_parser("legacy-scan",
                            help="report obsolete web-platform patterns in a repository target")
    add_common(legacy)
    legacy.add_argument("--target", required=True,
                        help="file or directory confined to the repository")
    legacy.set_defaults(handler=cmd_legacy_scan)

    session = sub.add_parser("check-session",
                             help="prove every retrieval was preceded by a search")
    add_common(session)
    session.set_defaults(handler=cmd_check_session)

    build = sub.add_parser("build", help="derive catalog.json and pin.json from a pinned tree")
    add_common(build)
    build.add_argument("--source-root", required=True,
                       help="materialized pinned tree (holds skills/modern-web-guidance/guides)")
    build.add_argument("--revision", required=True, help="full 40-hex reviewed commit sha")
    build.add_argument("--source", default=CANONICAL_SOURCE,
                       help="canonical HTTPS Git URL (the reviewed source only)")
    build.set_defaults(handler=cmd_build)
    return parser


def main(argv=None) -> int:
    use_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:  # pragma: no cover - argparse requires a subcommand
        parser.print_help(sys.stderr)
        return 2
    try:
        return handler(args)
    except CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
