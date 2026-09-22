#!/usr/bin/env python3
"""
Deterministic self-test for `log_tail.py` (zero LLM tokens, stdlib only).

Verifies the counters (total_lines/total_bytes), the per-`--grep` match counts, the tail length
and the exit-code contract (0 whenever the log is readable, 1 for a missing file or a bad
pattern/`--lines`).

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import log_tail as lt

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "log_tail.py"

LOG = "line1\nFAILED test_alpha\nERROR disk full\nline4\nFAILED test_beta\nline6\n"
LOG_LINES = 6
LOG_BYTES = len(LOG.encode("utf-8"))


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def counter(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + ": "):
            return line.split(": ", 1)[1]
    raise AssertionError(f"missing counter {key!r} in output: {text!r}")


def tail_of(text: str) -> list[str]:
    lines = text.splitlines()
    marker = next((i for i, ln in enumerate(lines) if ln.startswith("--- last ")), None)
    return [] if marker is None else lines[marker + 1:]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "tests.log"
        log.write_bytes(LOG.encode("utf-8"))

        # 1-3. Counters and the default tail (whole file, since 6 < 50).
        res = run(str(log))
        expect(res.returncode == 0, f"a readable log must exit 0: {res.stderr!r}")
        expect(counter(res.stdout, "total_lines") == str(LOG_LINES),
               f"total_lines: {res.stdout!r}")
        expect(counter(res.stdout, "total_bytes") == str(LOG_BYTES),
               f"total_bytes: {res.stdout!r}")
        expect(tail_of(res.stdout) == LOG.splitlines(), f"default tail must be whole: {res.stdout!r}")
        expect(str(log) in res.stdout, "the output must name the file")

        # 4. --lines 2 prints exactly the last two lines.
        res = run(str(log), "--lines", "2")
        expect(res.returncode == 0, "--lines 2 must exit 0")
        expect(tail_of(res.stdout) == ["FAILED test_beta", "line6"],
               f"unexpected tail: {res.stdout!r}")
        expect("line1" not in res.stdout, "the tail must not contain earlier lines")

        # 5. --lines larger than the file prints everything (no padding, no error).
        res = run(str(log), "--lines", "500")
        expect(res.returncode == 0, "--lines 500 must exit 0")
        expect(tail_of(res.stdout) == LOG.splitlines(), f"unexpected tail: {res.stdout!r}")

        # 6. --lines 0 keeps the counters and prints no tail at all.
        res = run(str(log), "--lines", "0")
        expect(res.returncode == 0, "--lines 0 must exit 0")
        expect(counter(res.stdout, "total_lines") == str(LOG_LINES), "--lines 0 must keep counters")
        expect("---" not in res.stdout and "line1" not in res.stdout,
               f"--lines 0 must print no tail: {res.stdout!r}")

        # 7-9. Every --grep gets its own match count; repeated flags are all reported.
        res = run(str(log), "--grep", "FAILED")
        expect(counter(res.stdout, "grep 'FAILED'") == "2", f"FAILED count: {res.stdout!r}")
        res = run(str(log), "--grep", "ERROR")
        expect(counter(res.stdout, "grep 'ERROR'") == "1", f"ERROR count: {res.stdout!r}")
        res = run(str(log), "--grep", "FAILED", "--grep", "ERROR")
        expect(counter(res.stdout, "grep 'FAILED'") == "2"
               and counter(res.stdout, "grep 'ERROR'") == "1",
               f"both patterns must be reported: {res.stdout!r}")
        res = run(str(log), "--grep", "FAILED|ERROR")
        expect(counter(res.stdout, "grep 'FAILED|ERROR'") == "3",
               f"alternation count: {res.stdout!r}")

        # 10-11. Bad input: an invalid regex and an unreadable file both exit 1.
        res = run(str(log), "--grep", "(")
        expect(res.returncode == 1, "an invalid --grep pattern must exit 1")
        expect("invalid --grep pattern" in res.stderr, f"must explain the bad pattern: {res.stderr!r}")
        expect(run(str(tmp / "missing.log")).returncode == 1, "a missing log must exit 1")
        expect(run(str(log), "--lines", "-1").returncode == 1, "a negative --lines must exit 1")

        # 12. An empty log is still a readable log.
        empty = tmp / "empty.log"
        empty.write_bytes(b"")
        res = run(str(empty))
        expect(res.returncode == 0, "an empty log must exit 0")
        expect(counter(res.stdout, "total_lines") == "0"
               and counter(res.stdout, "total_bytes") == "0",
               f"an empty log must report zeroes: {res.stdout!r}")

        # 13. A log with invalid UTF-8 bytes must not crash anything.
        mixed = tmp / "mixed.log"
        mixed.write_bytes(b"ok\n\xff\xfe broken\nFAILED boom\n")
        res = run(str(mixed), "--grep", "FAILED")
        expect(res.returncode == 0, f"non-UTF-8 bytes must not break the tail: {res.stderr!r}")
        expect(counter(res.stdout, "total_lines") == "3", f"line count: {res.stdout!r}")
        expect(counter(res.stdout, "grep 'FAILED'") == "1", f"match count: {res.stdout!r}")

    # 14-15. Library-level counting rules.
    expect(lt.count_lines(b"") == 0, "an empty log has 0 lines")
    expect(lt.count_lines(b"a\nb\n") == 2, "a trailing newline adds no line")
    expect(lt.count_matches(["a", "b"], ["a"]) == [("a", 1)], "match counting")
    expect(lt.count_matches(["FAILED x", "failed y"], ["FAILED"]) == [("FAILED", 1)],
           "matching must be case-sensitive by default")
    expect(lt.count_matches(["x"], ["x", "y"]) == [("x", 1), ("y", 0)],
           "a pattern without matches is reported as 0")

    print("PASS - log_tail.py reports counters, grep matches and the tail with the expected "
          "exit codes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
