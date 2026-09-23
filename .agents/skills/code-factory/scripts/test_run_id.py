#!/usr/bin/env python3
"""
Deterministic self-test for `run_id.py` (zero LLM tokens).

Checks through the CLI that (a) `gen` is deterministic and follows the documented contract —
`<YYYYMMDD local date>-<first 8 hex of the SHA-256 of the task file bytes>`, recomputed
independently here, (b) the digest of the committed, static fixture
`assets/task-template.yaml` equals the pinned `4b918a06` — the algorithm proven against a real
committed task file, not only against a temp fixture; the date part is TODAY by construction, so
only its FORMAT `YYYYMMDD-` is pinned (a pinned date would rot overnight), and the ephemeral
runtime task file `.code-factory/state/task.yaml` is never read (its bytes change with every task,
so pinning them would rot at the next run) — and
(c) `check` scans exactly the artifacts a run carries (`state/pipeline.yaml`, `state/acceptance.md`,
`logs/*.md`, `report.md`): an existing artifact without a `run_id: <id>` / `run_id=<id>` line is
listed and exits 1, a fully marked (or empty / absent) directory exits 0, and any id — not only the
current one — counts as marked.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import date

TOOL = pathlib.Path(__file__).with_name("run_id.py")
# .agents/skills/code-factory/scripts/run_id.py -> repository root
REPO = TOOL.resolve().parents[4]
TASK = REPO / ".agents" / "skills" / "code-factory" / "assets" / "task-template.yaml"
# Committed, static fixture task file (same shape as a real task) — pinning it survives every run,
# unlike the ephemeral `.code-factory/state/task.yaml`.
# Its DATE is today's by construction, so only the digest half is compared literally.
KNOWN_TASK_RUN_ID = "20260923-4b918a06"
HEX = set("0123456789abcdef")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def expected_run_id(task: pathlib.Path) -> str:
    """Independent restatement of the contract, so a wrong algorithm cannot agree with itself."""
    digest = hashlib.sha256(task.read_bytes()).hexdigest()
    return f"{date.today():%Y%m%d}-{digest[:8]}"


def scaffold(root: pathlib.Path, run_id: str) -> None:
    """Create the four artifacts a run carries, marking them with `run_id` when it is non-empty."""
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    header = f"run_id: {run_id}\n" if run_id else ""
    (root / "state" / "pipeline.yaml").write_text(header + "phase: implement\n", encoding="utf-8")
    (root / "state" / "acceptance.md").write_text(header + "# Acceptance\n", encoding="utf-8")
    (root / "logs" / "baseline.md").write_text(header + "# Baseline\n", encoding="utf-8")
    (root / "report.md").write_text(header + "# Report\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)

        # 1. gen: deterministic and equal to the documented algorithm (local date + SHA-256 prefix).
        task = tmp / "task.yaml"
        task.write_text("title: provenance\nrepo_path: .\n", encoding="utf-8")
        res = run("gen", "--task", str(task))
        expect(res.returncode == 0, f"gen must exit 0: {res.stderr!r}")
        run_id = res.stdout.strip()
        expect(run_id == expected_run_id(task),
               f"gen must follow <YYYYMMDD>-<sha256[:8]>: {run_id!r} != {expected_run_id(task)!r}")
        expect(run("gen", "--task", str(task)).stdout.strip() == run_id,
               "gen must be deterministic: two runs on one file must print the same id")
        date_part, _, digest_part = run_id.partition("-")
        expect(date_part == f"{date.today():%Y%m%d}",
               f"the id must start with the local date: {run_id!r}")
        expect(len(digest_part) == 8 and set(digest_part) <= HEX,
               f"the id must end with 8 hex digits: {run_id!r}")
        other = tmp / "other.yaml"
        other.write_text("title: another task\n", encoding="utf-8")
        expect(run("gen", "--task", str(other)).stdout.strip() != run_id,
               "two different task files must not share a run id")

        # 2. The committed fixture task file (`assets/task-template.yaml`) keeps the pinned DIGEST; a
        #    missing task file is an error, never a fabricated id. Only the digest is compared: `gen`
        #    dates the id with `date.today()`, so pinning the full literal would make this test fail
        #    tomorrow. The ephemeral runtime task file (`.code-factory/state/task.yaml`) is NOT read:
        #    it changes with every run and would turn this pin into a per-task failure.
        expect(TASK.is_file(), f"the fixture task file must exist: {TASK}")
        res = run("gen", "--task", str(TASK))
        expect(res.returncode == 0, f"gen on the fixture task must exit 0: {res.stderr!r}")
        fixture_run_id = res.stdout.strip()
        _, pinned_digest = KNOWN_TASK_RUN_ID.split("-", 1)
        date_part, _, fixture_digest = fixture_run_id.partition("-")
        expect(re.fullmatch(r"\d{8}", date_part) and fixture_run_id.startswith(date_part + "-"),
               f"the id must start with the date format YYYYMMDD-: {fixture_run_id!r}")
        expect(fixture_digest == pinned_digest,
               f"the fixture task must yield the digest {pinned_digest}: {fixture_run_id!r}")
        res = run("gen", "--task", str(tmp / "missing.yaml"))
        expect(res.returncode == 1 and "error:" in res.stderr,
               f"an unreadable task file must exit 1 with an error: {res.stderr!r}")
        expect("Traceback" not in res.stderr, "a missing task file must not raise a traceback")

        # 3. check positive: every existing artifact is marked -> exit 0.
        cf = tmp / "run" / ".code-factory"
        scaffold(cf, run_id)
        res = run("check", "--dir", str(cf))
        expect(res.returncode == 0, f"fully marked artifacts must exit 0: {res.stdout!r}")

        # 4. check negative: an artifact without a run_id line is named and exits 1; a missing
        #    artifact is not checked at all.
        (cf / "state" / "acceptance.md").write_text("# Acceptance\n", encoding="utf-8")
        (cf / "logs" / "baseline.md").write_text("# Baseline\n", encoding="utf-8")
        res = run("check", "--dir", str(cf))
        expect(res.returncode == 1, "an artifact without a run_id must exit 1")
        output = res.stdout + res.stderr
        expect("state/acceptance.md" in output and "logs/baseline.md" in output,
               f"every unmarked artifact must be listed: {output!r}")
        expect("state/pipeline.yaml" not in output and "report.md" not in output,
               f"marked artifacts must not be listed: {output!r}")
        expect("Traceback" not in res.stderr, "an unmarked artifact must not raise a traceback")
        scaffold(cf, run_id)  # re-mark everything, then drop one artifact: absent files are skipped
        (cf / "report.md").unlink()
        expect(run("check", "--dir", str(cf)).returncode == 0,
               "an absent artifact must not fail the check (only existing ones are checked)")
        (cf / "state" / "pipeline.yaml").unlink()
        (cf / "logs" / "baseline.md").write_text("# Baseline\n", encoding="utf-8")
        res = run("check", "--dir", str(cf))
        expect(res.returncode == 1 and "logs/baseline.md" in res.stdout + res.stderr,
               f"logs/*.md is part of the provenance set: {res.stdout + res.stderr!r}")

        # 5. Any run id counts, and both spellings are accepted: check proves attribution, not that
        #    the artifact belongs to the current run.
        old_cf = tmp / "old" / ".code-factory"
        scaffold(old_cf, "20200101-deadbeef")
        (old_cf / "state" / "acceptance.md").write_text("run_id=20200101-deadbeef\n", encoding="utf-8")
        expect(run("check", "--dir", str(old_cf)).returncode == 0,
               "an older run id and the run_id=<id> form must count as marked")
        expect(run_id != "20200101-deadbeef", "the fixture ids must differ for this check to mean "
                                              "anything")

        # 6. An empty or absent directory has nothing to check (exit 0), and artifacts outside the
        #    checked set (manifest, plan, non-markdown logs) are ignored.
        empty = tmp / "empty" / ".code-factory"
        empty.mkdir(parents=True)
        expect(run("check", "--dir", str(empty)).returncode == 0, "an empty directory must exit 0")
        expect(run("check", "--dir", str(tmp / "absent" / ".code-factory")).returncode == 0,
               "an absent directory must exit 0 (nothing to check)")
        (empty / "manifest.json").write_text("{}\n", encoding="utf-8")
        (empty / "state").mkdir()
        (empty / "state" / "plan.md").write_text("# Plan\n", encoding="utf-8")
        (empty / "logs").mkdir()
        (empty / "logs" / "baseline.log").write_text("log\n", encoding="utf-8")
        expect(run("check", "--dir", str(empty)).returncode == 0,
               "artifacts outside the provenance set must not fail the check")

    print("PASS - run_id.py behaves as expected (deterministic <date>-<sha256[:8]> id, the pinned "
          "digest for the committed task fixture, and a check that names existing .code-factory "
          "artifacts without a run_id).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
