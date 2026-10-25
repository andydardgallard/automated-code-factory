#!/usr/bin/env python3
"""
Deterministic self-test for `verify_quotes.py` (zero LLM tokens).

Verifies the Evidence-Preserving Reducer check through its CLI: an exact quote is verified (exit
0), an invented quote is UNTRUSTED (exit 1) with the fail-safe `fallback to full log` note, a
missing source is UNTRUSTED instead of a crash, an EMPTY claims file is UNVERIFIED (exit 2 —
nothing was checked, a contract error), a CRLF source matches a quote written with LF, and
the OPTIONAL `--repo`/`--base` anchor resolves a RELATIVE source (and a relative
`--claims`/`--report`) against the run's resolved repo_path instead of the launch directory —
without the flag the cwd stays the base and an absolute path is never re-anchored.

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

        # 7. An empty claims list is NOT verified: nothing was checked, so the verdict is
        #    UNVERIFIED with exit 2 (a contract error), never the vacuous "VERIFIED" of old.
        claims = write_claims(tmp, [], name="none.json")
        res = run("--claims", str(claims), cwd=tmp)
        report = json.loads(res.stdout)
        expect(res.returncode == 2 and report["total"] == 0,
               f"an empty claims list must exit 2: {res.returncode} {res.stderr!r}")
        expect(report["all_verified"] is False,
               f"an empty claims list must not report all_verified: {report!r}")
        expect("UNVERIFIED" in res.stderr and "nothing was checked" in res.stderr,
               f"the empty-set verdict must say nothing was checked: {res.stderr!r}")
        expect("every quote matches" not in res.stderr,
               f"the empty set must not claim every quote matches: {res.stderr!r}")
        expect("Traceback" not in res.stderr, "an empty claims list must not raise a traceback")

        # 8. The OPTIONAL `--repo`/`--base` anchor: a run whose repo_path is not its launch directory
        #    resolves a RELATIVE source — and a relative --claims/--report — against the resolved
        #    repo_path, so quotes taken from the target repository's `.code-factory/` are checked
        #    against THAT repository. Without the flag the cwd stays the base (cases 1-7), and an
        #    absolute source / claims path is never re-anchored.
        launch = tmp / "launch"
        launch.mkdir()
        repo = tmp / "target" / "repo"
        target_log = repo / ".code-factory" / "logs" / "baseline.md"
        target_log.parent.mkdir(parents=True)
        target_log.write_text(SOURCE_TEXT, encoding="utf-8")
        rel_claims = repo / ".code-factory" / "state" / "claims.json"
        rel_claims.parent.mkdir(parents=True)
        rel_claims.write_text(json.dumps([{"quote": QUOTE,
                                           "source": ".code-factory/logs/baseline.md"}]),
                              encoding="utf-8")
        res = run("--claims", ".code-factory/state/claims.json", "--repo", str(repo),
                  "--report", ".code-factory/logs/quotes.json", cwd=launch)
        expect(res.returncode == 0,
               f"--repo must anchor a relative --claims and source: {res.stderr!r}")
        report = json.loads((repo / ".code-factory" / "logs" / "quotes.json")
                            .read_text(encoding="utf-8"))
        expect(report["all_verified"] is True and report["verified"][0]["line"] == 3,
               f"the anchored source must verify the quote: {report!r}")
        expect(report["verified"][0]["source"] == ".code-factory/logs/baseline.md",
               "the report must keep the source exactly as the claim wrote it")
        expect(report["claims_file"] == ".code-factory/state/claims.json",
               "the report must keep the claims path exactly as passed")
        expect(not (launch / ".code-factory").exists(),
               "nothing may be written into the launch directory when --repo is given")
        res = run("--claims", ".code-factory/state/claims.json", "--base", str(repo), cwd=launch)
        expect(res.returncode == 0 and json.loads(res.stdout)["all_verified"] is True,
               f"--base must be accepted as a synonym of --repo: {res.stdout!r} {res.stderr!r}")
        res = run("--claims", ".code-factory/state/claims.json", cwd=launch)
        expect(res.returncode == 1 and "error:" in res.stderr,
               f"without --repo a relative --claims resolves against the cwd: {res.stderr!r}")
        res = run("--claims", str(rel_claims), cwd=launch)
        expect(res.returncode == 1 and "fallback to full log" in res.stdout,
               f"without --repo a relative source resolves against the cwd: {res.stdout!r}")
        abs_claims = write_claims(tmp, [{"quote": QUOTE, "source": str(target_log)}],
                                  name="abs-source.json")
        res = run("--claims", str(abs_claims), "--repo", str(launch), cwd=launch)
        expect(res.returncode == 0 and json.loads(res.stdout)["all_verified"] is True,
               f"an absolute source must never be re-anchored: {res.stdout!r} {res.stderr!r}")

    print("PASS - verify_quotes.py behaves as expected (exact quote verified, invented/missing/"
          "empty sources UNTRUSTED with fail-safe, an empty claims file UNVERIFIED with exit 2, "
          "CRLF normalized to LF only, relative sources anchored at --repo/--base).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
