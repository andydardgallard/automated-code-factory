#!/usr/bin/env python3
"""
Deterministic self-test for `review_followup_task.py` (zero LLM tokens).

A report-only review run hands its merged findings over as ONE factory task file. This test drives
the generator through its CLI and checks the whole contract:

  - the emitted file is a flat factory task carrying every required key, `mode: hitl` and
    `task_type: implement`, with the `--repo` value as `repo_path`;
  - `acceptance_criteria` holds one criterion per finding plus a final MACHINE-VERIFIABLE one and
    the "the change is reviewed" one, each finding criterion marked `derived: true` unless it
    carries a `verify` command (given by the finding, or derived from its location by running the
    module's sibling self-test);
  - REGRESSION (review 20261026-1c588b16, major 4): the generated task always carries at least one
    non-empty `verify` — the verified-acceptance gate accepts only such a task — and that command
    really executes in the repository;
  - the description groups the findings by severity with `file:line`, reports the RECOMPUTED
    counts (the stale `counts` of the input are ignored), states that the file comes from a
    report-only run and names the generation command;
  - every scalar is quoted, so a finding containing `: `, a `"` and a newline round-trips through
    the script's own reader byte-exactly;
  - the same argv produces a byte-identical file (determinism);
  - `--check` accepts a generated file and rejects one with a missing key, while the CLI keeps the
    sibling contract: `--help` -> 0, usage error -> 2, unreadable `--findings` -> 1, invalid
    content -> 2, no traceback;
  - VACCINATION: the same content emitted by a naive `f"{key}: {value}"` emitter is a document
    that does not parse, so the quoting cannot silently regress.

Everything is written into a temp directory; the repository is never touched.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).with_name("review_followup_task.py")
sys.path.insert(0, str(TOOL.parent))
import review_followup_task as generator  # noqa: E402  (needs the sys.path line above)

# Fixture findings: a `"` and `: ` in the title AND the detail, a multi-line detail, a finding
# without a line number and one without a detail. The `counts` of the fixture are deliberately
# wrong (all zero) to prove the generator recomputes them.
FINDINGS = [
    {"severity": "critical", "file": "src/app.py", "line": 12,
     "title": 'Guard says: "python: x" is not a command',
     "detail": 'The check prints: "not supported" and then passes silently.\n'
               'A second line: with a colon and a " quote.',
     "occurrences": ["shard-1"]},
    {"severity": "major", "file": "src/util.py", "line": None,
     "title": "Whole-file finding: no line number",
     "detail": 'Says "hello" without a location.'},
    {"severity": "minor", "file": "docs/readme.md", "line": 5,
     "title": "Wording is stale",
     "detail": ""},
]
MERGED = {
    "verdict": "request_changes",
    "counts": {"critical": 0, "major": 0, "minor": 0, "nit": 0},
    "findings": FINDINGS,
    "shards": [{"shard": "shard-1", "verdict": "request_changes"}],
}
COUNTS_TEXT = "critical: 1, major: 1, minor: 1, nit: 0"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args],
                          capture_output=True, text=True, errors="replace")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write_json(path: pathlib.Path, payload) -> pathlib.Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        repo = tmp / "target repo"          # a space in the path must survive the quoting
        repo.mkdir()
        merged = write_json(tmp / "code-review-merged.json", MERGED)
        out = tmp / "state" / "review-followup.yaml"
        run_id = "20261025-d412a454"

        # 1. The CLI contract: --help exits 0 and lists the flags.
        res = run("--help")
        expect(res.returncode == 0, f"--help must exit 0: {res.stderr!r}")
        expect("--verdict-ok" in res.stdout and "--check" in res.stdout and "--run-id" in res.stdout,
               f"--help must document the flags: {res.stdout[:400]!r}")

        # 2. A missing --findings outside --check is a usage error (exit 2, no traceback).
        res = run("--repo", str(repo), "--out", str(out))
        expect(res.returncode == 2, f"a missing --findings must exit 2: {res.returncode}")
        expect("Traceback" not in res.stderr, "a usage error must not raise a traceback")

        # 3. Generate the task from the merged report.
        res = run("--findings", str(merged), "--repo", str(repo), "--out", str(out),
                  "--run-id", run_id)
        expect(res.returncode == 0, f"generation must exit 0: {res.stderr!r}")
        expect(f"wrote {out} (3 findings)" in res.stdout,
               f"the CLI must report what it wrote: {res.stdout!r}")
        text = out.read_text(encoding="utf-8")
        first_bytes = out.read_bytes()

        # 4. Every required key is present, the repo path and mode are the emitted ones.
        task = generator.parse_task(text)
        for key in generator.REQUIRED_TASK_KEYS:
            expect(task.get(key), f"the generated task must carry '{key}': {sorted(task)}")
        expect(task["mode"] == "hitl", f"mode must be hitl: {task['mode']!r}")
        expect(task["task_type"] == "implement", f"task_type must be implement: {task['task_type']!r}")
        expect(task["repo_path"] == str(repo),
               f"repo_path must be the --repo value verbatim: {task['repo_path']!r}")
        expect(run_id in task["title"], f"the title must name the review run: {task['title']!r}")
        expect(COUNTS_TEXT in task["title"],
               f"the title must carry the recomputed counts: {task['title']!r}")
        expect("request_changes" in task["title"],
               f"the title must carry the review verdict: {task['title']!r}")

        # 5. The description groups the findings by severity with file:line, recomputes the
        #    counts and states where the file comes from.
        description = task["description"]
        expect(COUNTS_TEXT in description,
               f"the stale input counts must be recomputed: {description[:400]!r}")
        expect("report-only" in description and "never edits the project" in description,
               "the description must say the file comes from a report-only review run")
        expect("Run this task when you choose to" in description,
               "the description must say the owner runs it when they choose")
        expect(generator.GENERATOR_COMMAND in description,
               "the description must name the generation command")
        for severity in ("critical", "major", "minor"):
            expect(f"## {severity} (1)" in description,
                   f"every severity with findings must have its own group: {severity} missing")
        expect("## nit" not in description,
               "a severity without findings must not get an empty group")
        expect("src/app.py:12" in description, "a finding with a line must be named file:line")
        expect("src/util.py" in description and "src/util.py:None" not in description,
               "a finding without a line must be named by file alone")
        expect("A second line: with a colon" in " ".join(description.split()),
               "the full multi-line detail must survive in the description")

        # 6. One criterion per finding plus the final VERIFIED criterion and the review criterion.
        criteria = task["acceptance_criteria"]
        expect(len(criteria) == len(FINDINGS) + 2,
               f"expected {len(FINDINGS) + 2} criteria, got {len(criteria)}")
        for finding, item in zip(FINDINGS, criteria):
            expect(isinstance(item, dict) and item.get("criterion"),
                   f"every finding needs its own criterion: {item!r}")
            expect(item.get("derived") is True,
                   f"a criterion without a verify command must be derived: {item!r}")
            expect(generator.flatten(finding["title"]) in item["criterion"],
                   f"the criterion must quote its finding: {item['criterion']!r}")
        expect("reviewed" in criteria[-1]["criterion"],
               f"the last criterion must be the review one: {criteria[-1]!r}")
        expect("[critical] src/app.py:12" in criteria[0]["criterion"],
               f"the criterion must carry severity and file:line: {criteria[0]['criterion']!r}")

        # 7. Round-trip: the scalar with `: ` and `"` comes back byte-exactly, and the raw file
        #    really carries the escaped form (an unquoted emitter would have broken here).
        expect(criteria[0]["criterion"] == generator.criterion_text(FINDINGS[0]),
               f"the quoted criterion must round-trip exactly: {criteria[0]['criterion']!r}")
        expect('\\"' in text, "quotes inside a finding must be escaped in the file")
        expect('not supported\\"' in text or 'not supported' in text,
               "the detail must survive quoting")

        # 8. Determinism: the same argv produces a byte-identical file.
        res = run("--findings", str(merged), "--repo", str(repo), "--out", str(out),
                  "--run-id", run_id)
        expect(res.returncode == 0, f"the second run must succeed: {res.stderr!r}")
        expect(out.read_bytes() == first_bytes,
               "the same input must produce a byte-identical task file")

        # 9. --check: a generated file is valid, a file missing a required key is not.
        res = run("--check", "--out", str(out))
        expect(res.returncode == 0, f"--check must accept the generated file: {res.stderr!r}")
        broken = tmp / "broken-task.yaml"
        broken.write_text("\n".join(line for line in text.split("\n")
                                   if not line.startswith("repo_path:")), encoding="utf-8")
        res = run("--check", "--out", str(broken))
        expect(res.returncode == 1, f"--check must reject a task without repo_path: {res.returncode}")
        expect("repo_path" in res.stderr, f"the missing key must be named: {res.stderr!r}")
        expect("Traceback" not in res.stderr, "--check must not raise a traceback")
        res = run("--check", "--out", str(tmp / "absent.yaml"))
        expect(res.returncode == 1, "an unreadable --check target must exit 1")

        # 10. VACCINATION: the naive `f"{key}: {value}"` emitter produces a document that does not
        #     parse — the same content, so the only difference is the quoting this test guards.
        naive = "\n".join([
            "title: " + task["title"],
            "repo_path: " + str(repo),
            "description: " + description,          # multi-line, unquoted
            "mode: hitl",
            "task_type: implement",
            "acceptance_criteria:",
            "  - criterion: " + criteria[0]["criterion"],
            "    derived: true",
            "commit_exclude:",
            '  - "task.yaml"',
        ]) + "\n"
        naive_problem = ""
        try:
            generator.parse_task(naive)
        except ValueError as exc:
            naive_problem = str(exc)
        expect(naive_problem != "",
               "the naive unquoted emitter must produce a file that does not parse")
        expect(generator.check_task(text) == [],
               f"the real file must be valid while the naive one is not: {naive_problem}")

        # 11. A bare findings list (no merged report) is accepted and carries no verdict.
        bare = write_json(tmp / "bare.json", FINDINGS[:1])
        out_bare = tmp / "bare-task.yaml"
        res = run("--findings", str(bare), "--repo", str(repo), "--out", str(out_bare))
        expect(res.returncode == 0 and "1 findings" in res.stdout,
               f"a bare findings list must be accepted: {res.stdout!r} {res.stderr!r}")
        bare_task = generator.parse_task(out_bare.read_text(encoding="utf-8"))
        expect("review verdict: not reported" in bare_task["description"],
               "a bare list carries no review verdict")

        # 12. A finding carrying a verify command is emitted with `verify`, not `derived`.
        verified = write_json(tmp / "verified.json", [
            {"severity": "major", "file": "src/app.py", "line": 7, "title": "Run the suite",
             "detail": "the suite must pass", "verify": "python -m pytest -q"},
        ])
        out_verified = tmp / "verified-task.yaml"
        res = run("--findings", str(verified), "--repo", str(repo), "--out", str(out_verified))
        expect(res.returncode == 0, f"a verify command must be accepted: {res.stderr!r}")
        verified_task = generator.parse_task(out_verified.read_text(encoding="utf-8"))
        item = verified_task["acceptance_criteria"][0]
        expect(item.get("verify") == "python -m pytest -q",
               f"the verify command must be carried over: {item!r}")
        expect("derived" not in item, f"a verified criterion is not derived: {item!r}")

        # 13. An accepted verdict with no findings has nothing to hand over: nothing is written.
        clean = write_json(tmp / "clean.json",
                           {"verdict": "approve", "counts": {}, "findings": [], "shards": []})
        out_clean = tmp / "clean-task.yaml"
        res = run("--findings", str(clean), "--repo", str(repo), "--out", str(out_clean))
        expect(res.returncode == 0, f"an accepted clean report must exit 0: {res.stderr!r}")
        expect("nothing to do" in res.stdout, f"the no-op must be reported: {res.stdout!r}")
        expect(not out_clean.exists(), "an accepted clean report must not write a task file")
        # ... and --verdict-ok still hands over findings of an otherwise accepted report.
        res = run("--findings", str(merged), "--repo", str(repo), "--out", out_clean,
                  "--verdict-ok", "approve,request_changes")
        expect(res.returncode == 0 and out_clean.exists(),
               "findings must be handed over even when --verdict-ok accepts the verdict")

        # 13b. --title overrides the derived title and is named in the reproducing command.
        out_titled = tmp / "titled-task.yaml"
        res = run("--findings", str(merged), "--repo", str(repo), "--out", str(out_titled),
                  "--title", 'Owner: close the "review" findings')
        expect(res.returncode == 0, f"a custom title must be accepted: {res.stderr!r}")
        titled = out_titled.read_text(encoding="utf-8")
        expect(generator.parse_task(titled)["title"] == 'Owner: close the "review" findings',
               f"the custom title must win and survive quoting: {titled[:400]!r}")
        expect('--title "Owner: close the \\"review\\" findings"' in titled,
               "the reproducing command must carry the custom title")

        # 14. Exit codes of broken input: unreadable -> 1, invalid content -> 2, no traceback.
        res = run("--findings", str(tmp / "absent.json"), "--repo", str(repo), "--out", str(out))
        expect(res.returncode == 1 and "cannot read" in res.stderr,
               f"an unreadable --findings must exit 1: {res.returncode} {res.stderr!r}")
        broken_json = tmp / "broken.json"
        broken_json.write_text("{not json", encoding="utf-8")
        res = run("--findings", str(broken_json), "--repo", str(repo), "--out", str(out))
        expect(res.returncode == 2 and "invalid JSON" in res.stderr,
               f"broken JSON must exit 2: {res.returncode} {res.stderr!r}")
        bad_severity = write_json(tmp / "bad-severity.json", [
            {"severity": "blocker", "file": "a.py", "line": 1, "title": "x", "detail": ""}])
        res = run("--findings", str(bad_severity), "--repo", str(repo), "--out", str(out))
        expect(res.returncode == 2 and "severity" in res.stderr,
               f"a finding outside the contract must exit 2: {res.returncode} {res.stderr!r}")
        expect("Traceback" not in res.stderr, "invalid input must not raise a traceback")

        # 15. REGRESSION (review run 20261026-1c588b16, major 4): a generated task always carries a
        #     MACHINE-VERIFIABLE criterion. Before the fix every criterion was `derived` (the final
        #     one unconditionally), so the verified-acceptance gate could only ever report DEGRADED.
        #     A finding pointing at a module whose sibling self-test exists derives `python <test>`,
        #     and the final criterion re-runs those checks.
        checkable_repo = tmp / "checked repo"
        (checkable_repo / "scripts").mkdir(parents=True)
        (checkable_repo / "scripts" / "check.py").write_text("VALUE = 1\n", encoding="utf-8")
        (checkable_repo / "scripts" / "test_check.py").write_text("print('ok - check')\n",
                                                                  encoding="utf-8")
        (checkable_repo / "scripts" / "other.py").write_text("VALUE = 2\n", encoding="utf-8")
        checkable = write_json(tmp / "checkable.json", [
            {"severity": "critical", "file": "scripts/check.py", "line": 1,
             "title": "The check always passes", "detail": "it must bite on the broken input"},
            {"severity": "minor", "file": "scripts/other.py", "line": 1,
             "title": "No sibling self-test for this file", "detail": ""},
        ])
        out_checkable = tmp / "checkable-task.yaml"
        res = run("--findings", str(checkable), "--repo", str(checkable_repo),
                  "--out", str(out_checkable))
        expect(res.returncode == 0, f"a checkable finding must generate a task: {res.stderr!r}")
        checked_text = out_checkable.read_text(encoding="utf-8")
        checked_criteria = generator.parse_task(checked_text)["acceptance_criteria"]
        verified_items = [item for item in checked_criteria
                          if str(item.get("verify", "")).strip()]
        expect(verified_items,
               "the generated task must carry at least one criterion with a verify command, "
               f"else the acceptance gate can only report DEGRADED: {checked_criteria!r}")
        derived_item = checked_criteria[0]
        expect(derived_item.get("verify") == "python scripts/test_check.py",
               f"a finding with a sibling self-test derives that command: {derived_item!r}")
        expect("derived" not in derived_item,
               f"a criterion carrying a verify command is not derived: {derived_item!r}")
        expect(checked_criteria[1].get("derived") is True,
               f"a finding with nothing checkable stays derived: {checked_criteria[1]!r}")
        final_verify = checked_criteria[-2]
        expect(str(final_verify.get("verify", "")).strip() != "",
               f"the final criterion must carry a verify command: {final_verify!r}")
        expect(final_verify["verify"] == "python scripts/test_check.py",
               f"the final criterion re-runs the derived checks: {final_verify!r}")
        expect("derived" not in final_verify,
               f"the final verify criterion is not derived: {final_verify!r}")
        # The emitted command really executes, exactly as the acceptance gate runs it (cwd = repo).
        executed = subprocess.run(final_verify["verify"], shell=True, cwd=str(checkable_repo),
                                  capture_output=True, text=True, errors="replace")
        expect(executed.returncode == 0,
               f"the emitted verify command must actually execute: {executed.stdout!r} "
               f"{executed.stderr!r}")
        expect("ok - check" in executed.stdout,
               f"the verify command's own evidence must come back: {executed.stdout!r}")
        # Acceptance shape: the file parses and carries a usable verify command.
        expect(generator.check_task(checked_text) == [],
               f"a generated task must pass the acceptance-shape check: "
               f"{generator.check_task(checked_text)}")

        # 16. When nothing is checkable the final criterion still carries a REAL command (the
        #     tree-soundness gate) instead of an empty verify — the task is never doomed.
        final_default = criteria[-2]
        expect(final_default.get("verify") == generator.DEFAULT_FINAL_VERIFY,
               f"the fallback final verify must be the tree-soundness gate: {final_default!r}")
        expect("derived" not in final_default,
               f"the fallback final verify criterion is not derived: {final_default!r}")
        executed = subprocess.run(final_default["verify"], shell=True, cwd=str(repo),
                                  capture_output=True, text=True, errors="replace")
        expect(executed.returncode == 0,
               f"the fallback verify command must actually execute: {executed.stdout!r} "
               f"{executed.stderr!r}")

        # 17. `--check` rejects a task whose criteria carry no verify command at all (the shape the
        #     bug produced): the verified-acceptance gate would finish DEGRADED on it.
        unverified = tmp / "unverified-task.yaml"
        unverified.write_text("\n".join(line for line in text.split("\n")
                                        if not line.startswith("    verify:")),
                              encoding="utf-8")
        res = run("--check", "--out", str(unverified))
        expect(res.returncode == 1,
               f"--check must reject a task without any verify criterion: {res.returncode}")
        expect("verify" in res.stderr, f"the missing verify must be named: {res.stderr!r}")

    print("PASS - review_followup_task.py behaves as expected (flat factory task with quoted "
          "scalars, one criterion per finding plus a VERIFIED final criterion and the review "
          "one, same input -> identical bytes, --check shape validation, exit codes 0/1/2, and "
          "the naive-emitter vaccination).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
