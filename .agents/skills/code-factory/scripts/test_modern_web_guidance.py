#!/usr/bin/env python3
"""
Failing-first contract test for `modern_web_guidance.py` (zero LLM tokens, no network, no npm, no
execution of any downloaded code).

THIS FILE IS THE FAILING-FIRST EVIDENCE FOR task_01: the adapter does not exist yet, so the run must
stop at the guarded import with a clear message naming the missing module and the contract it owes.
Once the adapter exists (task_03) this suite is the permanent regression for that contract.

The contract it pins, with synthetic temporary catalogs only:

  * Catalog layout — a catalog directory holds `catalog.json`
    `{"source": <canonical HTTPS Git URL>, "revision": <full 40-hex commit SHA>, "entries": [...]}`
    and its pin `pin.json` `{"source": ..., "revision": ...}`. An entry is
    `{"id", "title", "summary", "body", "stability": "stable"|"unstable", "tags": [...],
    "fallback": <text, optional>}`. The default catalog directory is
    `<repo>/.code-factory/cache/reference-docs/modern-web-guidance` (the safe reference cache) and
    `--catalog <dir>` overrides it.
  * Freshness is deterministic and fail-closed: FRESH only when pin and catalog agree on the
    canonical source AND the exact full commit SHA; a divergent, short, moving or missing revision,
    a foreign source or a missing pin is never FRESH, and every read refuses to answer.
  * `status`, `search`, `retrieve`, `legacy-scan`, `check-session` print JSON on stdout; usage errors
    exit 2, data/catalog/configuration errors exit 1 as `ERROR: ...` with no traceback.
  * Search takes trimmed, non-empty, bounded text with the documented ONE-TO-FIVE-word shape
    (boundaries: one word and five words are accepted, a sixth is an exit-2 input error); retrieve
    takes at least one lowercase catalog identifier (never a path), deduplicated; legacy-scan takes
    a target confined to the repository, where zero findings is SUCCESS.
  * `.mwgrc` unstable decisions are JSON booleans only, absent means false; unstable guidance is
    delivered only with explicit opt-in AND a declared safe fallback.
  * Usage order is recorded in `.code-factory/state/modern-web-guidance/usage.json`; `check-session`
    fails when an id was retrieved without a preceding search — the GUI specialist must search and
    retrieve the pinned catalog BEFORE editing UI code.
  * `check-session` requires the EVIDENCE itself (failing-first, ADV-3): a missing usage file, an
    empty journal and a search never followed by a retrieval all fail (exit 1, `ERROR: ...`), so a
    session that consulted no guidance can never report `ok: true`.
  * Every journal is BOUND to its run and catalog (failing-first, review R1): the journal and each
    event carry the recording run's `run_id` (read from the WIP checkpoint) and each event carries
    the catalog revision, so a missing, stale, mixed-run or stale-revision journal is refused.
  * One journal holds ONE run (failing-first, review R2): a changed `run_id` archives the prior
    run's journal as `usage.<run_id>.json` — history preserved, never deleted — and starts a fresh
    current-run journal, so a sequential run's own search-then-retrieve evidence is never rejected
    because of its predecessor's events.
  * A pinned catalog with ZERO entries and an unreadable scan input are controlled `ERROR:`
    refusals (failing-first, review R1), never an IndexError traceback and never a scan that
    silently discards the file it could not read.
  * The adapter is a local data reader: no subprocess, network module, `npx`, `eval` or `exec`, and
    catalog bodies are returned as inert text even when they contain code.

Exit code 0 = all assertions pass, 1 = the adapter is missing or misbehaved.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "modern_web_guidance.py"
GUI_EXPERT = SCRIPTS.parents[2] / "agents" / "sub-agents" / "gui-expert.md"

CANONICAL_SOURCE = "https://github.com/GoogleChrome/modern-web-guidance.git"
REVISION = "8f2c1d5b6a7e4c3f9d0a1b2c3d4e5f60718293a4"
OTHER_REVISION = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"

sys.path.insert(0, str(SCRIPTS))
try:
    import modern_web_guidance as mwg  # noqa: E402  (the importable API under test)
except Exception as exc:  # the missing adapter is the expected pre-fix state
    mwg = None
    IMPORT_FAILURE = f"{type(exc).__name__}: {exc}"
else:
    IMPORT_FAILURE = ""

COUNTER = {"checks": 0}

PAYLOAD_BODY = (
    "import os\n"
    "os.system('touch pwned-by-guidance')\n"
)

ENTRIES = [
    {
        "id": "dialog-focus-management",
        "title": "Dialog focus management",
        "summary": "Move focus into a modal dialog and restore it on close so a keyboard user is "
                   "never stranded.",
        "tags": ["dialog", "focus", "accessibility", "keyboard"],
        "body": "Use the native <dialog> element and dialog.showModal(); the browser traps focus.",
        "stability": "stable",
    },
    {
        "id": "responsive-form-layout",
        "title": "Responsive form layout",
        "summary": "A single-column form on narrow viewports, two columns above a container query "
                   "breakpoint, with 44px touch targets.",
        "tags": ["form", "layout", "responsive"],
        "body": "Prefer grid with minmax() and container queries over fixed pixel widths.",
        "stability": "stable",
    },
    {
        "id": "scroll-driven-animations",
        "title": "Scroll-driven animations",
        "summary": "Drive an animation from a scroll progress timeline without a scroll listener.",
        "tags": ["animation", "scroll"],
        "body": "animation-timeline: view(); pairs with a transform-only animation.",
        "stability": "unstable",
        "fallback": "Use a CSS transition or an IntersectionObserver-driven class toggle where "
                    "scroll timelines are unsupported.",
    },
    {
        "id": "view-transitions-optin",
        "title": "View transitions",
        "summary": "Animate between two DOM states with document.startViewTransition.",
        "tags": ["animation", "navigation"],
        "body": "document.startViewTransition(() => update());",
        "stability": "unstable",
    },
]

LEGACY_HTML = """\
<!doctype html>
<html>
<body>
  <center><h1>Old landing page</h1></center>
  <font color="red">Sale</font>
  <marquee>scroll</marquee>
  <button onclick="go()">Go</button>
  <p>Modern paragraph with <strong>emphasis</strong> and a <button type="button">button</button>.</p>
</body>
</html>
"""
LEGACY_LINES = {4, 5, 6, 7}
CLEAN_LINE = 8

CLEAN_HTML = """\
<!doctype html>
<html>
<body>
  <main>
    <h1>Products</h1>
    <form><label for="q">Search</label><input id="q" type="search"><button>Search</button></form>
  </main>
</body>
</html>
"""


def check(cond: bool, msg: str) -> None:
    COUNTER["checks"] += 1
    if not cond:
        raise AssertionError(msg)


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", cwd=cwd)


def expect_clean_cli(res: subprocess.CompletedProcess[str], codes: int | set[int],
                     label: str) -> None:
    expected = {codes} if isinstance(codes, int) else codes
    check(res.returncode in expected, f"{label}: expected exit {sorted(expected)}, "
                                      f"got {res.returncode} (stdout={res.stdout!r} "
                                      f"stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: stderr must not carry a traceback: "
                                         f"{res.stderr!r}")


def expect_error(res: subprocess.CompletedProcess[str], codes: int | set[int],
                 label: str) -> None:
    expect_clean_cli(res, codes, label)
    check("ERROR" in res.stderr, f"{label}: a refusal must be reported as ERROR on stderr: "
                                 f"{res.stderr!r}")


def payload(res: subprocess.CompletedProcess[str], label: str) -> dict:
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label}: stdout must be a JSON document ({exc}): "
                             f"{res.stdout!r}")
    check(isinstance(data, dict), f"{label}: stdout must be a JSON object: {res.stdout!r}")
    return data


def new_repo(tmp: pathlib.Path, name: str) -> pathlib.Path:
    repo = tmp / name
    repo.mkdir(parents=True)
    return repo


RUN_ID = "20261122-ef747283"
OTHER_RUN = "20261121-0badbeef"


def bind_run(repo: pathlib.Path, run_id: str = RUN_ID) -> pathlib.Path:
    """The run's WIP checkpoint: the CURRENT run every guidance journal must be bound to."""
    state = repo / ".code-factory" / "state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / "pipeline.yaml"
    path.write_text(f"run_id: {run_id}\nphase: implement\n", encoding="utf-8")
    return path


def usage_journal(repo: pathlib.Path) -> dict:
    path = repo / ".code-factory" / "state" / "modern-web-guidance" / "usage.json"
    return json.loads(path.read_text(encoding="utf-8"))


def write_catalog(directory: pathlib.Path, *, revision: str | None = REVISION,
                  pin: bool = True, pin_revision: str | None = None,
                  source: str = CANONICAL_SOURCE, pin_source: str | None = None,
                  entries: list[dict] | None = None) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    catalog: dict = {"source": source,
                     "entries": json.loads(json.dumps(ENTRIES)) if entries is None else entries}
    if revision is not None:
        catalog["revision"] = revision
    (directory / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    if pin:
        (directory / "pin.json").write_text(json.dumps({
            "source": pin_source if pin_source is not None else source,
            "revision": pin_revision if pin_revision is not None else (revision or ""),
        }, indent=2), encoding="utf-8")
    return directory


def default_catalog_dir(repo: pathlib.Path) -> pathlib.Path:
    return repo / ".code-factory" / "cache" / "reference-docs" / "modern-web-guidance"


def write_mwgrc(repo: pathlib.Path, text: str) -> pathlib.Path:
    path = repo / ".mwgrc"
    path.write_text(text, encoding="utf-8")
    return path


def search(repo: pathlib.Path, catalog: pathlib.Path, query: str, *extra: str):
    return run("search", "--repo", str(repo), "--catalog", str(catalog), "--query", query, *extra)


def retrieve(repo: pathlib.Path, catalog: pathlib.Path, *ids: str):
    args = ["retrieve", "--repo", str(repo), "--catalog", str(catalog)]
    for entry_id in ids:
        args += ["--id", entry_id]
    return run(*args)


def test_missing_adapter() -> None:
    check(mwg is not None,
          "modern_web_guidance.py is missing: the stdlib local adapter over the PINNED cached "
          "Modern Web Guidance catalog must exist at "
          f"{TOOL} and expose status/search/retrieve/legacy-scan/check-session "
          f"(import failed: {IMPORT_FAILURE})")
    check(hasattr(mwg, "main"), "modern_web_guidance.py must expose main(argv=None) -> int")
    check(hasattr(mwg, "CANONICAL_SOURCE"),
          "modern_web_guidance.py must expose CANONICAL_SOURCE (the reviewed HTTPS Git URL)")
    check(getattr(mwg, "CANONICAL_SOURCE", None) == CANONICAL_SOURCE,
          f"CANONICAL_SOURCE must be the reviewed upstream repository, got "
          f"{getattr(mwg, 'CANONICAL_SOURCE', None)!r}")
    check(callable(getattr(mwg, "default_catalog_dir", None)),
          "modern_web_guidance.py must expose default_catalog_dir(repo) -> Path")
    check(mwg.default_catalog_dir(pathlib.Path("/repo")) ==
          pathlib.Path("/repo/.code-factory/cache/reference-docs/modern-web-guidance"),
          "the default catalog directory must be the safe reference cache")


def test_missing_and_unsupported_catalog(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "no-cache")
    absent = repo / "absent"

    res = run("status", "--repo", str(repo), "--catalog", str(absent))
    expect_clean_cli(res, 0, "status without a catalog directory")
    data = payload(res, "status without a catalog directory")
    check(data.get("status") == "MISSING",
          f"an absent catalog must be reported as MISSING, got {data!r}")
    check(data.get("entries") in (0, None), f"a missing catalog holds no entries: {data!r}")

    for label, res in (
        ("search", search(repo, absent, "dialog")),
        ("retrieve", retrieve(repo, absent, "dialog-focus-management")),
        ("legacy-scan", run("legacy-scan", "--repo", str(repo), "--catalog", str(absent),
                            "--target", str(repo))),
    ):
        expect_error(res, 1, f"{label} without a catalog")
        check("catalog" in res.stderr.lower() or "modern web" in res.stderr.lower(),
              f"{label} must name the missing catalog: {res.stderr!r}")

    unpinned = write_catalog(repo / "unpinned", pin=False)
    data = payload(run("status", "--repo", str(repo), "--catalog", str(unpinned)), "status unpinned")
    check(data.get("status") != "FRESH",
          f"a catalog without its pin must never be FRESH: {data!r}")
    expect_error(search(repo, unpinned, "dialog"), 1, "search against an unpinned catalog")

    broken = repo / "broken"
    broken.mkdir()
    (broken / "catalog.json").write_text("{not json", encoding="utf-8")
    (broken / "pin.json").write_text(json.dumps({"source": CANONICAL_SOURCE,
                                                 "revision": REVISION}), encoding="utf-8")
    expect_error(search(repo, broken, "dialog"), 1, "search against a malformed catalog")


def test_freshness(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "freshness")

    fresh = write_catalog(repo / "fresh")
    data = payload(run("status", "--repo", str(repo), "--catalog", str(fresh)), "status fresh")
    check(data.get("status") == "FRESH", f"a pinned, matching catalog must be FRESH: {data!r}")
    check(data.get("revision") == REVISION, f"status must report the pinned revision: {data!r}")
    check(data.get("entries") == len(ENTRIES), f"status must count the entries: {data!r}")
    expect_clean_cli(search(repo, fresh, "dialog"), 0, "search a fresh catalog")

    divergent = write_catalog(repo / "divergent", pin_revision=OTHER_REVISION)
    data = payload(run("status", "--repo", str(repo), "--catalog", str(divergent)), "status diverged")
    check(data.get("status") == "STALE",
          f"a catalog whose pin names another revision must be STALE: {data!r}")
    expect_error(search(repo, divergent, "dialog"), 1, "search a divergent catalog")

    for name, revision in (("moving", "main"), ("short", REVISION[:7]), ("absent", None)):
        directory = write_catalog(repo / f"{name}-rev", revision=revision)
        label = f"status with a {name} revision"
        data = payload(run("status", "--repo", str(repo), "--catalog", str(directory)), label)
        check(data.get("status") == "STALE",
              f"a {name} revision is not a reviewed commit and must be STALE: {data!r}")
        expect_error(search(repo, directory, "dialog"), 1, f"search with a {name} revision")

    foreign = write_catalog(repo / "foreign", source="https://github.com/evil/mwg.git")
    data = payload(run("status", "--repo", str(repo), "--catalog", str(foreign)), "status foreign")
    check(data.get("status") == "STALE",
          f"a catalog from a non-canonical source must be STALE: {data!r}")
    expect_error(search(repo, foreign, "dialog"), 1, "search a foreign catalog")

    pinned = write_catalog(repo / "pin-only-off")
    (pinned / "pin.json").write_text(json.dumps({"source": CANONICAL_SOURCE,
                                                 "revision": OTHER_REVISION}), encoding="utf-8")
    expect_error(search(repo, pinned, "dialog"), 1, "search a stale pin")

    defaulted = new_repo(tmp, "default-catalog")
    write_catalog(default_catalog_dir(defaulted))
    res = run("status", "--repo", str(defaulted))
    expect_clean_cli(res, 0, "status with the default catalog directory")
    check(payload(res, "status default dir").get("status") == "FRESH",
          "the default catalog directory must resolve to the safe reference cache")
    res = run("search", "--repo", str(defaulted), "--query", "dialog")
    expect_clean_cli(res, 0, "search with the default catalog directory")


def test_input_boundaries(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "boundaries")
    catalog = write_catalog(repo / "catalog")

    expect_clean_cli(run("search", "--repo", str(repo / "does-not-exist"),
                         "--catalog", str(catalog), "--query", "dialog"), {1, 2},
                     "search with a non-existent --repo")
    empty = tmp / "empty-file"
    empty.write_text("", encoding="utf-8")
    res = run("search", "--repo", str(empty), "--catalog", str(catalog), "--query", "dialog")
    expect_clean_cli(res, {1, 2}, "search with a --repo that is a file")

    for bad in ("", "   ", "\t\n"):
        expect_clean_cli(search(repo, catalog, bad), {1, 2}, f"search with query {bad!r}")
    expect_error(search(repo, catalog, "   "), {1, 2}, "search with a whitespace query")
    oversized = "a" * 201
    expect_clean_cli(search(repo, catalog, oversized), {1, 2}, "search with an oversized query")
    expect_clean_cli(search(repo, catalog, "x" * 200), 0, "search with a bounded query")
    # The DOCUMENTED query shape is one to five plain words: the boundaries 1 and 5 are legitimate
    # searches of one capability, the sixth word is refused instead of silently widening it.
    expect_clean_cli(search(repo, catalog, "dialog"), 0, "a one-word query")
    expect_clean_cli(search(repo, catalog, "  dialog focus management  "), 0,
                     "a three-word query")
    expect_clean_cli(search(repo, catalog, "one two three four five"), 0, "a five-word query")
    res = search(repo, catalog, "one two three four five six")
    expect_error(res, 2, "a six-word query")
    check("five" in res.stderr and "word" in res.stderr.lower(),
          f"the refusal must name the word bound: {res.stderr!r}")
    expect_error(search(repo, catalog, "dialog focus management modal keyboard trap"),
                 2, "a six-word query of catalog terms")

    expect_error(retrieve(repo, catalog), 2, "retrieve without --id")
    for bad in ("Dialog Focus", "dialog/focus", "../pin", "dialog_focus", "DIALOG-FOCUS"):
        expect_error(retrieve(repo, catalog, bad), 1, f"retrieve with the invalid id {bad!r}")


def test_search(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "search")
    catalog = write_catalog(repo / "catalog")

    res = search(repo, catalog, "  dialog focus  ")
    expect_clean_cli(res, 0, "search")
    data = payload(res, "search")
    check(data.get("query") == "dialog focus",
          f"the query must be reported trimmed: {data.get('query')!r}")
    check(data.get("revision") == REVISION, f"search must name the pinned revision: {data!r}")
    check(isinstance(data.get("matches"), list) and data["matches"],
          f"search must return matches for a catalog term: {data!r}")
    check(data.get("count") == len(data["matches"]), f"count must match the matches: {data!r}")
    first = data["matches"][0]
    check(first.get("id") == "dialog-focus-management",
          f"the strongest match must come first deterministically: {data['matches']!r}")
    for key in ("id", "title", "summary", "stability"):
        check(isinstance(first.get(key), str) and first[key],
              f"a match must carry {key}: {first!r}")

    again = search(repo, catalog, "dialog focus")
    check(again.stdout == res.stdout, "search must be byte-for-byte deterministic for one query")

    limited = payload(search(repo, catalog, "dialog focus", "--limit", "1"), "search --limit 1")
    check(limited.get("count") == 1, f"--limit must bound the matches: {limited!r}")

    empty = search(repo, catalog, "quantum chromodynamics")
    expect_clean_cli(empty, 0, "search without matches")
    check(payload(empty, "search without matches").get("count") == 0,
          "no match is an empty result, not an error")


def test_retrieve(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "retrieve")
    catalog = write_catalog(repo / "catalog", entries=ENTRIES + [{
        "id": "inert-payload",
        "title": "Inert payload",
        "summary": "A guidance body that looks like code.",
        "tags": ["payload"],
        "body": PAYLOAD_BODY,
        "stability": "stable",
    }])

    res = retrieve(repo, catalog, "dialog-focus-management")
    expect_clean_cli(res, 0, "retrieve one id")
    data = payload(res, "retrieve one id")
    check(data.get("revision") == REVISION, f"retrieve must name the pinned revision: {data!r}")
    entries = data.get("entries")
    check(isinstance(entries, list) and len(entries) == 1,
          f"retrieve must return exactly the requested entry: {data!r}")
    entry = entries[0]
    check(entry.get("id") == "dialog-focus-management", f"retrieve must return the id: {entry!r}")
    check(entry.get("body") and "dialog.showModal" in entry["body"],
          f"retrieve must return the guidance body verbatim: {entry!r}")
    check(entry.get("delivered") is True and entry.get("gated") is False,
          f"stable guidance is delivered ungated: {entry!r}")

    res = retrieve(repo, catalog, "responsive-form-layout", "responsive-form-layout",
                   "dialog-focus-management")
    expect_clean_cli(res, 0, "retrieve two ids with a duplicate")
    data = payload(res, "retrieve two ids with a duplicate")
    ids = [e.get("id") for e in data.get("entries", [])]
    check(ids == ["responsive-form-layout", "dialog-focus-management"],
          f"duplicate ids must be deduplicated, first occurrence kept: {ids!r}")

    expect_error(retrieve(repo, catalog, "no-such-guidance"), 1, "retrieve an unknown id")
    expect_error(retrieve(repo, catalog, "dialog-focus-management", "../pin"), 1,
                 "retrieve a path-shaped id alongside a valid one")

    payloadres = retrieve(repo, catalog, "inert-payload")
    expect_clean_cli(payloadres, 0, "retrieve an inert payload body")
    body = payload(payloadres, "retrieve an inert payload body")["entries"][0]["body"]
    check(body == PAYLOAD_BODY,
          f"the body must be returned as text, unchanged and unexecuted: {body!r}")
    check(not (pathlib.Path.cwd() / "pwned-by-guidance").exists()
          and not (repo / "pwned-by-guidance").exists(),
          "retrieving guidance must never execute the body it returns")


def test_unstable_gating(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "gating")
    catalog = write_catalog(repo / "catalog")

    data = payload(retrieve(repo, catalog, "scroll-driven-animations"), "unstable guidance default")
    entry = data["entries"][0]
    check(entry.get("gated") is True, f"unstable guidance must be gated by default: {entry!r}")
    check(entry.get("delivered") is False,
          f"unstable guidance must not be delivered without opt-in: {entry!r}")
    check(entry.get("fallback") and "IntersectionObserver" in entry["fallback"],
          f"gated guidance must carry its safe fallback: {entry!r}")
    check(not entry.get("body"), f"a gated entry must not leak its body: {entry!r}")

    write_mwgrc(repo, json.dumps({"allow_unstable_features": True}))
    data = payload(retrieve(repo, catalog, "scroll-driven-animations"), "unstable guidance opted in")
    entry = data["entries"][0]
    check(entry.get("delivered") is True,
          f"explicit opt-in must deliver unstable guidance: {entry!r}")
    check(entry.get("body") and "--fallback" not in entry["body"],
          f"an opted-in entry must carry its body: {entry!r}")

    data = payload(retrieve(repo, catalog, "dialog-focus-management"), "stable guidance opted in")
    check(data["entries"][0].get("delivered") is True,
          "opt-in must not suppress stable guidance")

    write_mwgrc(repo, json.dumps({"allow_unstable_features": True}))
    expect_error(retrieve(repo, catalog, "view-transitions-optin"), 1,
                 "unstable guidance without a declared fallback")
    check("fallback" in retrieve(repo, catalog, "view-transitions-optin").stderr.lower(),
          "the refusal must name the missing fallback")

    for label, text in (
        ("string", json.dumps({"allow_unstable_features": "true"})),
        ("number", json.dumps({"allow_unstable_features": 1})),
        ("null", json.dumps({"allow_unstable_features": None})),
        ("not-json", "{allow_unstable_features: true"),
        ("not-object", json.dumps([True])),
    ):
        write_mwgrc(repo, text)
        expect_error(retrieve(repo, catalog, "scroll-driven-animations"), 1,
                     f".mwgrc with a {label} unstable decision")
        expect_clean_cli(retrieve(repo, catalog, "dialog-focus-management"), 0,
                         f"stable guidance with a {label} .mwgrc")

    write_mwgrc(repo, json.dumps({"allow_unstable_features": False}))
    data = payload(retrieve(repo, catalog, "scroll-driven-animations"), "explicit opt-out")
    check(data["entries"][0].get("delivered") is False,
          f"an explicit false must keep unstable guidance gated: {data['entries']!r}")


def test_legacy_scan(tmp: pathlib.Path) -> None:
    repo = new_repo(tmp, "legacy")
    catalog = write_catalog(repo / "catalog")
    (repo / "legacy.html").write_text(LEGACY_HTML, encoding="utf-8")
    clean = repo / "assets" / "clean"
    clean.mkdir(parents=True)
    (clean / "clean.html").write_text(CLEAN_HTML, encoding="utf-8")

    res = run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog), "--target", str(repo))
    expect_clean_cli(res, 0, "legacy-scan")
    data = payload(res, "legacy-scan")
    findings = data.get("findings")
    check(isinstance(findings, list) and findings, f"legacy-scan must report findings: {data!r}")
    check(data.get("count") == len(findings), f"count must match the findings: {data!r}")

    reported = {f.get("line") for f in findings if f.get("path") == "legacy.html"}
    missing = LEGACY_LINES - reported
    check(not missing, f"every obsolete construct must be reported (lines {sorted(missing)} "
                       f"missing): {findings!r}")
    check(CLEAN_LINE not in reported,
          f"modern markup must not be reported as legacy: {findings!r}")
    for finding in findings:
        check(isinstance(finding.get("path"), str) and not finding["path"].startswith(("/", "\\"))
              and ":" not in finding["path"],
              f"a finding path must be repo-relative with forward slashes: {finding!r}")
        check(isinstance(finding.get("line"), int) and finding["line"] >= 1,
              f"a finding line must be a positive integer: {finding!r}")
        check(isinstance(finding.get("pattern"), str) and finding["pattern"],
              f"a finding must name its pattern: {finding!r}")
        guidance_id = finding.get("guidance_id")
        check(isinstance(guidance_id, str) and guidance_id,
              f"a finding must reference catalog guidance: {finding!r}")
        expect_clean_cli(retrieve(repo, catalog, guidance_id), 0,
                         f"retrieve the guidance of a finding ({guidance_id})")

    data = payload(run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog),
                       "--target", str(clean)), "legacy-scan a clean target")
    check(data.get("count") == 0 and data.get("findings") == [],
          f"a clean target has zero findings, which is success: {data!r}")

    (repo / "empty").mkdir()
    data = payload(run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog),
                       "--target", str(repo / "empty")), "legacy-scan an empty target")
    check(data.get("count") == 0, f"an empty target has zero findings: {data!r}")

    outside = repo.parent / "outside.html"
    outside.write_text(LEGACY_HTML, encoding="utf-8")
    expect_error(run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog),
                     "--target", str(outside)), 1, "legacy-scan a target outside the repository")
    expect_error(run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog),
                     "--target", "../outside.html"), 1,
                 "legacy-scan a relative target escaping the repository")
    expect_error(run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog),
                     "--target", str(repo / "missing")), 1,
                 "legacy-scan a missing target")

    link = repo / "link.html"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    else:
        expect_error(run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog),
                         "--target", str(link)), 1,
                     "legacy-scan a symlink escaping the repository")


def test_usage_order(tmp: pathlib.Path) -> None:
    searched = new_repo(tmp, "searched-first")
    bind_run(searched)
    catalog_a = write_catalog(searched / "catalog")
    expect_clean_cli(search(searched, catalog_a, "dialog focus"), 0, "search before retrieve")
    expect_clean_cli(retrieve(searched, catalog_a, "dialog-focus-management"), 0,
                     "retrieve after search")
    res = run("check-session", "--repo", str(searched), "--catalog", str(catalog_a))
    expect_clean_cli(res, 0, "check-session after search then retrieve")
    data = payload(res, "check-session after search then retrieve")
    check(data.get("ok") is True, f"a searched-then-retrieved session is valid: {data!r}")
    check(data.get("retrievals"), f"the audit must report what was retrieved: {data!r}")

    usage = searched / ".code-factory" / "state" / "modern-web-guidance" / "usage.json"
    check(usage.is_file(), f"the adapter must record its usage evidence at {usage}")
    recorded = json.loads(usage.read_text(encoding="utf-8"))
    check(isinstance(recorded, dict) and recorded.get("run_id") == RUN_ID,
          f"usage evidence must be bound to the run that recorded it: {recorded!r}")

    direct = new_repo(tmp, "retrieved-first")
    bind_run(direct)
    catalog_b = write_catalog(direct / "catalog")
    expect_clean_cli(retrieve(direct, catalog_b, "dialog-focus-management"), 0,
                     "retrieve without a preceding search")
    res = run("check-session", "--repo", str(direct), "--catalog", str(catalog_b))
    expect_error(res, 1, "check-session after retrieve without search")
    check("dialog-focus-management" in res.stderr,
          f"the violation must name the id: {res.stderr!r}")


def test_check_session_requires_evidence(tmp: pathlib.Path) -> None:
    """(failing-first, ADV-3) A session that consulted no guidance is not a valid session.

    `check-session` only looked for retrievals without a preceding search, so with NO usage file it
    answered `ok: true, searches: 0, events: 0` and exited 0 — a run that never consulted the
    pinned catalog passed its own precondition. The usage evidence IS the deliverable: a missing
    usage file, an empty journal and a search never followed by a retrieval all fail (exit 1,
    `ERROR: ...` naming what is missing), while search-then-retrieve stays green.
    """
    missing = new_repo(tmp, "usage-missing")
    bind_run(missing)
    catalog_a = write_catalog(missing / "catalog")
    res = run("check-session", "--repo", str(missing), "--catalog", str(catalog_a))
    expect_error(res, 1, "check-session with no usage file at all")
    data = payload(res, "check-session with no usage file at all")
    check(data.get("ok") is False, f"no usage evidence is never ok: {data!r}")
    check(data.get("events") == 0, f"the audit must report that nothing was recorded: {data!r}")
    check("usage" in res.stderr.lower(),
          f"the refusal must name the missing usage evidence: {res.stderr!r}")

    empty = new_repo(tmp, "usage-empty")
    bind_run(empty)
    catalog_b = write_catalog(empty / "catalog")
    usage = empty / ".code-factory" / "state" / "modern-web-guidance" / "usage.json"
    usage.parent.mkdir(parents=True, exist_ok=True)
    usage.write_text(json.dumps({"run_id": "", "events": []}), encoding="utf-8")
    res = run("check-session", "--repo", str(empty), "--catalog", str(catalog_b))
    expect_error(res, 1, "check-session over an empty usage journal")
    data = payload(res, "check-session over an empty usage journal")
    check(data.get("ok") is False and data.get("searches") == 0,
          f"an empty journal proves nothing was consulted: {data!r}")

    partial = new_repo(tmp, "usage-partial")
    bind_run(partial)
    catalog_c = write_catalog(partial / "catalog")
    expect_clean_cli(search(partial, catalog_c, "dialog focus"), 0, "a search with no retrieval")
    res = run("check-session", "--repo", str(partial), "--catalog", str(catalog_c))
    expect_error(res, 1, "check-session after a search with no retrieval")
    data = payload(res, "check-session after a search with no retrieval")
    check(data.get("ok") is False and data.get("searches") == 1
          and data.get("retrievals") == [],
          f"a search nobody followed up proves no guidance was used: {data!r}")
    check("retrieve" in res.stderr.lower(),
          f"the refusal must name the missing retrieval: {res.stderr!r}")

    # The positive control: search then retrieve is the evidence the audit accepts.
    good = new_repo(tmp, "usage-good")
    bind_run(good)
    catalog_d = write_catalog(good / "catalog")
    expect_clean_cli(search(good, catalog_d, "dialog focus"), 0, "search before retrieve")
    expect_clean_cli(retrieve(good, catalog_d, "dialog-focus-management"), 0,
                     "retrieve after search")
    res = run("check-session", "--repo", str(good), "--catalog", str(catalog_d))
    expect_clean_cli(res, 0, "check-session after search then retrieve")
    data = payload(res, "check-session after search then retrieve")
    check(data.get("ok") is True and data.get("searches") == 1,
          f"a searched-then-retrieved session is valid: {data!r}")
    check(data.get("retrievals") == ["dialog-focus-management"],
          f"the audit must report what was retrieved: {data!r}")


def test_usage_binding(tmp: pathlib.Path) -> None:
    """(review R1, major) Guidance usage is bound to the CURRENT run and catalog revision.

    The journal was written with `run_id: ""`, so a journal from another run (or one a previous run
    left behind) counted as this run's evidence, and `check-session` only counted events. Evidence
    must be bound: the journal — and every event in it — carries the run that recorded it, and each
    event carries the catalog revision it was recorded against. A missing, stale, mixed-run or
    stale-revision journal is refused (exit 1, `ERROR: ...`), never accepted as current proof.
    """
    bound = new_repo(tmp, "usage-binding")
    bind_run(bound)
    catalog = write_catalog(bound / "catalog")
    expect_clean_cli(search(bound, catalog, "dialog focus"), 0, "search")
    expect_clean_cli(retrieve(bound, catalog, "dialog-focus-management"), 0, "retrieve")
    journal = usage_journal(bound)
    check(journal.get("run_id") == RUN_ID,
          f"the usage journal must be bound to the run that recorded it: {journal!r}")
    events = journal.get("events") or []
    check(len(events) >= 2 and all(event.get("run_id") == RUN_ID for event in events),
          f"every event must carry the run that recorded it: {journal!r}")
    check(all(event.get("revision") == REVISION for event in events),
          f"every event must carry the catalog revision it was recorded against: {journal!r}")
    res = run("check-session", "--repo", str(bound), "--catalog", str(catalog))
    expect_clean_cli(res, 0, "check-session over a run-bound journal")

    def journal_case(name: str, mutate) -> pathlib.Path:
        repo = new_repo(tmp, name)
        bind_run(repo)
        write_catalog(repo / "catalog")
        payload_json = json.loads(json.dumps(journal))
        mutate(payload_json)
        path = repo / ".code-factory" / "state" / "modern-web-guidance" / "usage.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload_json, indent=2), encoding="utf-8")
        return repo

    def unbound(payload_json: dict) -> None:
        payload_json["run_id"] = ""
        for event in payload_json["events"]:
            event.pop("run_id", None)

    def stale(payload_json: dict) -> None:
        payload_json["run_id"] = OTHER_RUN
        for event in payload_json["events"]:
            event["run_id"] = OTHER_RUN

    def mixed(payload_json: dict) -> None:
        payload_json["events"][-1]["run_id"] = OTHER_RUN

    def stale_revision(payload_json: dict) -> None:
        for event in payload_json["events"]:
            event["revision"] = OTHER_REVISION

    def unrecorded_revision(payload_json: dict) -> None:
        payload_json["events"][-1].pop("revision", None)

    for name, mutate, needle in (
            ("usage-unbound", unbound, ("run", "binding", "run_id")),
            ("usage-stale-run", stale, ("stale", "current run", "another run", "run_id")),
            ("usage-mixed-run", mixed, ("mixed", "run", "binding")),
            ("usage-stale-revision", stale_revision,
             ("revision", "stale", "catalog", "pin")),
            ("usage-unrecorded-revision", unrecorded_revision,
             ("revision", "catalog", "recorded")),
    ):
        repo = journal_case(name, mutate)
        res = run("check-session", "--repo", str(repo), "--catalog", str(repo / "catalog"))
        expect_error(res, 1, f"check-session over a {name} journal")
        lowered = res.stderr.lower()
        check(any(word in lowered for word in needle),
              f"the {name} refusal must name what is not bound: {res.stderr!r}")


def test_sequential_runs(tmp: pathlib.Path) -> None:
    """(review R2, major) A second run starts a FRESH journal; the first run never poisons it.

    `record_usage` appended the new run's event to the events left by the run before it and wrote
    them ALL under the new run_id, so `check-session` of a sequential run refused its own journal as
    "mixing runs" even though that run really had searched and retrieved. One journal holds ONE
    run's evidence: on a run-id change the prior journal is archived as `usage.<run_id>.json`
    (history preserved on disk, never deleted) and the current run starts empty, so prior events
    can never poison the current run's proof.
    """
    repo = new_repo(tmp, "sequential-runs")
    bind_run(repo, RUN_ID)
    catalog = write_catalog(repo / "catalog")
    expect_clean_cli(search(repo, catalog, "dialog focus"), 0, "first run: search")
    expect_clean_cli(retrieve(repo, catalog, "dialog-focus-management"), 0, "first run: retrieve")
    expect_clean_cli(run("check-session", "--repo", str(repo), "--catalog", str(catalog)), 0,
                     "first run: check-session")
    first = usage_journal(repo)
    check(first.get("run_id") == RUN_ID,
          f"the first run's journal must be bound to it: {first!r}")

    bind_run(repo, OTHER_RUN)
    expect_clean_cli(search(repo, catalog, "dialog focus"), 0, "second run: search")
    expect_clean_cli(retrieve(repo, catalog, "dialog-focus-management"), 0, "second run: retrieve")

    journal = usage_journal(repo)
    check(journal.get("run_id") == OTHER_RUN,
          f"a changed run_id must start a journal bound to the new run: {journal!r}")
    events = journal.get("events") or []
    check(events and all(event.get("run_id") == OTHER_RUN for event in events),
          f"the current journal must hold ONLY the current run's events: {journal!r}")
    check([event.get("command") for event in events] == ["search", "retrieve"],
          f"the current journal must carry this run's ordered evidence: {journal!r}")

    state_dir = repo / ".code-factory" / "state" / "modern-web-guidance"
    archives = sorted(state_dir.glob("usage.*.json"))
    check(len(archives) == 1,
          f"the prior run's journal must be preserved as history, got {archives!r}")
    archived = json.loads(archives[0].read_text(encoding="utf-8"))
    check(archived.get("run_id") == RUN_ID and len(archived.get("events") or []) == 2,
          f"the archived journal must keep the prior run's evidence intact: {archived!r}")
    check(RUN_ID in archives[0].name,
          f"the archive must name the run that recorded it: {archives[0].name!r}")

    res = run("check-session", "--repo", str(repo), "--catalog", str(catalog))
    expect_clean_cli(res, 0, "second run: check-session")
    data = payload(res, "second run: check-session")
    check(data.get("ok") is True and data.get("run_id") == OTHER_RUN,
          f"a sequential run proves its own guidance usage: {data!r}")
    check(data.get("events") == 2,
          f"prior-run events must not be counted as current evidence: {data!r}")
    check(data.get("retrievals") == ["dialog-focus-management"],
          f"the audit must report only the current run's retrieval: {data!r}")

    # A run_id seen twice (A → B → A → B) keeps every archive: history is never overwritten, so a
    # collision takes the next free name instead of replacing the earlier evidence.
    bind_run(repo, RUN_ID)
    expect_clean_cli(search(repo, catalog, "dialog focus"), 0, "third run: search")
    expect_clean_cli(retrieve(repo, catalog, "dialog-focus-management"), 0, "third run: retrieve")
    expect_clean_cli(run("check-session", "--repo", str(repo), "--catalog", str(catalog)), 0,
                     "third run: check-session")
    bind_run(repo, OTHER_RUN)
    expect_clean_cli(search(repo, catalog, "dialog focus"), 0, "fourth run: search")
    archived_runs = sorted(path.name for path in state_dir.glob("usage.*.json"))
    check(len(archived_runs) == 3,
          f"every distinct prior journal must stay archived: {archived_runs!r}")
    repeated = [name for name in archived_runs if RUN_ID in name]
    check(len(repeated) == 2 and repeated[0] != repeated[1],
          f"a repeated run_id must not overwrite its earlier archive: {archived_runs!r}")
    kept = json.loads((state_dir / repeated[0]).read_text(encoding="utf-8"))
    check(len(kept.get("events") or []) == 2,
          f"the earlier archive must keep its evidence intact: {kept!r}")

    # The run_id is read from a file and now names a file too, so it is used only as a SANITIZED
    # token: a traversal attempt stays inside the state directory instead of escaping it.
    hostile = new_repo(tmp, "sequential-runs-hostile")
    bind_run(hostile, RUN_ID)
    hostile_catalog = write_catalog(hostile / "catalog")
    expect_clean_cli(search(hostile, hostile_catalog, "dialog focus"), 0, "hostile: first search")
    bind_run(hostile, "../../escaped-run")
    expect_clean_cli(search(hostile, hostile_catalog, "dialog focus"), 0, "hostile: second search")
    escaped = sorted(str(path) for path in tmp.rglob("escaped-run*"))
    check(not escaped, f"a run_id must never name a path outside the state directory: {escaped!r}")
    hostile_state = hostile / ".code-factory" / "state" / "modern-web-guidance"
    hostile_names = sorted(path.name for path in hostile_state.iterdir())
    check(hostile_names and all(name == "usage.json" or name.startswith("usage.")
                                for name in hostile_names),
          f"the archive must stay inside the state directory: {hostile_names!r}")


def test_legacy_scan_degenerate_inputs(tmp: pathlib.Path) -> None:
    """(review R1, major) An empty catalog and an unreadable file are CONTROLLED failures.

    `resolve_guidance_id` ended with `entries[0]["id"]`, so a pinned catalog with zero entries
    crashed `legacy-scan` with an IndexError traceback instead of a refusal, and `scan_file` threw
    away the OSError while its caller counted the file as scanned — a silent hole in the scan's own
    coverage. Both are explicit `ERROR:` refusals (exit 1, no traceback), never a crash and never a
    result that claims to have scanned what it could not read.
    """
    repo = new_repo(tmp, "legacy-empty-catalog")
    catalog = write_catalog(repo / "catalog", entries=[])
    (repo / "legacy.html").write_text(LEGACY_HTML, encoding="utf-8")
    data = payload(run("status", "--repo", str(repo), "--catalog", str(catalog)), "empty catalog")
    check(data.get("status") == "FRESH" and data.get("entries") == 0,
          f"a pinned catalog with zero entries is still FRESH: {data!r}")
    res = run("legacy-scan", "--repo", str(repo), "--catalog", str(catalog), "--target", str(repo))
    expect_error(res, 1, "legacy-scan against an empty catalog")
    lowered = res.stderr.lower()
    check("catalog" in lowered and any(word in lowered for word in ("empty", "no entr", "zero")),
          f"the refusal must name the empty catalog: {res.stderr!r}")
    try:
        mwg.resolve_guidance_id([], mwg.LEGACY_PATTERNS[0])
    except mwg.CliError:
        pass
    except Exception as exc:  # noqa: BLE001  (any other type is the crash this pins)
        raise AssertionError(f"an empty catalog must be a CliError, not {type(exc).__name__}: "
                             f"{exc}")
    else:
        raise AssertionError("an empty catalog must be refused, never given a fallback id")

    # An unreadable input is reported by `scan_file` itself: it must never return as if the file
    # had been read (a directory named like a scannable file raises OSError on every platform).
    blocked = repo / "blocked.html"
    blocked.mkdir()
    patterns = [dict(pattern, guidance_id="dialog-focus-management")
                for pattern in mwg.LEGACY_PATTERNS]
    findings: list[dict] = []
    outcome: object = None  # bound before the try: the message below is built in both branches
    try:
        outcome = mwg.scan_file(blocked, repo, findings, patterns)
    except mwg.CliError:
        reported = True
    else:
        reported = outcome is False or (isinstance(outcome, dict) and outcome.get("ok") is False)
    check(reported,
          "scan_file must report an input it cannot read instead of silently discarding the "
          f"OSError while the caller counts it as scanned (returned {outcome!r})")


def test_no_downloaded_code_execution() -> None:
    check(TOOL.is_file(), f"the adapter must exist at {TOOL}")
    source = TOOL.read_text(encoding="utf-8")
    forbidden = ("import subprocess", "from subprocess", "subprocess.",
                 "import urllib", "from urllib", "import socket",
                 "import http.client", "requests.", "os.system", "os.popen",
                 "eval(", "exec(", "npx", "npm ")
    for token in forbidden:
        check(token not in source,
              f"the adapter is a local data reader: it must never reference {token!r}")


def test_gui_workflow_contract() -> None:
    check(GUI_EXPERT.is_file(), f"the GUI specialist brief must exist at {GUI_EXPERT}")
    text = GUI_EXPERT.read_text(encoding="utf-8")
    lowered = text.lower()

    for command in ("modern_web_guidance.py status", "modern_web_guidance.py search",
                    "modern_web_guidance.py retrieve", "modern_web_guidance.py legacy-scan"):
        check(command in text,
              f"the GUI specialist must be told to run `{command}`: the pinned catalog workflow is "
              "the precondition for UI edits")
    check("pinned" in lowered and "cache" in lowered,
          "the brief must name the PINNED CACHED catalog as the only guidance source")
    check("npx @latest" in text,
          "the brief must forbid the implicit `npx @latest` shortcut by name")
    check(".mwgrc" in text, "the brief must name the .mwgrc unstable decision")
    check("fallback" in lowered, "the brief must require a safe fallback for unstable guidance")
    check("before" in lowered and ("edit" in lowered or "ui code" in lowered),
          "the brief must state that search/retrieve happen BEFORE UI code edits")
    check("legacy" in lowered,
          "the brief must require reviewing legacy patterns with legacy-scan")
    check("accessib" in lowered and "performance" in lowered,
          "the brief must keep its accessibility and performance obligations")
    check("never execut" in lowered or "not execut" in lowered or "downloaded" in lowered,
          "the brief must keep the rule that downloaded repository code is never executed")


def test_cli_contract() -> None:
    res = run("--help")
    expect_clean_cli(res, 0, "--help")
    for name in ("status", "search", "retrieve", "legacy-scan", "check-session"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help"), 0, f"{name} --help")

    expect_clean_cli(run("search"), 2, "search without --repo")
    expect_clean_cli(run("retrieve"), 2, "retrieve without --repo")
    expect_clean_cli(run("legacy-scan"), 2, "legacy-scan without --repo")
    expect_clean_cli(run("status"), 2, "status without --repo")

    legacy = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True,
                            errors="replace", env={"PYTHONIOENCODING": "cp1251",
                                                   "PATH": "/usr/bin:/bin"})
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy console code page: {legacy.stderr!r}")


def main() -> int:
    test_missing_adapter()
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        test_missing_and_unsupported_catalog(tmp)
        test_freshness(tmp)
        test_input_boundaries(tmp)
        test_search(tmp)
        test_retrieve(tmp)
        test_unstable_gating(tmp)
        test_legacy_scan(tmp)
        test_usage_order(tmp)
    with tempfile.TemporaryDirectory() as td:
        test_check_session_requires_evidence(pathlib.Path(td))
    with tempfile.TemporaryDirectory() as td:
        test_usage_binding(pathlib.Path(td))
    with tempfile.TemporaryDirectory() as td:
        test_sequential_runs(pathlib.Path(td))
    with tempfile.TemporaryDirectory() as td:
        test_legacy_scan_degenerate_inputs(pathlib.Path(td))
    test_no_downloaded_code_execution()
    test_gui_workflow_contract()
    test_cli_contract()

    print(f"PASS - modern_web_guidance.py contract holds: {COUNTER['checks']} assertions over the "
          "pinned cached catalog (freshness and fail-closed refusals), bounded search and "
          "ID-confined deduplicated retrieval, gated unstable guidance with mandatory fallbacks, "
          "repository-confined legacy scanning where zero findings is success and an empty or "
          "unreadable input is a controlled refusal, run- and revision-bound usage evidence with "
          "search-before-retrieve ordering and sequential-run journal isolation, no downloaded-code "
          "execution, the GUI pre-edit workflow and the argparse CLI contract.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL - {exc}", file=sys.stderr)
        sys.exit(1)
