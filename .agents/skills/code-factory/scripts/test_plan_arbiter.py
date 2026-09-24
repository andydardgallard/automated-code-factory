#!/usr/bin/env python3
"""
Deterministic self-test for `plan_arbiter.py` (zero LLM tokens, stdlib only).

Builds two competing plans in a temp dir — a shared task id with an IDENTICAL body, a shared id
with DIFFERENT bodies (the conflict), ids only one plan carries, overlapping and one-sided risks
and business tests — and verifies:

  - tasks merge BY ID: the identical one appears exactly once, the conflicting id leaves the merged
    task list and lands in `## Divergences` with both wordings, one-sided ids are carried over;
  - risks and business tests merge as deduplicated unions (sorted, one copy each);
  - the divergence list names the one-sided risks and business tests of each plan;
  - the CLI contract: the merged plan on stdout, --out holds the same text, exit 0, --help works;
  - broken input exits 2 with a message naming the file and the problem and never a traceback:
    a missing file, a directory instead of a file, a plan without `## Tasks (DAG)`, an empty task
    list, a malformed task line, a task without `verification:`, the same id twice with different
    bodies, and a missing required argument;
  - determinism: two runs over the same inputs print byte-identical output and swapping
    --plan-a/--plan-b leaves the merged tasks, risks and business tests untouched.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

import plan_arbiter as pa

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "plan_arbiter.py"
# The divergence list carries non-ASCII characters (the em dash): pin UTF-8 on the child's stdout
# so the assertions are portable across console code pages (the script itself replaces unencodable
# characters, never crashes).
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

TASK_01 = "task_01: add the arbiter script; files: [scripts/plan_arbiter.py]; deps: []; " \
          "verification: python scripts/test_plan_arbiter.py"
TASK_02_A = "task_02: update SKILL.md only; files: [SKILL.md]; deps: [task_01]; " \
            "verification: python validate_mermaid.py"
TASK_02_B = "task_02: update SKILL.md and the planning guide; files: [SKILL.md, " \
            "planning-guide.md]; deps: []; verification: python validate_mermaid.py"
TASK_03 = "task_03: document the rule; files: [AGENTS.md]; deps: []; " \
          "verification: python check_factory_rules.py"
TASK_04 = "task_04: extend the rulebook; files: [factory-rules.md]; deps: [task_01]; " \
          "verification: python check_factory_rules.py"

RISK_SHARED = "the two planners disagree on scope"
RISK_A = "the golden set is not committed"
RISK_B = "the arbiter might be fed stale plans"
TEST_SHARED = "the merged plan is presented to the user"
TEST_B = "the user sees the divergence list"


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write_plan(root: pathlib.Path, name: str, tasks: list[str], risks: list[str],
               tests: list[str]) -> pathlib.Path:
    """Write one plan.md carrying exactly the given machine-readable sections (UTF-8, LF)."""
    lines = ["# Plan: demo", "", "## Goal (business)", "do the thing", "", "## Tasks (DAG)"]
    lines += [f"- {task}" for task in tasks]
    lines += ["", "## Risks"] + [f"- {risk}" for risk in risks]
    lines += ["", "## Business tests"] + [f"- {test}" for test in tests]
    path = root / name
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def write_raw(root: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = root / name
    path.write_bytes(text.encode("utf-8"))
    return path


def run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, env=ENV)


def out(res: subprocess.CompletedProcess[bytes]) -> str:
    """stdout as text, CRLF-normalized (Windows text-mode stdout may translate newlines)."""
    return res.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def err(res: subprocess.CompletedProcess[bytes]) -> str:
    return res.stderr.decode("utf-8", "replace")


def block(markdown: str, heading: str) -> list[str]:
    """Bullet lines of the `## <heading>` section of a rendered plan."""
    lines = markdown.splitlines()
    start = lines.index(f"## {heading}") + 1
    out_lines: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip():
            out_lines.append(line)
    return out_lines


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        plan_a = write_plan(root, "plan-a.md", [TASK_01, TASK_02_A, TASK_03],
                            [RISK_SHARED, RISK_A], [TEST_SHARED])
        plan_b = write_plan(root, "plan-b.md", [TASK_01, TASK_02_B, TASK_04],
                            [RISK_SHARED, RISK_B], [TEST_SHARED, TEST_B])

        # 1. the merged plan: tasks by id, deduplicated risks/tests, exit 0.
        res = run("--plan-a", str(plan_a), "--plan-b", str(plan_b))
        expect(res.returncode == 0, f"a valid pair must exit 0, got {res.returncode}: {err(res)!r}")
        expect(b"Traceback" not in res.stderr, f"no traceback expected: {err(res)!r}")
        merged = out(res)
        expect(block(merged, "Tasks (DAG)") == [f"- {TASK_01}", f"- {TASK_03}", f"- {TASK_04}"],
               f"tasks must merge by id and stay sorted: {block(merged, 'Tasks (DAG)')}")
        expect(block(merged, "Risks") == [f"- {RISK_B}", f"- {RISK_A}", f"- {RISK_SHARED}"],
               f"risks must merge as a sorted deduplicated union: {block(merged, 'Risks')}")
        expect(block(merged, "Business tests") == [f"- {TEST_SHARED}", f"- {TEST_B}"],
               f"business tests must merge as a union: {block(merged, 'Business tests')}")

        # 2. the conflict: out of the task list, both wordings in the divergence list.
        divergent = "\n".join(block(merged, "Divergences (user decision)"))
        expect("task_02" in divergent, f"the conflicting id must be listed: {divergent!r}")
        expect(pa.normalize(TASK_02_A.split(": ", 1)[1]) in divergent,
               f"plan A's wording of the conflict must be quoted: {divergent!r}")
        expect(pa.normalize(TASK_02_B.split(": ", 1)[1]) in divergent,
               f"plan B's wording of the conflict must be quoted: {divergent!r}")
        expect(not [line for line in block(merged, "Tasks (DAG)") if "- task_02" in line],
               "the conflicting id must stay out of the merged task list")

        # 3. one-sided risks and business tests are named per plan.
        expect(f"- risk only in plan A: {RISK_A}" in divergent,
               f"a plan-A-only risk must be listed: {divergent!r}")
        expect(f"- risk only in plan B: {RISK_B}" in divergent,
               f"a plan-B-only risk must be listed: {divergent!r}")
        expect(f"- business test only in plan B: {TEST_B}" in divergent,
               f"a plan-B-only business test must be listed: {divergent!r}")

        # 4. --out carries the same text; --help works.
        target = root / "plan-merged.md"
        res_out = run("--plan-a", str(plan_a), "--plan-b", str(plan_b), "--out", str(target))
        expect(res_out.returncode == 0, f"--out must exit 0: {err(res_out)!r}")
        expect(target.read_bytes().decode("utf-8") == out(res_out),
               "--out must hold exactly the text printed to stdout")
        helper = run("--help")
        expect(helper.returncode == 0, f"--help must exit 0, got {helper.returncode}")
        for flag in ("--plan-a", "--plan-b", "--out"):
            expect(flag in out(helper), f"--help must document {flag}")

        # 5. determinism: same inputs twice, and a swapped pair keeps the merged sections.
        again = run("--plan-a", str(plan_a), "--plan-b", str(plan_b))
        expect(again.stdout == res.stdout, "two runs over the same inputs must be byte-identical")
        swapped = out(run("--plan-a", str(plan_b), "--plan-b", str(plan_a)))
        for heading in ("Tasks (DAG)", "Risks", "Business tests"):
            expect(block(swapped, heading) == block(merged, heading),
                   f"swapping --plan-a/--plan-b must not change {heading!r}")

        # 6. identical bodies collapse into one task, whatever the input order.
        twin = pathlib.Path(tmp) / "plan-twin.md"
        twin.write_bytes(plan_a.read_bytes())
        same = out(run("--plan-a", str(plan_a), "--plan-b", str(twin)))
        expect(block(same, "Tasks (DAG)") == [f"- {TASK_01}", f"- {TASK_02_A}", f"- {TASK_03}"],
               f"identical plans must merge without duplicates: {block(same, 'Tasks (DAG)')}")
        expect("no divergences" in same, f"identical plans have no divergences: {same!r}")

        # 7. broken input: exit 2, the file named, never a traceback.
        bare = write_raw(root, "bare.md", "# Plan\n\nJust prose, no machine-readable sections.\n")
        empty_tasks = write_raw(root, "empty.md", "# Plan\n\n## Tasks (DAG)\n\n## Risks\n- none\n")
        malformed = write_raw(root, "malformed.md",
                              "# Plan\n\n## Tasks (DAG)\n- task_01 files: [a.py]; deps: []; "
                              "verification: x\n")
        no_verify = write_raw(root, "noverify.md",
                              "# Plan\n\n## Tasks (DAG)\n- task_01: change a; files: [a.py]; "
                              "deps: []\n")
        twice = write_raw(root, "twice.md",
                          "# Plan\n\n## Tasks (DAG)\n- task_01: change a; deps: []; verification: x\n"
                          "- task_01: change b; deps: []; verification: y\n")
        bad = [
            (root / "missing.md", "cannot read"),
            (bare, "## Tasks (DAG)"),
            (empty_tasks, "declares no task"),
            (malformed, "malformed task line"),
            (no_verify, "verification"),
            (twice, "declared twice"),
        ]
        for path, needle in bad:
            broken = run("--plan-a", str(path), "--plan-b", str(plan_b))
            expect(broken.returncode == 2, f"{path.name} must exit 2, got {broken.returncode}")
            expect(needle in err(broken), f"{path.name}: stderr {err(broken)!r} lacks {needle!r}")
            expect(path.name in err(broken), f"{path.name}: stderr must name the file")
            expect("Traceback" not in err(broken), f"{path.name}: no traceback: {err(broken)!r}")

        # a directory instead of a plan file is a contract error too, not a crash.
        as_dir = run("--plan-a", str(root), "--plan-b", str(plan_b))
        expect(as_dir.returncode == 2 and "cannot read" in err(as_dir),
               f"a directory must exit 2 with a message: {err(as_dir)!r}")
        expect("Traceback" not in err(as_dir), f"a directory must not raise: {err(as_dir)!r}")

        # a missing required argument is argparse's usage error (exit 2), still no traceback.
        missing_arg = run("--plan-b", str(plan_b))
        expect(missing_arg.returncode == 2, "a missing --plan-a must exit 2")
        expect("Traceback" not in err(missing_arg), f"usage errors must not traceback: "
                                                    f"{err(missing_arg)!r}")

    # 8. stdlib-only contract (no third-party imports).
    source = pathlib.Path(pa.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", source, flags=re.M))
    allowed = {"__future__", "argparse", "dataclasses", "pathlib", "re", "sys"}
    expect(imported <= allowed, f"plan_arbiter must be stdlib-only, imports={imported}")

    print("PASS - plan_arbiter.py merges two plans by task id (identical bodies once, conflicts and "
          "one-sided risks/business tests into the divergence list), deduplicates the unions, is "
          "byte-deterministic and rejects unstructured input with exit 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
