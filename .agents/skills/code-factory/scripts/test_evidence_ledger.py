#!/usr/bin/env python3
"""
Deterministic self-test for `evidence_ledger.py` (zero LLM tokens).

Checks through the CLI that (a) `sign` is a deterministic, order-independent SHA-256 over path +
content, (b) `stamp` creates/refreshes one ledger entry and writes it atomically, (c) `check`
marks entries FRESH/STALE by recomputing the fingerprint — a file edited after signing turns the
evidence STALE and exits 1, a fresh ledger exits 0, (d) a broken ledger is refused, never
overwritten, and never leaves a temp file behind.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("evidence_ledger.py")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def sign(tmp: pathlib.Path, *files: str) -> tuple[str, int]:
    res = run("sign", "--repo", str(tmp), "--files", *files)
    return res.stdout.strip(), res.returncode


def stamp(tmp: pathlib.Path, ledger: pathlib.Path, name: str, result: str,
          *files: str, log: str = "") -> subprocess.CompletedProcess[str]:
    extra = ["--log", log] if log else []
    return run("stamp", "--repo", str(tmp), "--ledger", str(ledger), "--name", name,
               "--result", result, "--files", *files, *extra)


def check(tmp: pathlib.Path, ledger: pathlib.Path, *files: str) -> subprocess.CompletedProcess[str]:
    return run("check", "--repo", str(tmp), "--ledger", str(ledger), "--files", *files)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        (tmp / "a.py").write_text("A-v1\n", encoding="utf-8")
        (tmp / "b.py").write_text("B-v1\n", encoding="utf-8")
        (tmp / "sub").mkdir()
        (tmp / "sub" / "c.py").write_text("C-v1\n", encoding="utf-8")
        ledger = tmp / "state" / "evidence.json"

        # 1. sign: deterministic 64-hex, independent of argument order and of the path spelling.
        first, code = sign(tmp, "a.py", "b.py")
        expect(code == 0, "sign must exit 0")
        expect(bool(HEX64.match(first)), f"sign must print a 64-hex SHA-256: {first!r}")
        expect(sign(tmp, "b.py", "a.py")[0] == first, "file order must not change the fingerprint")
        expect(sign(tmp, "a.py", "a.py")[0] == sign(tmp, "a.py")[0],
               "a repeated file must not change the fingerprint")
        expect(sign(tmp, "./a.py", "b.py")[0] == first, "path spelling must not matter")
        expect(sign(tmp, "a.py", "b.py", "sub/c.py")[0] != first,
               "another signed file must change the fingerprint")

        # 2. Content changes shift the fingerprint; a missing file is a change, not an error.
        (tmp / "a.py").write_text("A-v2\n", encoding="utf-8")
        changed, code = sign(tmp, "a.py", "b.py")
        expect(code == 0, "sign must not fail after an edit")
        expect(changed != first, "an edit of a signed file must shift the fingerprint")
        gone, code = sign(tmp, "a.py", "deleted.py")
        expect(code == 0 and bool(HEX64.match(gone)),
               f"a missing signed file must be hashed as a change, not crash: {gone!r}")

        # 3. stamp creates the ledger (directories included) and check accepts FRESH evidence.
        (tmp / "a.py").write_text("A-v1\n", encoding="utf-8")
        res = stamp(tmp, ledger, "regression", "pass", "a.py", "b.py",
                    log=".code-factory/logs/regression.log")
        expect(res.returncode == 0, f"stamp must exit 0: {res.stderr!r}")
        expect(ledger.is_file(), "stamp must create the ledger, directories included")
        data = json.loads(ledger.read_text(encoding="utf-8"))
        entry = data["entries"][0]
        expect(entry["name"] == "regression" and entry["result"] == "pass",
               f"the stamped entry must record name and result: {data!r}")
        expect(entry["fingerprint"] == sign(tmp, "a.py", "b.py")[0],
               "the stamped fingerprint must be the fingerprint of the signed files")
        expect(entry["log"].endswith("regression.log"), "the optional --log must be recorded")
        expect(bool(entry["timestamp"]), "every entry must carry a timestamp")
        res = check(tmp, ledger, "a.py", "b.py")
        expect(res.returncode == 0, f"FRESH + pass evidence must exit 0: {res.stdout!r}")
        expect("FRESH" in res.stdout and "STALE" in res.stdout,
               f"check must print a FRESH/STALE table: {res.stdout!r}")
        expect("regression" in res.stdout and "FRESH" in res.stdout.split("regression")[1],
               f"the regression row must be FRESH: {res.stdout!r}")

        # 4. An edit after signing -> STALE + exit 1 (the whole point: stale evidence is rejected).
        (tmp / "b.py").write_text("B-v2\n", encoding="utf-8")
        res = check(tmp, ledger, "a.py", "b.py")
        expect(res.returncode == 1, "STALE evidence must exit 1")
        expect(res.stdout.split("regression")[1].strip().startswith("pass"),
               f"the table must keep the row readable: {res.stdout!r}")
        expect("STALE" in res.stdout, f"the changed file must make the entry STALE: {res.stdout!r}")
        expect("STALE" in res.stdout.split("regression")[1][:40],
               f"the regression row itself must be STALE: {res.stdout!r}")
        (tmp / "b.py").write_text("B-v1\n", encoding="utf-8")
        expect(check(tmp, ledger, "a.py", "b.py").returncode == 0,
               "restoring the file content must make the evidence FRESH again")

        # 5. Re-stamping a name refreshes it instead of piling up stale entries.
        stamp(tmp, ledger, "regression", "pass", "a.py")
        data = json.loads(ledger.read_text(encoding="utf-8"))
        expect(len(data["entries"]) == 1, f"a re-stamp must refresh, not duplicate: {data!r}")
        expect(check(tmp, ledger, "a.py").returncode == 0, "the refreshed scope must be FRESH")
        expect(check(tmp, ledger, "a.py", "b.py").returncode == 1,
               "a wider scope than the signed one must be STALE")

        # 6. A failed result is never accepted, even while the fingerprint is FRESH.
        stamp(tmp, ledger, "regression", "fail", "a.py")
        res = check(tmp, ledger, "a.py")
        expect(res.returncode == 1, "result=fail must exit 1 even when FRESH")
        expect("fail" in res.stdout and "not pass" in res.stdout,
               f"the recorded result and its cause must appear: {res.stdout!r}")
        stamp(tmp, ledger, "unit", "pass", "a.py")
        expect(check(tmp, ledger, "a.py").returncode == 1,
               "one non-pass entry must fail the whole check (all entries must be FRESH and pass)")
        expect("unit" in check(tmp, ledger, "a.py").stdout, "every entry must be listed")

        # 7. An empty/missing ledger is never "trusted": exit 1, no traceback.
        res = check(tmp, tmp / "nope.json", "a.py")
        expect(res.returncode == 1, "a missing ledger must exit 1")
        expect("no entries" in res.stdout or "no entries" in res.stderr,
               f"the reason must say there is no evidence: {res.stdout + res.stderr!r}")
        expect("Traceback" not in res.stderr, "a missing ledger must not raise a traceback")

        # 8. Atomicity: a broken ledger is refused, left byte-identical, and no temp file remains.
        broken = tmp / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        res = stamp(tmp, broken, "regression", "pass", "a.py")
        expect(res.returncode == 1 and "error:" in res.stderr,
               f"stamping into a broken ledger must exit 1 with an error: {res.stderr!r}")
        expect("Traceback" not in res.stderr, "a broken ledger must not raise a traceback")
        expect(broken.read_text(encoding="utf-8") == "{not json",
               "a broken ledger must never be overwritten or damaged")
        expect(not list(tmp.glob("*.tmp")), "a failed stamp must not leave temp files behind")
        res = check(tmp, broken, "a.py")
        expect(res.returncode == 1, "checking a broken ledger must exit 1, never 0")
        bad_shape = tmp / "badshape.json"
        bad_shape.write_text('["not", "an", "object"]', encoding="utf-8")
        res = stamp(tmp, bad_shape, "regression", "pass", "a.py")
        expect(res.returncode == 1 and "error:" in res.stderr,
               f"a non-object ledger must be refused: {res.stderr!r}")

        # 9. Usage errors are reported, not crashed: --result is a closed set, --ledger required.
        res = run("stamp", "--repo", str(tmp), "--ledger", str(ledger), "--name", "x",
                  "--result", "green", "--files", "a.py")
        expect(res.returncode != 0, "an unknown --result must be rejected")
        res = run("check", "--repo", str(tmp), "--files", "a.py")
        expect(res.returncode != 0, "--ledger is required for check")
        res = run("sign", "--repo", str(tmp / "does-not-exist"), "--files", "a.py")
        expect(res.returncode == 0, "sign over a missing repo is still deterministic, not an error")

    print("PASS - evidence_ledger.py behaves as expected (deterministic sign, atomic stamp, "
          "FRESH/STALE check with stale evidence rejected).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
