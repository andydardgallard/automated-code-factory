#!/usr/bin/env python3
"""
Contract self-test for the provider-failure stop path (zero LLM tokens, stdlib only).

The wild run 20261026-a65b9a6e: the task pinned `reviewer: kimi-code/k3.1-pro`, the provider
answered `429` (5-hour window exhausted), and the factory never called the router, never spent the
infrastructure budget and never stopped — the main agent did the review itself on another model and
`models_used` gained the invented role `orchestrator`. This test pins the stop path end to end:

  1. the deterministic router classifies the very line the provider produced: `429` →
     `category: PROVIDER_RATE`, `route: infrastructure`, `pattern_id: C`, and the shipped snapshot
     carries the infrastructure retry budget 3 the retry loop must respect (provider rows A/B/C/E
     all route to infrastructure);
  2. `SKILL.md` WIRES that mechanism into the flow:
     - the provider-failure node MS is fed by EVERY task-named role delegation (M, E, SC, F, PC,
       N, Q, S, CR, CR0, DG, ADV, DOC2, SA) and names the classify command, the errors.md record,
       the pipeline counter, the SAME named model on every retry and the STOP;
     - MS leads only to the owner decision VMS (hitl) and the terminal Y (auto FAILED);
     - VMS → RDM (`new matrix`, written to `state/task.yaml` + `state/task.json` and re-resolved
       with `model_matrix.py resolve`) or → Y (`stop`);
     - RDM is the SEMANTIC retry: it re-issues the same failed delegation at ITS ORIGIN node and
       draws no edge back into the graph; the retry coverage is DERIVED from the parsed
       provider-failure edges, so an added failing delegation X without a retry path fails here;
  3. the deterministic parse of the ORIGINAL task file comes FIRST and its normalized
     `state/task.json` feeds every later stage (node B), `state/task.yaml` being the verbatim copy;
  4. `model_attribution.py` reports an unknown `models_used` role (`orchestrator`) as exit 1 through
     its CLI — the run error the DEGRADED exit 3 used to hide.

Everything runs through the CLI in a throwaway tempdir (no real `~/.kimi-code`, no session).

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
ROUTER = SCRIPTS / "error_router.py"
ATTRIBUTION = SCRIPTS / "model_attribution.py"
PATTERNS = SCRIPTS.parent / "references" / "error-patterns.default.json"
SKILL = ".agents/skills/code-factory/SKILL.md"

# The provider line of the wild run, verbatim enough to be the real shape of a quota answer. It
# carries no `error:` prefix on purpose: the router is first-match-wins, and a leading `error: `
# would be claimed by the generic COMPILE_ERROR row 8 before the provider table is consulted.
PROVIDER_LINE = ("llm request failed: 429 Too Many Requests — rate limit exceeded for the 5-hour "
                 "window; retry after 02:14:09")

# Mermaid readers (the block is the only place the wiring can live).
MERMAID_RE = re.compile(r"```mermaid\r?\n(.*?)\r?\n```", re.S)
NODE_RE = re.compile(r"(?:^|[\s>|])([A-Za-z][A-Za-z0-9_]*)\s*([\[\{])")
CLOSING = {"[": "]", "{": "}"}
EDGE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*-->\s*(?:\|([^|\n]*)\|)?\s*([A-Za-z0-9_]+)")

FAILURE_NODE = "MS"
# EVERY task-named role delegation must be able to reach the stop branch, not only the coder and
# the reviewer: analyzer (E, SC), planner (F, PC), coder/gui_expert (M), tester (N, Q, S),
# reviewer (CR, CR0), diagnostician (DG), advisor (ADV), documenter (DOC2), security auditor (SA).
FAILURE_FROM = ("M", "E", "SC", "F", "PC", "N", "Q", "S", "CR", "CR0", "DG", "ADV", "DOC2", "SA")
ROLE_FRAGMENTS = ("analyzer", "planner", "coder", "gui_expert", "tester", "reviewer",
                  "diagnostician", "advisor", "documenter", "security auditor")
# The mechanism the node must name (it is the whole point of the branch).
NODE_FRAGMENTS = (
    ("error_router.py classify", "the deterministic classification command"),
    ("PROVIDER_*", "the category family that routes to infrastructure"),
    ("model-unavailable-stop", "the rule that governs the branch"),
    ("SAME named model", "the retry uses the same model, never another"),
    ("retry_counters.infrastructure", "the budget counter kept in pipeline.yaml"),
    ("budget 3", "the infrastructure budget"),
    ("logs/errors.md", "where the classification is recorded"),
    ("EVERY delegation", "that the branch covers every task-named role, not a fixed node list"),
    ("FAILED", "the auto outcome"),
)
# The owner-approved matrix change (the third outcome the flow used to lack). The retry itself is
# SEMANTIC: RDM names the origin node it re-issues and draws NO edge back into the graph — a fan-out
# here made implementation nodes reachable from review verdict paths (broke `review-report-only`).
DECISION = "VMS"
RESOLVE_NODE = "RDM"
ALLOWED_TARGETS = (DECISION, "Y")
# Node B: the deterministic parse of the ORIGINAL task file comes BEFORE the LLM extraction.
TASK_NODE = "B"
TASK_NODE_FRAGMENTS = ("DETERMINISTIC PARSE FIRST", "task_parser.py parse",
                       "--task <the task file AS HANDED OVER>",
                       "--out .code-factory/state/task.json",
                       "task.json is the input of EVERY later stage",
                       "Extract FROM that normalized task.json",
                       "VERBATIM copy of the source task",
                       "state/task.yaml", "VERBATIM in hitl", "generically unreadable")

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(argv: list[str], cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=ENV, cwd=str(cwd) if cwd else None)


def text_of(res: subprocess.CompletedProcess[str]) -> str:
    return (res.stdout or "") + (res.stderr or "")


# ---------------------------------------------------------------------------------------------
# 1. The deterministic router classifies the provider line
# ---------------------------------------------------------------------------------------------
def check_router(root: pathlib.Path) -> list[str]:
    """429 → PROVIDER_RATE / infrastructure / pattern C, and the budget the loop must respect."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        log = work / "errors.md"
        log.write_text(PROVIDER_LINE + "\n", encoding="utf-8")
        res = run([sys.executable, str(root / ROUTER.relative_to(ROOT)), "classify",
                   "--log", str(log), "--repo", str(work)])
        if res.returncode != 0:
            problems.append(f"{ROUTER.name}: classify of a provider 429 must exit 0, got "
                            f"{res.returncode}: {text_of(res).strip()[:200]}")
            return problems
        fields = {}
        for line in (res.stdout or "").splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                fields[key.strip()] = value.strip()
        expected = {"category": "PROVIDER_RATE", "route": "infrastructure", "pattern_id": "C"}
        for key, value in expected.items():
            if fields.get(key) != value:
                problems.append(f"{ROUTER.name}: a provider 429 must classify as {key}={value!r}, "
                                f"got {fields.get(key)!r} ({text_of(res).strip()[:200]})")
        if "429" not in fields.get("matched", ""):
            problems.append(f"{ROUTER.name}: the matched pattern must be the 429 one, got "
                            f"{fields.get('matched')!r}")

    snapshot = root / PATTERNS.relative_to(ROOT)
    if not snapshot.is_file():
        problems.append(f"{PATTERNS.relative_to(ROOT)}: the shipped pattern snapshot is missing")
        return problems
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    budget = (data.get("retry_budgets") or {}).get("infrastructure")
    if budget != 3:
        problems.append(f"{PATTERNS.relative_to(ROOT)}: the infrastructure retry budget must be 3 "
                        f"(the loop the stop rule allows), got {budget!r}")
    routes = {entry["id"]: entry["route"] for entry in data.get("provider_patterns", [])
              if entry["category"].startswith("PROVIDER_")}
    for pattern_id in ("A", "B", "C", "D", "E", "F"):
        if routes.get(pattern_id) != "infrastructure":
            problems.append(f"{PATTERNS.relative_to(ROOT)}: provider row {pattern_id} must route to "
                            f"infrastructure, got {routes.get(pattern_id)!r}")
    return problems


# ---------------------------------------------------------------------------------------------
# 2. SKILL.md wires the branch
# ---------------------------------------------------------------------------------------------
def read_flow(root: pathlib.Path, problems: list[str]) -> tuple[str, int]:
    path = root / SKILL
    if not path.is_file():
        problems.append(f"{SKILL}:1: file is missing — the stop branch cannot be checked")
        return "", 0
    text = path.read_text(encoding="utf-8")
    match = MERMAID_RE.search(text)
    if match is None:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the stop branch cannot be wired into it")
        return "", 0
    return match.group(1), text.count("\n", 0, match.start(1)) + 1


def flow_graph(block: str, first: int) -> tuple[dict[str, tuple[int, str]],
                                               list[tuple[int, str, str | None, str]]]:
    """(nodes, edges) of a mermaid block: `ID[body]` work nodes and `ID{body}` decision nodes."""
    nodes: dict[str, tuple[int, str]] = {}
    edges: list[tuple[int, str, str | None, str]] = []
    for offset, line in enumerate(block.splitlines()):
        number = first + offset
        match = EDGE_RE.match(line)
        if match:
            edges.append((number, match.group(1),
                          match.group(2).strip() if match.group(2) else None, match.group(3)))
        for found in NODE_RE.finditer(line):
            start = line.index(found.group(2), found.end(1) - 1)
            closer = CLOSING[found.group(2)]
            depth = 0
            body = ""
            for k in range(start, len(line)):
                if line[k] == found.group(2):
                    depth += 1
                    continue
                if line[k] == closer:
                    depth -= 1
                    if depth == 0:
                        body = line[start + 1:k]
                        break
            nodes.setdefault(found.group(1), (number, body))
    return nodes, edges


def check_skill_wiring(root: pathlib.Path) -> list[str]:
    """The provider-failure branch exists, EVERY task-named delegation reaches it, and it stops."""
    problems: list[str] = []
    block, first = read_flow(root, problems)
    if not block:
        return problems
    nodes, edges = flow_graph(block, first)

    if FAILURE_NODE not in nodes:
        problems.append(f"{SKILL}:{first}: no provider-failure node `{FAILURE_NODE}[...]` — a "
                        "provider refusal of a task-named model has no branch to land in, so the "
                        "run degrades instead of stopping")
        return problems
    number, body = nodes[FAILURE_NODE]
    for fragment, what in NODE_FRAGMENTS:
        if fragment not in body:
            problems.append(f"{SKILL}:{number}: node {FAILURE_NODE} must name {what} "
                            f"({fragment!r}) — the stop branch has to be runnable, not prose")
    for role in ROLE_FRAGMENTS:
        if role not in body:
            problems.append(f"{SKILL}:{number}: node {FAILURE_NODE} must name the role {role!r} — "
                            "the branch covers EVERY task-named role delegation, not only M/CR/CR0")
    for source in FAILURE_FROM:
        if not any(src == source and target == FAILURE_NODE for _line, src, _label, target in edges):
            problems.append(f"{SKILL}:{first}: no edge {source} -> {FAILURE_NODE} — the {source} "
                            "delegation can hit an unavailable named model too; every task-named "
                            "role must reach the stop branch")
    outgoing = [(line, label, target) for line, src, label, target in edges if src == FAILURE_NODE]
    if not outgoing:
        problems.append(f"{SKILL}:{number}: node {FAILURE_NODE} has no outgoing edge — it must stop, "
                        "never fall through to the work it could not delegate")
        return problems
    for _line, _label, target in outgoing:
        if target not in ALLOWED_TARGETS:
            problems.append(f"{SKILL}:{outgoing[0][0]}: node {FAILURE_NODE} routes to {target} — "
                            "the only legal destinations are the owner decision (VMS) and the "
                            "terminal finish (Y); no implementation or delivery node may follow a "
                            "provider refusal of a task-named model")
    for target, word in ((DECISION, "hitl"), ("Y", "auto")):
        if not any(destination == target and label and word in label.lower()
                   for _line, label, destination in outgoing):
            problems.append(f"{SKILL}:{outgoing[0][0]}: node {FAILURE_NODE} needs a `{word}` edge to "
                            f"{target} (hitl asks the owner, auto ends FAILED)")

    # The owner-approved matrix change: new matrix -> re-resolve -> retry; decline -> stop.
    decided = [(line, label, target) for line, src, label, target in edges if src == DECISION]
    if DECISION not in nodes:
        problems.append(f"{SKILL}:{number}: no owner-decision node `{DECISION}` — hitl must offer "
                        "an authorized matrix change, not only a stop")
        return problems
    if not any(target == RESOLVE_NODE and label and "new matrix" in label.lower()
               for _line, label, target in decided):
        problems.append(f"{SKILL}:{decided[0][0] if decided else nodes[DECISION][0]}: node "
                        f"{DECISION} needs a `new matrix` edge to {RESOLVE_NODE} — the owner may "
                        "authorize a different model and the run continues on it")
    if not any(target == "Y" and label and "stop" in label.lower()
               for _line, label, target in decided):
        problems.append(f"{SKILL}:{decided[0][0] if decided else nodes[DECISION][0]}: node "
                        f"{DECISION} needs a `stop` edge to Y — a declined matrix change ends the run")
    if RESOLVE_NODE not in nodes:
        problems.append(f"{SKILL}:{number}: no re-resolve node `{RESOLVE_NODE}` — an authorized "
                        "matrix must be written and resolved before the retry")
        return problems
    resolve_number, resolve_body = nodes[RESOLVE_NODE]
    for fragment, what in (("state/task.yaml", "where the new matrix is written"),
                           ("state/task.json", "the normalized copy kept in sync"),
                           ("model_matrix.py resolve", "the deterministic re-resolution"),
                           ("retry", "the retry of the failed delegation"),
                           ("failed delegation", "which delegation is retried"),
                           ("origin node", "the node the retry is re-issued at")):
        if fragment not in resolve_body:
            problems.append(f"{SKILL}:{resolve_number}: node {RESOLVE_NODE} must name {what} "
                            f"({fragment!r})")
    # The retry is SEMANTIC: no edge back into the graph (a fan-out here broke review-report-only).
    for line, src, _label, target in edges:
        if src == RESOLVE_NODE:
            problems.append(f"{SKILL}:{line}: node {RESOLVE_NODE} routes to {target} — the retry "
                            "must stay semantic: an edge from here makes an implementation node "
                            "reachable from a review verdict path")
    # Coverage DERIVED from the parsed flow: every node with a provider-failure edge into MS is an
    # origin of a retryable delegation and must be named by RDM — no second hand-written list.
    origins = {src for _line, src, label, target in edges
               if target == FAILURE_NODE and label and "provider error" in label.lower()}
    for origin in sorted(origins):
        if not re.search(rf"\b{re.escape(origin)}\b", resolve_body):
            problems.append(f"{SKILL}:{resolve_number}: the retry mechanism does not cover "
                            f"{origin!r} — {origin} has a provider-failure edge into "
                            f"{FAILURE_NODE}, so an owner-authorized matrix change must be able to "
                            "re-issue that delegation at its origin node")
    return problems


# ---------------------------------------------------------------------------------------------
# 2b. The deterministic task parse comes BEFORE the extraction (the statement is never re-typed)
# ---------------------------------------------------------------------------------------------
def check_task_parse_first(root: pathlib.Path) -> list[str]:
    """Node B parses the ORIGINAL task file first; the extraction works FROM the normalized JSON.

    The finding this pins: `task.json` had no consumer — the flow parsed the task AFTER the LLM had
    already extracted it by hand, so `state/task.json` was written and read by nobody, and every
    part of the statement the owner wrote could be lost in the re-typing.
    """
    problems: list[str] = []
    block, first = read_flow(root, problems)
    if not block:
        return problems
    nodes, _edges = flow_graph(block, first)
    if TASK_NODE not in nodes:
        problems.append(f"{SKILL}:{first}: no task node `{TASK_NODE}[...]` in the flow")
        return problems
    line, body = nodes[TASK_NODE]
    for fragment in TASK_NODE_FRAGMENTS:
        if fragment not in body:
            problems.append(f"{SKILL}:{line}: node {TASK_NODE} must state {fragment!r} — the "
                            "deterministic parse of the original task file comes first, its "
                            "normalized task.json feeds every later stage, state/task.yaml is the "
                            "verbatim copy and a parse error is shown verbatim, never as "
                            "generically unreadable")
    parse_at = body.find("task_parser.py parse")
    extract_at = body.find("Extract FROM that normalized task.json")
    if parse_at != -1 and extract_at != -1 and parse_at > extract_at:
        problems.append(f"{SKILL}:{line}: node {TASK_NODE} extracts the task BEFORE it parses it — "
                        "the deterministic parse of the original file must come first")
    return problems


# ---------------------------------------------------------------------------------------------
# 3. An unknown role in models_used is exit 1 through the CLI
# ---------------------------------------------------------------------------------------------
def check_unknown_role(root: pathlib.Path) -> list[str]:
    """`models_used.orchestrator` exits 1 and names the role and the registry — never DEGRADED."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        repo = work / "repo"
        repo.mkdir()
        home = work / "home"                      # an empty wire root: nothing to confirm
        home.mkdir()
        pipeline = work / "pipeline.yaml"
        pipeline.write_text("\n".join([
            "run_id: 20261026-a65b9a6e", "phase: review", "status: ok", "models_used:",
            "  main: kimi-code/k3",
            "  reviewer: kimi-code/k3.1-pro",
            "  orchestrator: kimi-code/k3",
            "",
        ]), encoding="utf-8")
        out = work / "attribution.json"
        res = run([sys.executable, str(root / ATTRIBUTION.relative_to(ROOT)),
                   "--session", "auto", "--repo", str(repo), "--out", str(out),
                   "--pipeline", str(pipeline), "--home", str(home)])
        said = text_of(res)
        if res.returncode != 1:
            problems.append(f"{ATTRIBUTION.name}: an unknown models_used role must exit 1, got "
                            f"{res.returncode}: {said.strip()[:200]}")
            return problems
        for needle, what in (("orchestrator", "the offending role"),
                             ("model_matrix.ROLES", "the registry it is missing from"),
                             ("not a role of the factory", "the nature of the breach")):
            if needle not in said:
                problems.append(f"{ATTRIBUTION.name}: the run error must name {what} "
                                f"({needle!r}): {said.strip()[:200]}")
        final = (res.stdout or "").strip().splitlines()[-1] if (res.stdout or "").strip() else ""
        if not final.startswith("FAIL - "):
            problems.append(f"{ATTRIBUTION.name}: the final line must read FAIL, not DEGRADED "
                            f"(exit 3): {final!r}")
        if out.is_file():
            artifact = json.loads(out.read_text(encoding="utf-8"))
            if artifact.get("verdict") != "FAIL":
                problems.append(f"{ATTRIBUTION.name}: the artifact verdict must be FAIL, got "
                                f"{artifact.get('verdict')!r}")
            if artifact.get("flags", {}).get("unknown_roles") != ["orchestrator"]:
                problems.append(f"{ATTRIBUTION.name}: flags.unknown_roles must list the role, got "
                                f"{artifact.get('flags', {}).get('unknown_roles')!r}")
    return problems


SECTIONS = (
    ("1", "the router classifies a provider 429 as PROVIDER_RATE / infrastructure", check_router),
    ("2", "SKILL.md wires the provider-failure stop branch for EVERY task-named role",
     check_skill_wiring),
    ("3", "the deterministic task parse comes first and its task.json feeds the flow",
     check_task_parse_first),
    ("4", "an unknown models_used role is a run error (exit 1)", check_unknown_role),
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []
    print(f"provider-stop contracts under {ROOT}")
    for key, title, section in SECTIONS:
        found = section(ROOT)
        if found:
            failures.extend(found)
            print(f"not ok - {key}. {title}", file=sys.stderr)
            for item in found:
                print(f"FAIL - {item}", file=sys.stderr)
        else:
            print(f"ok   - {key}. {title}")

    if failures:
        print(f"FAIL - {len(failures)} contract violation(s)", file=sys.stderr)
        return 1

    print("PASS - a provider refusal of a task-named model goes through the deterministic router "
          "(429 -> PROVIDER_RATE / infrastructure / pattern C, budget 3), SKILL.md routes it from "
          "EVERY named-role delegation (M, E, SC, F, PC, N, Q, S, CR, CR0, DG, ADV, DOC2, SA) into "
          "the stop branch that retries the SAME model and then asks the owner (VMS), who may "
          "authorize a new matrix (written to state/task.yaml + task.json, re-resolved, retried) or "
          "stop (auto ends FAILED); the deterministic parse of the ORIGINAL task file feeds the "
          "flow from state/task.json; and an unknown models_used role is a run error (exit 1) "
          "naming the role and the registry — never a DEGRADED exit 3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
