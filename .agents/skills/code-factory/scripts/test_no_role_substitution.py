#!/usr/bin/env python3
"""
Text-contract self-test for the `model-unavailable-stop` rule (zero LLM tokens, stdlib only).

WHY THIS EXISTS

On run 20261026-a65b9a6e the task pinned the reviewer model, the provider answered 429 (a 5-hour
window exhausted), and nobody was stopped: the main agent performed the review itself on another
model, invented the role `orchestrator` in `models_used`, and `model_attribution.py` filed the
whole thing as DEGRADED ("no wire for this role"). The owner stopped the run. The promise that was
missing — an unavailable TASK-NAMED model is a STOP, never a substitution, and the main agent never
performs the role itself — lives in PROSE, so nothing in the suite would notice it drifting away.

This test pins it:
  A. the canonical rule exists in `references/factory-rules.md` with exactly the four declared
     carriers, and its block still states the semantics (a STOP, both modes, no substitution, the
     router, the budget, the unknown-role error);
  B. every carrier quotes that block BYTE-IDENTICALLY exactly once;
  C. the SKILL.md flow carries the branch for EVERY named-role delegation:
     - the provider-failure node MS is fed by the coder/gui_expert M, the analyzer E and SC, the
       planner F and PC, the tester N, Q and S, the reviewer CR and CR0, the diagnostician DG, the
       advisor ADV, the documenter DOC2 and the security auditor SA — each with a
       `provider error at delegation` edge — and its body names every role family as well as the
       router, the budget, the errors.md record, the SAME named model and the STOP;
     - MS leaves ONLY to the owner decision VMS (hitl, naming AskUserQuestion) and to the terminal
       Y (auto FAILED) — never to an implementation, delivery or review node;
     - VMS offers exactly two outcomes: `new matrix` → RDM and `stop` → Y;
     - RDM is the MATRIX-CHANGE CONTINUATION: it writes the owner's matrix into `state/task.yaml`
       and `state/task.json`, re-resolves it with `model_matrix.py resolve`, and RE-ISSUES the same
       failed delegation at its OWN origin node — a SEMANTIC retry, so RDM draws NO edge back into
       the graph (a fan-out there made implementation nodes reachable from review verdict paths and
       broke `review-report-only`);
     - the retry coverage is DERIVED from the parsed provider-failure edges: every node that can
       reach MS must be named by RDM, so an added failing delegation cannot silently lose its retry
       path — there is no second hand-written list;
  D. no carrier contains an unnegated sentence handing a named role's work to the main agent.

Invariant: every check reads the REAL shipped file and reports `<file>:<line>: <what is missing>`;
the nine negative probes at the bottom break the contract on a throwaway copy the way a careless
edit would (drop the block from a carrier, re-point MS at a delivery node, delete MS, unhook the
analyst delegation, add an uncovered failing delegation X, drop the `new matrix` outcome, draw the
retry as a fan-out edge, stop naming the origin node, hand a role's work to the main agent) and the
checker must FAIL on each of them, so none of the pins is a tautology.

Exit code 0 = every contract holds and every probe is caught, 1 = a contract or a probe failed.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys
import tempfile

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent

RULEBOOK = ".agents/skills/code-factory/references/factory-rules.md"
SKILL = ".agents/skills/code-factory/SKILL.md"
PROVIDERS = ".agents/skills/code-factory/references/providers.md"
CODE_REVIEW = ".agents/skills/code-factory/references/code-review.md"
AGENT = ".agents/agents/code-factory.md"

RULE = "model-unavailable-stop"
# The documents that must quote the rule verbatim — the carrier list the rulebook declares.
CARRIERS = (AGENT, SKILL, CODE_REVIEW, PROVIDERS)
# The rulebook declares them in this order; the set is what matters, the order is reported.
DECLARED = (AGENT, SKILL, CODE_REVIEW, PROVIDERS)

# What the canonical block must still SAY, whatever else it says (`check_factory_rules.py` pins
# three of these markers too; here the reader-facing semantics are pinned as well).
FRAGMENTS = ("STOPS", "hitl", "auto", "NEVER performs", "NEVER substitutes", "AskUserQuestion",
             "state/task.yaml", "FAILED", "error_router.py", "PROVIDER_*", "budget 3",
             "logs/errors.md", "pipeline.yaml", "SAME named model", "`ROLES`",
             "scripts/model_matrix.py", "exits 1 naming the role", "never DEGRADED")

# The mermaid block and the two things read out of it: node definitions and edges.
MERMAID_RE = re.compile(r"```mermaid\r?\n(.*?)\r?\n```", re.S)
NODE_RE = re.compile(r"(?:^|[\s>|])([A-Za-z][A-Za-z0-9_]*)\s*([\[\{])")
CLOSING = {"[": "]", "{": "}"}
EDGE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*-->\s*(?:\|([^|\n]*)\|)?\s*([A-Za-z0-9_]+)")

# The branch: who may reach it, and where it may lead. The rule covers EVERY task-named role, so
# every delegation node of the flow must be able to reach the stop branch — not only the coder and
# the reviewer. This tuple is only the MINIMUM coverage the flow must draw; the retry coverage is
# derived from the parsed edges, never from a second list.
FAILURE_NODE = "MS"
FAILURE_FROM = ("M", "E", "SC", "F", "PC", "N", "Q", "S", "CR", "CR0", "DG", "ADV", "DOC2", "SA")
# The role families the branch must name in words, so the coverage is readable and not only drawn.
ROLE_FRAGMENTS = ("analyzer", "planner", "coder", "gui_expert", "tester", "reviewer",
                  "diagnostician", "advisor", "documenter", "security auditor")
# The ONLY legal destinations of the provider-failure node: the owner's decision (hitl) and the
# terminal finish node (auto FAILED). No implementation/delivery/review node may follow a provider
# refusal of a task-named model.
ALLOWED_TARGETS = ("VMS", "Y")
# The owner-approved matrix change: ask, re-resolve, retry — the third outcome the flow used to
# lack (it only offered "fix code / revise plan / stop"). The retry itself is SEMANTIC (RDM names
# the origin node it re-issues) and draws NO edge back into the graph: a fan-out from here made
# implementation nodes reachable from review verdict paths and broke `review-report-only`.
DECISION = "VMS"
RESOLVE_NODE = "RDM"
# The wording each incoming edge carries (the failure has to be recognized as such).
INCOMING_LABEL = "provider error"

# The node body must name the mechanism, not merely exist.
NODE_FRAGMENTS = ("error_router.py", "PROVIDER_*", "model-unavailable-stop", "SAME named model",
                  "retry_counters.infrastructure", "logs/errors.md", "FAILED",
                  "EVERY delegation", "not limited to M, CR and CR0")
# The two labels of the branch must state the mechanism each hop carries (the owner question, and
# the automatic FAILED), so an edit that keeps the arrows but drops the semantics is caught.
HITL_LABEL_FRAGMENTS = ("AskUserQuestion", "owner")
# An unnegated handover: "the main agent performs the review itself" and friends.
HANDOVER_RE = re.compile(
    r"main agent\b[^.\n]{0,80}?\b(performs|does|runs|takes over|executes|reviews)\b"
    r"[^.\n]{0,60}\b(review|reviewer|role|work|itself)\b", re.I)
NEGATION_RE = re.compile(r"\b(?:never|not|no|forbidden|instead of|rather than|nor)\b", re.I)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def markers(rule_id: str = RULE) -> tuple[str, str]:
    return (f"<!-- factory-rule: {rule_id} begin -->",
            f"<!-- factory-rule: {rule_id} end -->")


def extract_block(text: str, rule_id: str = RULE) -> str | None:
    """The inner text of the single marked block of `rule_id`; None when absent/duplicated/empty."""
    begin, end = markers(rule_id)
    if text.count(begin) != 1 or text.count(end) != 1:
        return None
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    if stop <= start:
        return None
    return text[start:stop].strip() or None


def declared_carriers(book: str) -> list[str]:
    """The `carriers:` line of the `## model-unavailable-stop` section, in declaration order."""
    section: list[str] = []
    inside = False
    for line in book.splitlines():
        if re.match(rf"^##\s+{re.escape(RULE)}\s*$", line):
            inside = True
            continue
        if inside:
            if re.match(r"^##\s+\S+", line):
                break
            section.append(line)
    for line in section:
        match = re.match(r"^carriers:\s*(.+?)\s*$", line)
        if match:
            return [part.strip() for part in match.group(1).split(";") if part.strip()]
    return []


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, max(0, index)) + 1


class Doc:
    """One shipped file, with the mermaid helpers the flow contract needs."""

    def __init__(self, rel: str, text: str):
        self.rel = rel
        self.text = text
        self.lines = text.splitlines()

    @classmethod
    def load(cls, root: pathlib.Path, rel: str, problems: list[str]) -> "Doc":
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}:1: file is missing — the contract cannot be pinned")
            return cls(rel, "")
        return cls(rel, path.read_text(encoding="utf-8"))

    def count(self, needle: str) -> int:
        return self.text.count(needle)

    def mermaid(self) -> str:
        """The flowchart block body, or "" when the file carries none."""
        match = MERMAID_RE.search(self.text)
        return match.group(1) if match else ""

    def block_first_line(self) -> int:
        """The 1-based line number of the mermaid block's first body line."""
        match = MERMAID_RE.search(self.text)
        return line_of(self.text, match.start(1)) if match else 0

    def nodes(self) -> dict[str, tuple[int, str]]:
        """`{node id: (1-based line, body)}` of the mermaid block (first definition wins).

        Both shapes are read: the rectangle `ID[body]` (the work nodes) and the decision
        `ID{body}` (the owner's choice) — the matrix-change branch lives in a decision node.
        """
        found: dict[str, tuple[int, str]] = {}
        first = self.block_first_line()
        for offset, line in enumerate(self.mermaid().splitlines()):
            for match in NODE_RE.finditer(line):
                start = line.index(match.group(2), match.end(1) - 1)
                closer = CLOSING[match.group(2)]
                depth = 0
                body = ""
                for k in range(start, len(line)):
                    if line[k] == match.group(2):
                        depth += 1
                        continue
                    if line[k] == closer:
                        depth -= 1
                        if depth == 0:
                            body = line[start + 1:k]
                            break
                found.setdefault(match.group(1), (first + offset, body))
        return found

    def edges(self) -> list[tuple[int, str, str | None, str]]:
        """`[(1-based line, source, label, target)]` of every edge of the mermaid block."""
        first = self.block_first_line()
        out: list[tuple[int, str, str | None, str]] = []
        for offset, line in enumerate(self.mermaid().splitlines()):
            match = EDGE_RE.match(line)
            if match:
                label = match.group(2).strip() if match.group(2) else None
                out.append((first + offset, match.group(1), label, match.group(3)))
        return out


def check_rulebook(root: pathlib.Path) -> list[str]:
    """A. The rule exists, declares exactly the four carriers, and keeps its semantics."""
    problems: list[str] = []
    book = Doc.load(root, RULEBOOK, problems)
    block = extract_block(book.text)
    if block is None:
        problems.append(f"{RULEBOOK}: the rule '{RULE}' is missing — the canonical stop rule must be "
                        "declared with one marked block (a named model that is unavailable stops "
                        "the run; the main agent never substitutes it and never performs its work)")
        return problems
    declared = declared_carriers(book.text)
    if set(declared) != set(DECLARED):
        problems.append(f"{RULEBOOK}: rule '{RULE}' must declare the carriers "
                        f"{', '.join(DECLARED)} — declared: {', '.join(declared) or 'none'}")
    for fragment in FRAGMENTS:
        if fragment not in block:
            problems.append(f"{RULEBOOK}: the canonical block of '{RULE}' lost {fragment!r} — the "
                            "stop semantics must not be watered down")
    return problems


def check_carriers(root: pathlib.Path) -> list[str]:
    """B. Every carrier quotes the block byte-identically, exactly once."""
    problems: list[str] = []
    book = Doc.load(root, RULEBOOK, problems)
    block = extract_block(book.text)
    if block is None:
        return problems or [f"{RULEBOOK}: the rule '{RULE}' is missing — no block to quote"]
    for rel in CARRIERS:
        carrier = Doc.load(root, rel, problems)
        found = extract_block(carrier.text)
        begin, end = markers()
        if found is None:
            count = carrier.count(begin) + carrier.count(end)
            why = "duplicated" if count else "missing"
            problems.append(f"{rel}: the block of '{RULE}' is {why} — every declared carrier must "
                            "quote the canonical wording verbatim exactly once")
        elif found != block:
            problems.append(f"{rel}: the block of '{RULE}' differs from the {RULEBOOK} canonical "
                            "wording")
        if RULE not in carrier.text.replace(f"factory-rule: {RULE}", ""):
            problems.append(f"{rel}: the prose must name the rule '{RULE}' next to the quote")
    return problems


def check_flow(root: pathlib.Path) -> list[str]:
    """C. The SKILL.md flow carries the stop branch and nothing but the two stop destinations."""
    problems: list[str] = []
    skill = Doc.load(root, SKILL, problems)
    block = skill.mermaid()
    if not block:
        problems.append(f"{SKILL}:1: no ```mermaid flow — the stop branch cannot be wired into it")
        return problems
    nodes = skill.nodes()
    if FAILURE_NODE not in nodes:
        problems.append(f"{SKILL}:1: no provider-failure node `{FAILURE_NODE}[...]` — a named model "
                        "that cannot be reached must reach a branch of its own")
        return problems
    node_line, body = nodes[FAILURE_NODE]
    for fragment in NODE_FRAGMENTS:
        if fragment not in body:
            problems.append(f"{SKILL}:{node_line}: node {FAILURE_NODE} must name {fragment!r} — the "
                            "stop branch has to classify, budget, retry the SAME model and stop")
    for role in ROLE_FRAGMENTS:
        if role not in body:
            problems.append(f"{SKILL}:{node_line}: node {FAILURE_NODE} must name the role {role!r} — "
                            "the rule covers EVERY task-named role delegation, not only M/CR/CR0")

    edges = skill.edges()
    for source in FAILURE_FROM:
        routes = [(line, label) for line, src, label, target in edges
                  if src == source and target == FAILURE_NODE]
        if not routes:
            problems.append(f"{SKILL}:1: node {source} has no edge to {FAILURE_NODE} — the "
                            f"delegation of {source} can fail on the named model too, and every "
                            "task-named role must reach the stop branch")
            continue
        if not any(label and INCOMING_LABEL in label.lower() for _line, label in routes):
            problems.append(f"{SKILL}:{routes[0][0]}: the {source} -> {FAILURE_NODE} edge must be "
                            "labelled as a provider failure of the named model")

    outgoing = [(line, label, target) for line, src, label, target in edges
                if src == FAILURE_NODE]
    if not outgoing:
        problems.append(f"{SKILL}:{node_line}: node {FAILURE_NODE} has no outgoing edge — the stop "
                        "branch must ask (hitl) or fail (auto); it must never fall through")
        return problems
    targets = {target for _line, _label, target in outgoing}
    for target in sorted(targets - set(ALLOWED_TARGETS)):
        problems.append(f"{SKILL}:{outgoing[0][0]}: node {FAILURE_NODE} routes to {target} — a "
                        "provider refusal of a task-named model may only ask the owner (VMS) or end "
                        "the run (Y); it never reaches an implementation, delivery or review node")
    for target, word in ((DECISION, "hitl"), ("Y", "auto")):
        if not any(target == destination and label and word in label.lower()
                   for _line, label, destination in outgoing):
            problems.append(f"{SKILL}:{outgoing[0][0]}: node {FAILURE_NODE} needs a `{word}` edge to "
                            f"{target} — the owner is asked in hitl, the run ends FAILED in auto")
    hitl_labels = " ".join(label for _line, label, target in outgoing
                           if target == DECISION and label)
    for fragment in HITL_LABEL_FRAGMENTS:
        if fragment.lower() not in hitl_labels.lower():
            problems.append(f"{SKILL}:{outgoing[0][0]}: the hitl edge of {FAILURE_NODE} must name "
                            f"{fragment!r} — the owner is asked for a decision, not merely told")

    # The owner-approved matrix change: ask, write the new matrix, re-resolve, retry.
    if DECISION not in nodes:
        problems.append(f"{SKILL}:{node_line}: no owner-decision node `{DECISION}` — hitl must let "
                        "the owner authorize a new matrix instead of only stopping")
        return problems
    decision_line, decision_body = nodes[DECISION]
    if "matrix" not in decision_body.lower():
        problems.append(f"{SKILL}:{decision_line}: node {DECISION} must be the decision about the "
                        "task's model matrix")
    decided = [(line, label, target) for line, src, label, target in edges if src == DECISION]
    for target, word in ((RESOLVE_NODE, "new matrix"), ("Y", "stops")):
        if not any(target == destination and label and word in label.lower()
                   for _line, label, destination in decided):
            problems.append(f"{SKILL}:{decided[0][0] if decided else decision_line}: node "
                            f"{DECISION} needs a `{word}` edge to {target} — the owner either "
                            "authorizes a new matrix (then the run continues on it) or declines "
                            "(then the run stops)")
    for target in sorted({destination for _line, _label, destination in decided} - {RESOLVE_NODE, "Y"}):
        problems.append(f"{SKILL}:{decided[0][0]}: node {DECISION} routes to {target} — only "
                        "`new matrix` (re-resolve and retry) and `stop` are legal outcomes")

    if RESOLVE_NODE not in nodes:
        problems.append(f"{SKILL}:{decision_line}: no re-resolve node `{RESOLVE_NODE}` — an "
                        "authorized matrix must be written down and resolved before the retry")
        return problems
    resolve_line, resolve_body = nodes[RESOLVE_NODE]
    for fragment, what in (("state/task.yaml", "the task file the new matrix is written to"),
                           ("state/task.json", "its normalized copy, kept in sync"),
                           ("model_matrix.py resolve", "the deterministic re-resolution"),
                           ("retry", "the retry of the failed delegation"),
                           ("failed delegation", "which delegation is retried"),
                           ("origin node", "the node the retry is re-issued at"),
                           ("SEMANTIC", "that the retry is not a graph edge")):
        if fragment not in resolve_body:
            problems.append(f"{SKILL}:{resolve_line}: node {RESOLVE_NODE} must name {what} "
                            f"({fragment!r})")

    # The retry is SEMANTIC: an owner-authorized matrix change re-issues the delegation at ITS OWN
    # origin node, so RDM draws no edge back into the graph. A fan-out here made implementation
    # nodes reachable from review/security-audit verdict paths and broke `review-report-only`.
    fanout = [(line, target) for line, src, _label, target in edges if src == RESOLVE_NODE]
    for line, target in fanout:
        problems.append(f"{SKILL}:{line}: node {RESOLVE_NODE} routes to {target} — the retry is "
                        "SEMANTIC and must not draw an edge back into the graph: a fan-out here "
                        "makes an implementation node reachable from a review verdict path and "
                        "breaks the report-only guarantee")

    # Coverage DERIVED from the parsed flow: every node that has a provider-failure edge into MS is
    # an origin of a retryable delegation, and RDM must name it. No second hand-written list — an
    # extra `X -->|provider error...| MS` edge is therefore caught by itself.
    origins = {src for _line, src, label, target in edges
               if target == FAILURE_NODE and label and INCOMING_LABEL in label.lower()}
    for origin in sorted(origins):
        if not re.search(rf"\b{re.escape(origin)}\b", resolve_body):
            problems.append(f"{SKILL}:{resolve_line}: the retry mechanism does not cover {origin!r} — "
                            f"{origin} has a provider-failure edge into {FAILURE_NODE}, so an "
                            "owner-authorized matrix change must be able to re-issue THAT "
                            "delegation at its origin node")
    return problems


def check_no_handover(root: pathlib.Path) -> list[str]:
    """D. No carrier hands a named role's work (or model) to the main agent."""
    problems: list[str] = []
    for rel in (RULEBOOK, SKILL, AGENT, CODE_REVIEW, PROVIDERS):
        doc = Doc.load(root, rel, problems)
        for match in HANDOVER_RE.finditer(doc.text):
            if NEGATION_RE.search(match.group(0)):
                continue
            problems.append(f"{rel}:{line_of(doc.text, match.start())}: the main agent must never "
                            f"{match.group(1)} a named role's work — the stop rule forbids it: "
                            f"{' '.join(match.group(0).split())[:90]!r}")
    return problems


SECTIONS = (
    ("A", "the canonical stop rule is declared with its four carriers", check_rulebook),
    ("B", "every carrier quotes the rule byte-identically", check_carriers),
    ("C", "the SKILL.md flow carries the stop branch", check_flow),
    ("D", "no carrier hands a named role's work to the main agent", check_no_handover),
)

FILES = (RULEBOOK, SKILL, AGENT, CODE_REVIEW, PROVIDERS)


def locate_root(start: pathlib.Path) -> pathlib.Path:
    """The repository root: the directory holding AGENTS.md and the code-factory SKILL.md."""
    for parent in (start, *start.parents):
        if (parent / "AGENTS.md").is_file() and (parent / SKILL).is_file():
            return parent
    return start.parents[2]


ROOT = locate_root(SCRIPT_DIR)


def make_tree(dst: pathlib.Path) -> pathlib.Path:
    """A throwaway root holding byte-identical copies of every file the contracts read."""
    if dst.exists():
        shutil.rmtree(dst)
    for rel in FILES:
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return dst


def probe(name: str, section, edits, expected: str) -> str:
    """Break the contract on a copy the way a careless edit would; the checker must catch it."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = make_tree(pathlib.Path(tmp) / "repo")
        for rel, old, new in edits:
            path = tree / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                raise AssertionError(f"probe {name!r}: {rel} does not contain {old!r} — the probe "
                                     "would be a no-op, not a vaccination")
            path.write_text(text.replace(old, new), encoding="utf-8")
        found = section(tree)
        if not found:
            raise AssertionError(f"probe {name!r}: the checker ACCEPTED the broken copy — the "
                                 "assertion is a tautology")
        report = "\n".join(found)
        if expected not in report:
            raise AssertionError(f"probe {name!r}: the checker failed for the wrong reason "
                                 f"(expected {expected!r}): {report}")
        return found[0]


PROBES = (
    ("B: the code-review carrier drops the rule block", check_carriers,
     ((CODE_REVIEW, f"<!-- factory-rule: {RULE} begin -->", "<!-- rule removed -->"),
      (CODE_REVIEW, f"<!-- factory-rule: {RULE} end -->", "<!-- rule removed -->")),
     "is missing"),
    ("C: the failure branch is re-pointed at the delivery node", check_flow,
     ((SKILL, "MS -->|auto: end FAILED with the explicit reason naming the model and the provider "
              "error| Y",
       "MS -->|auto: continue the run| W"),),
     "may only ask the owner"),
    ("C: the failure branch disappears from the flow", check_flow,
     ((SKILL, "MS[Named-model provider failure", "ZZ[Named-model provider failure"),),
     "no provider-failure node"),
    ("C: the analyst delegation can no longer reach the stop branch", check_flow,
     ((SKILL, "    E -->|provider error at delegation: the named model is unavailable| MS\n",
       ""),),
     "node E has no edge to MS"),
    ("C: the owner-approved matrix change is dropped", check_flow,
     ((SKILL, "VMS -->|new matrix authorized: write it into state/task.yaml and state/task.json, "
              "then re-resolve| RDM",
       "VMS -->|the owner decides| RDM"),),
     "needs a `new matrix` edge"),
    ("C: a new delegation starts failing without a retry path (X)", check_flow,
     ((SKILL, "    E -->|provider error at delegation: the named model is unavailable| MS\n",
       "    E -->|provider error at delegation: the named model is unavailable| MS\n"
       "    X -->|provider error at delegation: the named model is unavailable| MS\n"),),
     "does not cover 'X'"),
    ("C: the retry is drawn as a fan-out edge again", check_flow,
     ((SKILL, "    VMS -->|declines, or supplies no matrix",
       "    RDM --> M\n    VMS -->|declines, or supplies no matrix"),),
     "must not draw an edge back into the graph"),
    ("C: the retry stops naming its origin node", check_flow,
     ((SKILL, "at its own origin node", "somewhere"),),
     "'origin node'"),
    ("D: an unnegated handover sentence sneaks in", check_no_handover,
     ((PROVIDERS, "another model is never an infrastructure auto-fix.",
       "the main agent performs the review itself when the provider is unavailable."),),
     "must never"),
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    root = ROOT
    failures: list[str] = []
    print(f"no-role-substitution contracts under {root}")

    for key, title, section in SECTIONS:
        found = section(root)
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

    caught = 0
    for name, section, edits, expected in PROBES:
        try:
            first = probe(name, section, edits, expected)
        except AssertionError as exc:
            failures.append(f"probe {name}: {exc}")
            print(f"FAIL - probe {name}: {exc}", file=sys.stderr)
            continue
        caught += 1
        print(f"ok   - probe {name} -> {first}")

    if failures:
        print(f"FAIL - {len(failures)} contract violation(s)", file=sys.stderr)
        return 1

    print(f"PASS - the rule '{RULE}' is declared in {RULEBOOK} with its four carriers and quoted "
          f"byte-identically in every one of them; the SKILL.md flow routes a provider failure of "
          f"ANY task-named role delegation (analyzer, planner, coder/gui_expert, tester, reviewer, "
          f"diagnostician, advisor, documenter, security auditor — nodes M, E, SC, F, PC, N, Q, S, "
          f"CR, CR0, DG, ADV, DOC2, SA) into the stop branch, which only asks the owner (VMS), "
          f"re-resolves an owner-authorized matrix and retries the SAME role, or ends the run (auto "
          f"FAILED / owner declines); no carrier hands a named role's work to the main agent — and "
          f"all {caught} deliberately broken copies were caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
