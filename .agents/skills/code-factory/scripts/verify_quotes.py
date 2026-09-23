#!/usr/bin/env python3
"""
Evidence-Preserving Reducer check for the Code Factory (zero LLM tokens).

The Diagnostician and the code-reviewer must back every finding with a verbatim quote from the
archived evidence (logs or code under `.code-factory/` / the repository). This script re-checks
each quote as an EXACT substring of its source file before a frontier model ever sees the reduced
summary: a reducer may compress a log, it may not invent text.

Normalization is deliberately minimal — CRLF -> LF only, so a log written on Windows matches a
quote pasted on POSIX. Case and whitespace are NOT normalized: an approximate match is a failed
match.

Fail-safe: a missing/unreadable source, an empty quote or a quote that is not found verbatim is
reported as UNTRUSTED, always with an explicit `fallback to full log` note — the caller must
re-read the raw archive instead of trusting the reduction. Unreadable input never crashes the run.

Input (JSON):
  [{"quote": "exact text from the source", "source": ".code-factory/logs/baseline.md"}, ...]
  A relative `source` is resolved against the current working directory.

Usage:
  python verify_quotes.py --claims claims.json [--report quotes-report.json]

Output: the JSON report goes to `--report` when given, otherwise to stdout; the human-readable
summary always goes to stderr. Exit code 0 only if EVERY quote is verified. stdlib only.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

FAIL_SAFE = "fallback to full log"


def normalize(text: str) -> str:
    """CRLF -> LF only; case, spaces and tabs are evidence and stay untouched."""
    return text.replace("\r\n", "\n")


def read_source(path: pathlib.Path) -> str | None:
    """Return the normalized source text, or None when it cannot be read as text."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return normalize(data.decode("utf-8", errors="replace"))


def check_claim(quote: str, source: str, cwd: pathlib.Path) -> dict:
    """Verify one quote against its source; return a report entry."""
    if not quote:
        return {"quote": quote, "source": source, "reason":
                f"empty quote is never evidence; {FAIL_SAFE}"}
    path = pathlib.Path(source)
    if not path.is_absolute():
        path = cwd / path
    text = read_source(path)
    if text is None:
        return {"quote": quote, "source": source, "reason":
                f"source missing or unreadable: {source}; {FAIL_SAFE}"}
    quote_norm = normalize(quote)
    if quote_norm not in text:
        return {"quote": quote, "source": source, "reason":
                f"quote is not an exact substring of {source}; {FAIL_SAFE}"}
    return {"quote": quote, "source": source,
            "line": text[:text.index(quote_norm)].count("\n") + 1}


def load_claims(path: pathlib.Path) -> list[dict]:
    """Read the claims JSON; raise ValueError with a human-readable cause on malformed input."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read claims file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"claims file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"claims file {path} must contain a JSON array of objects")
    claims: list[dict] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"claim #{idx} must be a JSON object")
        quote, source = item.get("quote", ""), item.get("source", "")
        if not isinstance(quote, str) or not isinstance(source, str):
            raise ValueError(f"claim #{idx}: 'quote' and 'source' must be strings")
        claims.append({"quote": quote, "source": source})
    return claims


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
    ap.add_argument("--claims", required=True, help="Claims JSON file (see module docstring)")
    ap.add_argument("--report", default="", help="Write the JSON report here (default: stdout)")
    args = ap.parse_args()

    try:
        claims = load_claims(pathlib.Path(args.claims))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    cwd = pathlib.Path.cwd()
    verified: list[dict] = []
    untrusted: list[dict] = []
    for claim in claims:
        entry = check_claim(claim["quote"], claim["source"], cwd)
        if "reason" in entry:
            untrusted.append(entry)
        else:
            verified.append(entry)

    report = {
        "claims_file": args.claims,
        "total": len(claims),
        "verified_count": len(verified),
        "untrusted_count": len(untrusted),
        "all_verified": not untrusted,
        "verified": verified,
        "untrusted": untrusted,
    }
    blob = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        out = pathlib.Path(args.report)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(blob, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write {out}: {exc}", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(blob)

    # ASCII only on stdout/stderr: a legacy Windows console code page must never make the run crash.
    print(f"verify_quotes: {len(claims)} claim(s) - {len(verified)} verified, "
          f"{len(untrusted)} untrusted", file=sys.stderr)
    for entry in untrusted:
        print(f"  UNTRUSTED {entry['source']}: {entry['reason']}", file=sys.stderr)
    if untrusted:
        print(f"verify_quotes: verdict UNTRUSTED - {FAIL_SAFE}", file=sys.stderr)
        return 1
    print("verify_quotes: verdict VERIFIED - every quote matches its source verbatim",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
