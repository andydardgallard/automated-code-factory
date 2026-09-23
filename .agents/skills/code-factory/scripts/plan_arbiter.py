#!/usr/bin/env python3
"""
Deterministic arbiter of two competing plans for the plan committee (zero LLM tokens, stdlib).

When the user rejects a plan TWICE (hitl mode, the Revise branch of plan approval), the main agent
launches a SECOND independent `factory-planner` subagent from a CONTRASTING model family. The two
plans are reconciled HERE, by a deterministic script, so the merged plan cannot be reshaped by
prose (see `references/factory-rules.md` -> `plan-committee`):

  plan_arbiter.py --plan-a <plan.md> --plan-b <plan.md> [--out <path>]

Both plans are read through their machine-readable sections (`references/planning-guide.md` §4):

  ## Tasks (DAG)
  - task_01: <change>; files: [...]; deps: [...]; verification: <command>
  ## Risks
  - <risk>
  ## Business tests
  - <scenario>

Merging rules (the merged sections never depend on the input order — only the A/B labels of
`## Расхождения` follow which plan was passed as --plan-a):
  - tasks merge BY ID: the same id with an identical (whitespace-normalized) body collapses into
    one task; the same id with a DIFFERENT body is a conflict — both wordings move to the
    `## Расхождения` section and that id stays OUT of the merged task list; an id carried by only
    one plan is taken as it is;
  - `## Risks` and `## Business tests` merge as the deduplicated union of both plans;
  - `## Расхождения` lists, in a fixed order, every task conflict (both wordings) plus every risk
    and business test that only one plan carries — the list the user decides on.

The merged plan goes to stdout (and to --out when given) in the same plan format, so it can be
presented to the user or arbitrated again; `--out` always writes UTF-8 with LF newlines.

Contract errors — a plan without the `## Tasks (DAG)` section, an empty task list, a malformed task
line, a task without `verification:`, one task id declared TWICE within a single plan with
different bodies (the cross-plan conflict above is a finding, not an error), an unreadable file,
an unwritable --out — exit 2 with a message naming the file and the problem, never a traceback.
Exit 0 = merged plan produced.
"""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import sys

SECTION_TASKS = "tasks (dag)"
SECTION_RISKS = "risks"
SECTION_TESTS = "business tests"
SECTIONS = (SECTION_TASKS, SECTION_RISKS, SECTION_TESTS)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
TASK_RE = re.compile(r"^[-*]\s+(?P<task_id>[A-Za-z0-9][A-Za-z0-9_.-]*)\s*:\s*(?P<body>\S.*)$")
ITEM_RE = re.compile(r"^[-*]\s+(?P<body>\S.*)$")
VERIFICATION_RE = re.compile(r"(?:^|;)\s*verification\s*:", re.IGNORECASE)


class InputError(Exception):
    """A plan file does not match the plan contract of `planning-guide.md` §4."""


def normalize(text: str) -> str:
    """Dedup/ordering key part: whitespace collapsed, bracketed lists and `;` separators tidied."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\[\s*", "[", text)
    text = re.sub(r"\s*\]", "]", text)
    text = re.sub(r",\s*", ", ", text)
    text = re.sub(r";\s*", "; ", text)
    return text


@dataclasses.dataclass(frozen=True)
class Plan:
    """One competing plan: the file it came from and its three machine-readable sections."""

    path: str
    tasks: dict[str, str]
    risks: tuple[str, ...]
    business_tests: tuple[str, ...]


def split_sections(text: str) -> dict[str, list[tuple[int, str]]]:
    """Map each known `##` section name to its (line number, line) pairs; other headings end it."""
    sections: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        heading = HEADING_RE.match(line)
        if heading:
            name = heading.group(2).strip().lower()
            current = name if len(heading.group(1)) == 2 and name in SECTIONS else None
            continue
        if current is not None:
            sections.setdefault(current, []).append((lineno, line))
    return sections


def list_items(rows: list[tuple[int, str]]) -> tuple[str, ...]:
    """Normalized, deduplicated, sorted bullets of a list section (prose lines are ignored)."""
    items = {normalize(match.group("body")) for _, line in rows
             if (match := ITEM_RE.match(line.strip()))}
    return tuple(sorted(items))


def parse_plan(path: pathlib.Path, label: str) -> Plan:
    """Parse one plan file; raise InputError naming the file and the problem on any contract miss."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"{label}: cannot read {path} ({exc.strerror or exc})") from None

    sections = split_sections(text)
    rows = sections.get(SECTION_TASKS)
    if rows is None:
        raise InputError(f"{label}: {path} carries no '## Tasks (DAG)' section — it does not match "
                         "the plan contract of planning-guide.md §4")

    tasks: dict[str, str] = {}
    for lineno, line in rows:
        stripped = line.strip()
        if not stripped or not stripped.startswith(("-", "*")):
            continue  # prose inside the section is not a task line
        task = TASK_RE.match(stripped)
        if task is None:
            raise InputError(f"{label}: {path}:{lineno}: malformed task line (expected '- <id>: "
                             f"<change>; files: [...]; deps: [...]; verification: <cmd>'): "
                             f"{stripped[:80]!r}")
        task_id, body = task.group("task_id"), normalize(task.group("body"))
        if not VERIFICATION_RE.search(body):
            raise InputError(f"{label}: {path}:{lineno}: task {task_id!r} carries no "
                             "'verification:' field")
        if tasks.get(task_id, body) != body:
            raise InputError(f"{label}: {path}:{lineno}: task {task_id!r} is declared twice with "
                             "different content")
        tasks[task_id] = body

    if not tasks:
        raise InputError(f"{label}: {path} declares no task in '## Tasks (DAG)'")
    return Plan(str(path), tasks, list_items(sections.get(SECTION_RISKS, [])),
                list_items(sections.get(SECTION_TESTS, [])))


def merge_tasks(plan_a: Plan, plan_b: Plan) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """(merged tasks by id, conflicts as (id, wording A, wording B)) — ids sorted."""
    merged: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []
    for task_id in sorted(set(plan_a.tasks) | set(plan_b.tasks)):
        in_a, in_b = task_id in plan_a.tasks, task_id in plan_b.tasks
        if in_a and in_b:
            body_a, body_b = plan_a.tasks[task_id], plan_b.tasks[task_id]
            if body_a != body_b:
                conflicts.append((task_id, body_a, body_b))
                continue
            merged[task_id] = body_a
        else:
            merged[task_id] = plan_a.tasks[task_id] if in_a else plan_b.tasks[task_id]
    return merged, conflicts


def render(plan_a: Plan, plan_b: Plan) -> str:
    """The merged plan (deterministic) followed by the human-readable divergence list."""
    merged, conflicts = merge_tasks(plan_a, plan_b)
    risks = set(plan_a.risks) | set(plan_b.risks)
    tests = set(plan_a.business_tests) | set(plan_b.business_tests)
    one_sided = tuple(
        (kind, which, sorted(set(first) - set(second)))
        for kind, which, first, second in (
            ("риск", "A", plan_a.risks, plan_b.risks),
            ("риск", "B", plan_b.risks, plan_a.risks),
            ("бизнес-тест", "A", plan_a.business_tests, plan_b.business_tests),
            ("бизнес-тест", "B", plan_b.business_tests, plan_a.business_tests),
        )
    )

    lines = [
        "# Merged plan (plan committee)",
        "",
        f"<!-- merged deterministically by scripts/plan_arbiter.py; plan A: {plan_a.path}; "
        f"plan B: {plan_b.path} -->",
        "<!-- a task id carried by both plans with different bodies stays OUT of ## Tasks (DAG) "
        "and appears under ## Расхождения -->",
        "",
        "## Tasks (DAG)",
    ]
    lines += [f"- {task_id}: {body}" for task_id, body in sorted(merged.items())]
    lines += ["", "## Risks"]
    lines += [f"- {risk}" for risk in sorted(risks)]
    lines += ["", "## Business tests"]
    lines += [f"- {test}" for test in sorted(tests)]
    lines += ["", "## Расхождения (решение пользователя)"]
    if not conflicts and not any(items for _, _, items in one_sided):
        lines.append("- расхождений нет: оба плана совпадают по машиночитаемым секциям.")
    for task_id, body_a, body_b in conflicts:
        lines.append(f"- {task_id}: одинаковый id с разным содержимым — задача не включена в "
                     "merged-план, нужен выбор пользователя:")
        lines.append(f"  - план A: {body_a}")
        lines.append(f"  - план B: {body_b}")
    for kind, which, items in one_sided:
        lines += [f"- {kind} только в плане {which}: {item}" for item in items]
    return "\n".join(lines) + "\n"


def main() -> int:
    # The divergence list is Russian: a console code page that cannot encode it must not crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan-a", required=True, metavar="PLAN", help="First plan.md (state/plan.md)")
    ap.add_argument("--plan-b", required=True, metavar="PLAN", help="Second, independent plan.md")
    ap.add_argument("--out", metavar="PATH", help="Also write the merged plan to this path")
    args = ap.parse_args()

    plans: list[Plan] = []
    for label, name in (("plan A", args.plan_a), ("plan B", args.plan_b)):
        try:
            plans.append(parse_plan(pathlib.Path(name), label))
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    merged = render(plans[0], plans[1])
    if args.out:
        try:
            with pathlib.Path(args.out).open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(merged)
        except OSError as exc:
            print(f"error: cannot write {args.out} ({exc.strerror or exc})", file=sys.stderr)
            return 2

    sys.stdout.write(merged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
