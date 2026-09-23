#!/usr/bin/env python3
"""
Evidence ledger with FRESH/STALE signatures for the Code Factory (anti-hallucination gate).

Test and review results are evidence only for the working tree they were produced from. Every
evidence entry therefore carries a SHA-256 fingerprint of the files it depends on; `check`
recomputes that fingerprint and marks the entry FRESH (unchanged) or STALE (the signed files
changed afterwards). The reviewer and the acceptance gate accept evidence only while it is
FRESH — a green test log from an older revision is not proof about the current code.

Fingerprint: SHA-256 over one line per file, `<relative path>:<content sha256>`, sorted by path
and de-duplicated, so neither the order of `--files` nor the platform separator matters. A
missing file contributes `<relative path>:missing` and an unreadable one `:unreadable`, so a
deletion counts as a change instead of an error. The timestamp is the only non-deterministic
field of an entry and is NOT part of the fingerprint.

Ledger JSON (created on demand by `stamp`, written atomically: same-directory temp file +
os.replace, so a crash can never leave a half-written ledger):
  {"version": 1,
   "entries": [{"name": "regression", "result": "pass", "fingerprint": "<64 hex>",
                "timestamp": "2026-09-24T10:00:00+00:00", "log": "<path or null>",
                "run_id": "20260922-442cd2f8"}]}
Re-stamping a name refreshes that entry, so one evidence name has exactly one current entry.
`run_id` (see `run_id.py`) attributes an entry to the run that produced it; it is written from
`--run-id` and defaults to "", so entries written before the field existed still load unchanged.

Usage:
  python evidence_ledger.py sign  --files src/a.py src/b.py [--repo .] [--run-id <id>]
  python evidence_ledger.py stamp --ledger .code-factory/state/evidence.json --name regression \\
         --result pass --files src/a.py [--log .code-factory/logs/regression.log] [--repo .] \\
         [--run-id <id>]
  python evidence_ledger.py check --ledger .code-factory/state/evidence.json --files src/a.py

`sign` prints the fingerprint. `check` prints one FRESH/STALE row per entry and exits 0 only
when every entry is FRESH and every result is `pass`; anything else (STALE evidence, a failed
result, an empty ledger, an unreadable ledger) is exit 1. stdlib only, Windows/POSIX.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

LEDGER_VERSION = 1
RESULTS = ("pass", "fail")
FRESH = "FRESH"
STALE = "STALE"
MISSING = "missing"
UNREADABLE = "unreadable"
# Evidence name the acceptance gate requires to be FRESH and passing (see acceptance_blocker).
REQUIRED_EVIDENCE = "regression"


def _abs(path, root: pathlib.Path) -> pathlib.Path:
    """Resolve `path` against `root` when it is relative (the ledger's file scope is --repo)."""
    p = pathlib.Path(path)
    return p if p.is_absolute() else root / p


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    """POSIX relative path where possible; an outside-root path keeps its own spelling."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def sha256_file(path: pathlib.Path) -> str:
    """Streamed SHA-256 of a file, so a large file never lands in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_digest(path: pathlib.Path, root: pathlib.Path) -> str:
    """Content digest of one signed file, or a `missing`/`unreadable` marker (never raises)."""
    target = _abs(path, root)
    if not target.is_file():
        return MISSING
    try:
        return sha256_file(target)
    except OSError:
        return UNREADABLE


def fingerprint_files(files, root) -> str:
    """SHA-256 over (relative path + content) of `files`, sorted and de-duplicated.

    Order-independent and deterministic: the same working tree always yields the same value,
    while any content change of a signed file shifts it.
    """
    root = pathlib.Path(root)
    records = {}
    for item in files:
        target = _abs(item, root)
        records[_relative(target, root)] = f"{_relative(target, root)}:{file_digest(target, root)}"
    return hashlib.sha256("\n".join(sorted(records.values())).encode("utf-8")).hexdigest()


def load_ledger(path) -> list[dict]:
    """Read the ledger entries; raise ValueError with a human-readable cause.

    A missing or empty ledger is an empty entry list (the first `stamp` creates the file), a
    broken one is an error — never silently treated as "no evidence" that could be overwritten.
    """
    ledger = pathlib.Path(path)
    if not ledger.exists():
        return []
    try:
        raw = ledger.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read ledger {ledger}: {exc}") from exc
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ledger {ledger} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ValueError(f"ledger {ledger} must be a JSON object with an 'entries' array")
    entries: list[dict] = []
    for idx, item in enumerate(data["entries"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"ledger entry #{idx} must be a JSON object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"ledger entry #{idx} needs a non-empty 'name' string")
        fingerprint = item.get("fingerprint", "")
        if not isinstance(fingerprint, str):
            raise ValueError(f"ledger entry #{idx} ({name}): 'fingerprint' must be a string")
        entries.append({"name": name.strip(),
                        "result": str(item.get("result", "")).strip().lower(),
                        "fingerprint": fingerprint.strip().lower(),
                        "timestamp": str(item.get("timestamp", "")),
                        "log": item.get("log"),
                        # `run_id` was added later: an older entry simply has no run and loads as "".
                        "run_id": str(item.get("run_id") or "").strip()})
    return entries


def save_ledger(path, entries: list[dict]) -> None:
    """Write the ledger atomically (same-dir temp file + os.replace); leaves no temp on failure."""
    ledger = pathlib.Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"version": LEDGER_VERSION, "entries": entries},
                      indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(ledger.parent), prefix=ledger.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, ledger)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def evaluate(entries: list[dict], files, root) -> dict:
    """Recompute the scope fingerprint and mark every entry FRESH/STALE.

    Returns {"fingerprint", "ok", "reason", "rows", "stale", "fresh"}; `ok` follows the CLI rule
    (all entries FRESH and all results `pass`), while the stricter acceptance rule lives in
    `acceptance_blocker`.
    """
    current = fingerprint_files(files, root)
    rows = [{**entry, "status": FRESH if entry.get("fingerprint") == current else STALE}
            for entry in entries]
    stale = [r["name"] for r in rows if r["status"] == STALE]
    fresh = [r["name"] for r in rows if r["status"] == FRESH]
    failed = [r["name"] for r in rows if r["result"] != "pass"]
    if not rows:
        reason = "the evidence ledger has no entries: nothing was signed for this working tree"
    elif stale and failed:
        reason = (f"evidence is STALE: {', '.join(stale)}; and not pass: {', '.join(failed)}")
    elif stale:
        reason = (f"evidence is STALE, the signed files changed after it was recorded: "
                  f"{', '.join(stale)}")
    elif failed:
        reason = f"evidence result is not pass: {', '.join(failed)}"
    else:
        reason = f"all {len(rows)} evidence entries are FRESH and passed"
    return {"fingerprint": current, "ok": bool(rows) and not stale and not failed,
            "reason": reason, "rows": rows, "stale": stale, "fresh": fresh}


def acceptance_blocker(rows: list[dict]) -> str:
    """Reason the acceptance gate must reject this ledger, or "" when it may trust it.

    Stricter than the `check` exit rule on purpose: acceptance additionally requires a FRESH
    `regression=pass` entry, because a SUCCESS verdict without fresh regression evidence is
    exactly the tautology this gate exists to close.
    """
    if not rows:
        return (f"the evidence ledger has no entries: no FRESH {REQUIRED_EVIDENCE}=pass evidence")
    stale = [r["name"] for r in rows if r["status"] == STALE]
    if stale:
        return (f"STALE evidence, the working tree changed after it was signed: "
                f"{', '.join(stale)}")
    failed = [r["name"] for r in rows if r["result"] != "pass"]
    if failed:
        return f"evidence result is not pass: {', '.join(failed)}"
    if not any(r["name"] == REQUIRED_EVIDENCE and r["status"] == FRESH for r in rows):
        return f"no FRESH {REQUIRED_EVIDENCE}=pass evidence in the ledger"
    return ""


def cmd_sign(args: argparse.Namespace) -> int:
    print(fingerprint_files(args.files, pathlib.Path(args.repo)))
    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    ledger = pathlib.Path(args.ledger)
    try:
        entries = load_ledger(ledger)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    entry = {"name": args.name,
             "result": args.result,
             "fingerprint": fingerprint_files(args.files, pathlib.Path(args.repo)),
             "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "log": args.log or None,
             "run_id": args.run_id or ""}
    entries = [e for e in entries if e["name"] != entry["name"]] + [entry]
    try:
        save_ledger(ledger, entries)
    except OSError as exc:
        print(f"error: cannot write ledger {ledger}: {exc}", file=sys.stderr)
        return 1
    print(f"evidence_ledger: stamped name={entry['name']} result={entry['result']} "
          f"fingerprint={entry['fingerprint']} entries={len(entries)} ledger={ledger}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    ledger = pathlib.Path(args.ledger)
    try:
        entries = load_ledger(ledger)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = evaluate(entries, args.files, pathlib.Path(args.repo))
    print(f"{'NAME':<24} {'RESULT':<7} {'FRESHNESS':<10} FINGERPRINT")
    for row in report["rows"]:
        print(f"{row['name']:<24} {row['result']:<7} {row['status']:<10} "
              f"{(row['fingerprint'][:12] or 'n/a')}")
    print(f"evidence_ledger: {len(report['rows'])} entries, FRESH={len(report['fresh'])} "
          f"STALE={len(report['stale'])}; scope fingerprint={report['fingerprint']}")
    print(f"evidence_ledger: {report['reason']}")
    return 0 if report["ok"] else 1


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
    sub = ap.add_subparsers(dest="command", required=True)

    def add_common(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--files", nargs="*", default=[],
                            help="Files the evidence depends on (relative to --repo)")
        parser.add_argument("--repo", default=".",
                            help="Directory the file paths are relative to (default: cwd)")
        parser.add_argument("--run-id", default="",
                            help="Run id (see run_id.py); recorded in the entry by `stamp`")

    sign = sub.add_parser("sign", help="Print the SHA-256 fingerprint of --files")
    add_common(sign)
    sign.set_defaults(func=cmd_sign)

    stamp = sub.add_parser("stamp", help="Append/refresh one evidence entry in the ledger")
    add_common(stamp)
    stamp.add_argument("--ledger", required=True, help="Ledger JSON path (created on demand)")
    stamp.add_argument("--name", required=True, help="Evidence name, e.g. regression")
    stamp.add_argument("--result", required=True, choices=RESULTS, help="Observed outcome")
    stamp.add_argument("--log", default="", help="Path of the log backing this evidence")
    stamp.set_defaults(func=cmd_stamp)

    check = sub.add_parser("check", help="Recompute fingerprints and print FRESH/STALE rows")
    add_common(check)
    check.add_argument("--ledger", required=True, help="Ledger JSON path")
    check.set_defaults(func=cmd_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
