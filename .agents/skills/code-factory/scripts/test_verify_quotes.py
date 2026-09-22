#!/usr/bin/env python3
"""
Deterministic self-test for `verify_quotes.py` (zero LLM tokens).

Verifies the Evidence-Preserving Reducer check through its CLI: an exact quote is verified (exit
0), an invented quote is UNTRUSTED (exit 1) with the fail-safe `fallback to full log` note, a
missing source is UNTRUSTED instead of a crash, and a CRLF source matches a quote written with LF.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("verify_quotes.py")

SOURCE_TEXT = ("# Baseline\nline one\nline two: ERROR boom\nline three\n")
QUOTE = "line two: ERROR boom"


def run(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace", cwd=str(cwd))


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write_claims(tmp: pathlib.Path, claims: list[dict], name: str = "claims.json") -> pathlib.Path:
    path = tmp / name
    path.write_text(json.dumps(claims, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        log = tmp / "logs" / "baseline.md"
        log.parent.mkdir(parents=True)
        log.write_text(SOURCE_TEXT, encoding="utf-8")

        # 1. An exact quote is VERIFIED: exit 0, reported in `verified` with its line number.
        claims = write_claims(tmp, [{"quote": QUOTE, "source": "logs/baseline.md"}])
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 0, f"an exact quote must exit 0: {res.stderr!r}")
        report = json.loads(res.stdout)
        expect(report["all_verified"] is True and report["verified_count"] == 1,
               f"the exact quote must be listed as verified: {report!r}")
        expect(report["verified"][0]["line"] == 3, f"the source line must be reported: {report!r}")
        expect(report["untrusted"] == [], "nothing may be untrusted in this run")
        expect("verified" in res.stderr and "VERIFIED" in res.stderr,
               f"a human-readable summary must go to stderr: {res.stderr!r}")

        # 2. An invented quote is UNTRUSTED: exit 1, reason carries the fail-safe note, and the
        #    report keeps the *original* claim so the caller can fall back to the full log.
        fake = "line two: ERROR cATASTROPHE never written"
        claims = write_claims(tmp, [{"quote": QUOTE, "source": "logs/baseline.md"},
                                    {"quote": fake, "source": "logs/baseline.md"}],
                              name="mixed.json")
        report_path = tmp / "report.json"
        res = run("--claims", str(claims), "--report", str(report_path), cwd=tmp)
        expect(res.returncode == 1, "an untrusted quote must exit 1")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        expect(report["verified_count"] == 1 and report["untrusted_count"] == 1,
               f"the report must split verified/untrusted: {report!r}")
        expect(report["all_verified"] is False, "all_verified must be false with an untrusted quote")
        bad = report["untrusted"][0]
        expect(bad["quote"] == fake and bad["source"] == "logs/baseline.md",
               f"the untrusted entry must keep the original claim: {bad!r}")
        expect("fallback to full log" in bad["reason"],
               f"the fail-safe note must be explicit: {bad!r}")
        expect(res.stdout == "", "with --report the JSON must not also be dumped to stdout")
        expect("UNTRUSTED" in res.stderr, f"the summary must name the untrusted claim: {res.stderr!r}")

        # 3. Case and whitespace are evidence, not noise: a re-cased / re-spaced quote fails.
        claims = write_claims(tmp, [{"quote": "Line Two: ERROR boom", "source": "logs/baseline.md"}],
                              name="recased.json")
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 1,
               "a re-cased quote must NOT be verified (no case normalization, anti-hallucination)")

        # 4. A missing or unreadable source is UNTRUSTED (never a crash) with the fail-safe note.
        claims = write_claims(tmp, [{"quote": QUOTE, "source": "logs/gone.md"}], name="missing.json")
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 1 and "Traceback" not in res.stderr,
               f"a missing source must not crash: {res.stderr!r}")
        report = json.loads(res.stdout)
        expect("fallback to full log" in report["untrusted"][0]["reason"],
               f"a missing source needs the fail-safe note: {report!r}")
        # A directory is unreadable as a source too.
        claims = write_claims(tmp, [{"quote": QUOTE, "source": "logs"}], name="dir.json")
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 1 and json.loads(res.stdout)["untrusted_count"] == 1,
               "a directory as source must be UNTRUSTED, not fatal")
        # An empty quote is never evidence.
        claims = write_claims(tmp, [{"quote": "", "source": "logs/baseline.md"}], name="empty.json")
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 1, "an empty quote must not be verified")

        # 5. A CRLF source matches a quote held with LF (the only normalization allowed).
        crlf = tmp / "logs" / "baseline_crlf.md"
        crlf.write_bytes(SOURCE_TEXT.replace("\n", "\r\n").encode("utf-8"))
        claims = write_claims(tmp, [{"quote": "line one\nline two: ERROR boom",
                                     "source": "logs/baseline_crlf.md"}], name="crlf.json")
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 0, f"a CRLF source must match an LF quote: {res.stderr!r}")
        # ... and a multi-line quote that spans a line break still matches.
        expect(json.loads(res.stdout)["verified"][0]["line"] == 2,
               "the first line of a multi-line quote must be reported")

        # 6. Malformed claims input -> exit 1 with an error message, never a traceback.
        broken = tmp / "broken.json"
        broken.write_text("[{\"quote\": 1}]", encoding="utf-8")
        res = run("--claims", str(broken), cwd=tmp)
        expect(res.returncode == 1 and "error:" in res.stderr and "Traceback" not in res.stderr,
               f"non-string fields must exit 1 cleanly: {res.stderr!r}")
        res = run("--claims", str(tmp / "nope.json"), cwd=tmp)
        expect(res.returncode == 1 and "error:" in res.stderr,
               f"a missing claims file must exit 1 cleanly: {res.stderr!r}")

        # 7. An empty claims list is vacuously verified (nothing was claimed).
        claims = write_claims(tmp, [], name="none.json")
        res = run("--claims", str(claims), cwd=tmp)
        expect(res.returncode == 0 and json.loads(res.stdout)["total"] == 0,
               f"an empty claims list must exit 0: {res.stderr!r}")

    print("PASS - verify_quotes.py behaves as expected (exact quote verified, invented/missing/"
          "empty sources UNTRUSTED with fail-safe, CRLF normalized to LF only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
