#!/usr/bin/env python3
"""
Deterministic self-test for `verify_acceptance.py` (zero LLM tokens).

Verifies the anti-tautology acceptance gate end to end through its CLI: a passing verify command
is MET, a failing one is FAILED, criteria without `verify` are UNVERIFIED and labeled
derived/unverified, commands really run inside `--repo`, long output is excerpted, and the verdict
follows the rules (SUCCESS only with all verify criteria MET + regression pass; DEGRADED without a
regression proof or without any verify criterion; FAILURE on any failure), and the optional
evidence ledger gate (--ledger/--evidence-files) downgrades SUCCESS to DEGRADED on STALE, failed,
missing or unparsable evidence, while a FRESH regression=pass ledger keeps SUCCESS. The optional
`--run-id` only adds the `run_id: <id>` provenance line to the acceptance header.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("verify_acceptance.py")
LEDGER_TOOL = pathlib.Path(__file__).with_name("evidence_ledger.py")
PY = f'"{sys.executable}"'


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def run_ledger(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(LEDGER_TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write_criteria(tmp: pathlib.Path, items: list[dict], name: str = "criteria.json") -> pathlib.Path:
    path = tmp / name
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        (tmp / "marker.txt").write_text("MARKER-CONTENT\n", encoding="utf-8")

        # 1. All verify criteria MET + regression pass -> SUCCESS, exit 0, acceptance.md evidence.
        criteria = write_criteria(tmp, [
            {"criterion": "exit code zero is proof", "verify": f'{PY} -c "print(\'OK-MARKER\')"'},
            {"criterion": "runs inside --repo", "verify":
                f'{PY} -c "print(open(\'marker.txt\', encoding=\'utf-8\').read().strip())"'},
        ])
        md = tmp / "acceptance.md"
        res = run("--input", str(criteria), "--output", str(md), "--repo", str(tmp),
                  "--regression", "pass")
        expect(res.returncode == 0, f"all MET + regression pass must exit 0: {res.stderr!r}")
        text = md.read_text(encoding="utf-8")
        expect("Verdict: **SUCCESS**" in text, f"SUCCESS verdict must be reported: {text[:200]!r}")
        expect("| 0 |" in text and text.count("| 0 |") == 2,
               f"every exit code 0 must appear in the table: {text!r}")
        expect("OK-MARKER" in text, "the verify command output must be kept as evidence")
        expect("MARKER-CONTENT" in text,
               "the command must run with cwd=--repo (marker.txt is relative to it)")
        expect("MET" in text, "a successful criterion must be marked MET")

        # 2. A failing verify command -> FAILED + verdict FAILURE, non-zero exit.
        criteria = write_criteria(tmp, [
            {"criterion": "this one fails", "verify":
                f'{PY} -c "import sys; print(\'FAIL-OUT\'); sys.exit(3)"'},
        ], name="fail.json")
        md_fail = tmp / "acceptance_fail.md"
        res = run("--input", str(criteria), "--output", str(md_fail), "--repo", str(tmp),
                  "--regression", "pass")
        expect(res.returncode == 1, "a FAILED criterion must exit 1")
        text = md_fail.read_text(encoding="utf-8")
        expect("Verdict: **FAILURE**" in text, f"any failure must yield FAILURE: {text[:200]!r}")
        expect("| 3 |" in text, f"the real exit code 3 must be recorded: {text!r}")
        expect("FAILED" in text, "the failing criterion must be marked FAILED")
        expect("FAIL-OUT" in text, "the failing command output must be kept as evidence")

        # 3. Long output is excerpted (tail kept, head dropped, truncation is explicit).
        criteria = write_criteria(tmp, [
            {"criterion": "noisy command", "verify":
                f'{PY} -c "print(chr(10).join(\'L%02d\' % i for i in range(1, 31)))"'},
        ], name="long.json")
        md_long = tmp / "acceptance_long.md"
        res = run("--input", str(criteria), "--output", str(md_long), "--repo", str(tmp),
                  "--regression", "pass")
        expect(res.returncode == 0, f"the noisy command exits 0: {res.stderr!r}")
        text = md_long.read_text(encoding="utf-8")
        expect("L30" in text, "the tail of a long output must be kept")
        expect("L01" not in text, "the head of a long output must be dropped")
        expect("truncated" in text, "a truncated excerpt must say so")

        # 4. Criteria without verify -> UNVERIFIED, labeled derived / unverified, and the report
        #    still lists them next to the verified ones.
        criteria = write_criteria(tmp, [
            {"criterion": "verified", "verify": f'{PY} -c "pass"'},
            {"criterion": "inferred from artifacts", "derived": True},
            {"criterion": "never checked"},
        ], name="mixed.json")
        md_mixed = tmp / "acceptance_mixed.md"
        res = run("--input", str(criteria), "--output", str(md_mixed), "--repo", str(tmp),
                  "--regression", "pass")
        expect(res.returncode == 0,
               f"verified criterion MET + regression pass = SUCCESS: {res.stderr!r}")
        text = md_mixed.read_text(encoding="utf-8")
        expect("Verdict: **SUCCESS**" in text, "unverified criteria do not block SUCCESS by themselves")
        expect("UNVERIFIED (derived)" in text, "derived=true must be labeled derived")
        expect("UNVERIFIED (unverified)" in text, "a criterion without verify/derived is unverified")
        expect("Criteria: 3 (verified: 1, unverified: 2)" in text,
               f"the counts must be reported: {text[:400]!r}")

        # 5. Degraded baseline: all MET but regression not-run -> DEGRADED, exit 1.
        criteria = write_criteria(tmp, [{"criterion": "ok", "verify": f'{PY} -c "pass"'}],
                                  name="ok.json")
        md_degraded = tmp / "acceptance_degraded.md"
        res = run("--input", str(criteria), "--output", str(md_degraded), "--repo", str(tmp),
                  "--regression", "not-run")
        expect(res.returncode == 1, "regression not-run must not exit 0")
        text = md_degraded.read_text(encoding="utf-8")
        expect("Verdict: **DEGRADED**" in text, f"a missing regression proof must degrade: {text[:200]!r}")
        expect("Regression baseline: not-run" in text, "the regression state must be recorded")

        # 6. Regression fail -> FAILURE even when every verify criterion is MET.
        res = run("--input", str(criteria), "--output", str(tmp / "acceptance_regfail.md"),
                  "--repo", str(tmp), "--regression", "fail")
        expect(res.returncode == 1, "a failed baseline must exit 1")
        expect("Verdict: **FAILURE**" in (tmp / "acceptance_regfail.md").read_text(encoding="utf-8"),
               "a failed baseline must yield FAILURE")

        # 7. No verify criterion at all -> DEGRADED (nothing was actually verified, even with a
        #    passing baseline): the anti-tautology hole stays closed.
        noverify = write_criteria(tmp, [{"criterion": "self-declared", "derived": True}],
                                  name="noverify.json")
        md_noverify = tmp / "acceptance_noverify.md"
        res = run("--input", str(noverify), "--output", str(md_noverify), "--repo", str(tmp),
                  "--regression", "pass")
        expect(res.returncode == 1, "no verify criterion must not exit 0")
        expect("Verdict: **DEGRADED**" in md_noverify.read_text(encoding="utf-8"),
               "nothing verified must be DEGRADED, never SUCCESS")

        # 8. Malformed input / missing repo -> exit 1 with an error, never a traceback.
        broken = tmp / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        res = run("--input", str(broken), "--output", str(tmp / "x.md"), "--repo", str(tmp))
        expect(res.returncode == 1 and "error:" in res.stderr,
               f"broken JSON must exit 1 with an error message: {res.stderr!r}")
        expect("Traceback" not in res.stderr, "broken JSON must not raise a traceback")
        bad_shape = tmp / "badshape.json"
        bad_shape.write_text('{"criterion": "not a list"}', encoding="utf-8")
        res = run("--input", str(bad_shape), "--output", str(tmp / "x.md"), "--repo", str(tmp))
        expect(res.returncode == 1 and "array" in res.stderr,
               f"a non-array criteria file must exit 1: {res.stderr!r}")
        res = run("--input", str(criteria), "--output", str(tmp / "x.md"),
                  "--repo", str(tmp / "does-not-exist"))
        expect(res.returncode == 1 and "--repo" in res.stderr,
               f"a missing --repo must exit 1: {res.stderr!r}")

        # 9. A hanging command is killed (process tree) by --timeout and marked FAILED.
        criteria = write_criteria(tmp, [
            {"criterion": "hangs forever", "verify": f'{PY} -c "import time; time.sleep(20)"'},
        ], name="hang.json")
        md_hang = tmp / "acceptance_hang.md"
        res = run("--input", str(criteria), "--output", str(md_hang), "--repo", str(tmp),
                  "--regression", "pass", "--timeout", "1")
        expect(res.returncode == 1, "a timed-out command must fail the acceptance")
        text = md_hang.read_text(encoding="utf-8")
        expect("Verdict: **FAILURE**" in text, "a timeout must yield FAILURE")
        expect("timeout after 1s" in text, f"the timeout must be recorded as evidence: {text!r}")

        # 10. Output directories are created on demand (the main agent points at state/).
        nested = tmp / "out" / "state" / "acceptance.md"
        res = run("--input", str(noverify), "--output", str(nested), "--repo", str(tmp),
                  "--regression", "pass")
        expect(res.returncode == 1, "still DEGRADED for the no-verify criteria file")
        expect(nested.is_file(), "a missing output directory must be created")

        # 11. Evidence ledger, FRESH: FRESH regression=pass evidence keeps SUCCESS and is reported.
        ledger_criteria = write_criteria(
            tmp, [{"criterion": "ledger gate", "verify": f'{PY} -c "pass"'}], name="ledger_ok.json")
        ledger_src = tmp / "ledger_src.py"
        ledger_src.write_text("value = 1\n", encoding="utf-8")
        ledger = tmp / "state" / "evidence.json"
        res = run_ledger("stamp", "--repo", str(tmp), "--ledger", str(ledger), "--name",
                         "regression", "--result", "pass", "--files", "ledger_src.py")
        expect(res.returncode == 0, f"stamping the ledger must work: {res.stderr!r}")
        md_ledger = tmp / "acceptance_ledger.md"
        res = run("--input", str(ledger_criteria), "--output", str(md_ledger), "--repo", str(tmp),
                  "--regression", "pass", "--ledger", str(ledger),
                  "--evidence-files", "ledger_src.py")
        expect(res.returncode == 0,
               f"FRESH regression=pass evidence must not block SUCCESS: {res.stdout!r}")
        text = md_ledger.read_text(encoding="utf-8")
        expect("Verdict: **SUCCESS**" in text, f"a FRESH ledger keeps SUCCESS: {text[:300]!r}")
        expect("## Evidence ledger" in text and "all entries FRESH" in text,
               f"the ledger must be reported when --ledger is given: {text!r}")
        expect("Evidence ledger" not in (tmp / "acceptance.md").read_text(encoding="utf-8"),
               "without --ledger the report must be unchanged (no ledger section)")

        # 12. STALE evidence (the signed file changed after stamping) downgrades SUCCESS to
        #     DEGRADED even with --regression pass, and the reason lands in acceptance.md.
        ledger_src.write_text("value = 2\n", encoding="utf-8")
        md_stale = tmp / "acceptance_stale.md"
        res = run("--input", str(ledger_criteria), "--output", str(md_stale), "--repo", str(tmp),
                  "--regression", "pass", "--ledger", str(ledger),
                  "--evidence-files", "ledger_src.py")
        expect(res.returncode == 1, "STALE evidence must never be accepted")
        text = md_stale.read_text(encoding="utf-8")
        expect("Verdict: **DEGRADED**" in text,
               f"a STALE ledger must downgrade SUCCESS to DEGRADED: {text[:300]!r}")
        expect("evidence ledger rejected" in text and "STALE" in text,
               f"the rejection reason must be explicit in acceptance.md: {text!r}")
        expect("| regression | pass | STALE |" in text,
               f"the per-entry freshness table must mark the entry STALE: {text!r}")

        # 13. A ledger without FRESH regression=pass evidence degrades: some other FRESH evidence
        #     (unit) is not enough to certify the acceptance.
        unit_ledger = tmp / "unit" / "evidence.json"
        res = run_ledger("stamp", "--repo", str(tmp), "--ledger", str(unit_ledger), "--name",
                         "unit", "--result", "pass", "--files", "ledger_src.py")
        expect(res.returncode == 0, f"stamping the unit evidence must work: {res.stderr!r}")
        md_unit = tmp / "acceptance_unit_ledger.md"
        res = run("--input", str(ledger_criteria), "--output", str(md_unit), "--repo", str(tmp),
                  "--regression", "pass", "--ledger", str(unit_ledger),
                  "--evidence-files", "ledger_src.py")
        expect(res.returncode == 1, "FRESH unit evidence is not FRESH regression evidence")
        text = md_unit.read_text(encoding="utf-8")
        expect("Verdict: **DEGRADED**" in text and "no FRESH regression=pass evidence" in text,
               f"the missing regression evidence must be named: {text[:400]!r}")

        # 14. A missing or broken ledger is a rejection too (fail-safe), never a silent pass.
        for broken_ledger, label in ((tmp / "missing.json", "missing"),
                                     (broken, "unparsable")):  # case 8 `broken` is invalid JSON
            md_bad = tmp / f"acceptance_ledger_{label}.md"
            res = run("--input", str(ledger_criteria), "--output", str(md_bad), "--repo", str(tmp),
                      "--regression", "pass", "--ledger", str(broken_ledger),
                      "--evidence-files", "ledger_src.py")
            expect(res.returncode == 1, f"a {label} ledger must exit 1")
            text = md_bad.read_text(encoding="utf-8")
            expect("Verdict: **DEGRADED**" in text and "evidence ledger" in text,
                   f"a {label} ledger must degrade with a reason: {text[:300]!r}")
            expect("Traceback" not in res.stderr, f"a {label} ledger must not raise a traceback")

        # 15. --run-id stamps the run provenance into the header and changes nothing else.
        runid_criteria = write_criteria(tmp, [{"criterion": "ok", "verify": f'{PY} -c "pass"'}],
                                        name="runid.json")
        md_runid = tmp / "acceptance_runid.md"
        res = run("--input", str(runid_criteria), "--output", str(md_runid), "--repo", str(tmp),
                  "--regression", "pass", "--run-id", "20260922-442cd2f8")
        expect(res.returncode == 0, f"a run id must not change the verdict: {res.stderr!r}")
        text_runid = md_runid.read_text(encoding="utf-8")
        expect("run_id: 20260922-442cd2f8" in text_runid,
               f"the run id must be recorded in acceptance.md: {text_runid[:300]!r}")
        expect("Verdict: **SUCCESS**" in text_runid, "the verdict must stay unaffected by --run-id")

    print("PASS - verify_acceptance.py behaves as expected (MET/FAILED/UNVERIFIED with "
          "derived/unverified labels, excerpts, SUCCESS/DEGRADED/FAILURE verdicts, the "
          "evidence ledger gate: FRESH keeps SUCCESS, STALE/missing evidence degrades, and the "
          "optional --run-id provenance line).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
