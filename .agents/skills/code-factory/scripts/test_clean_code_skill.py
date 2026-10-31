#!/usr/bin/env python3
"""
Self-test for the clean-code deliverable of run 20261031-6dfd0921 (zero LLM tokens, stdlib only).

The run delivers five things that no other self-test reads, so a careless edit could delete any of
them while the rest of the suite stayed green:

  1. the two skills of the persistent skill base — `skill-base/skills/clean-code-discipline/SKILL.md`
     (the writing discipline) and `skill-base/skills/clean-code-metrics/SKILL.md` (the three metric
     gates) — each English only, with a frontmatter `name` that matches its directory and the
     contract sections in the contract order;
  2. the three measured gates (CRAP below 10, duplication rank 0.8 or above removed, surviving
     mutants killed and dead code deleted), with their thresholds, in the metrics skill;
  3. the safety warnings those sources force onto every consumer: the measuring tools install
     packages on their own initiative, a coverage command given as a shell string runs through a
     shell (only the argument-vector form is safe), and `scripts/get-uml-viewer` must never be
     executed;
  4. the registration in `skill-base/manifest.json`: both skills recorded with a non-empty source and
     a 64-hex content hash, the PINNED revision of each source, and all four sources of the metrics
     skill in its `sources` list;
  5. the wiring that makes the deliverable bite: the standing `## 2.2 Metric gates` section of the
     reviewer reference with its three numbered gates, the discipline reference in the two
     code-writing role prompts, and the metric-gate reference in the reviewer prompt.

`acceptance-verify` re-implements — without shelling out to a per-run, gitignored `task.yaml` — the
second and third `verify:` commands of the task: the gates' words must be present across the whole
skill base, and so must the install/shell warning — BOTH halves of it, the shell string and the
argument vector, and `acceptance-verify-cases` proves a one-sided body is rejected instead of
passing on the half that happens to be there.

Invariant: every failure line names the shipped file (and the line, where one exists), so a red run
says what to restore rather than that "something is wrong".

Exit code 0 = every check PASSed, 1 = at least one check FAILed.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
from typing import Callable

# scripts/ -> code-factory/ -> skills/ -> .agents/ -> repository root
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
AGENTS_SKILL = ".agents/skills/code-factory/SKILL.md"

SKILLS = pathlib.Path("skill-base/skills")
DISCIPLINE = "clean-code-discipline"
METRICS = "clean-code-metrics"
MANIFEST = pathlib.Path("skill-base/manifest.json")
CODE_REVIEW = pathlib.Path(".agents/skills/code-factory/references/code-review.md")
CODER = pathlib.Path(".agents/agents/sub-agents/coder.md")
GUI_EXPERT = pathlib.Path(".agents/agents/sub-agents/gui-expert.md")
CODE_REVIEWER = pathlib.Path(".agents/agents/sub-agents/code-reviewer.md")

# The revisions this deliverable is pinned to (the task names them; the manifest must agree).
PINNED = {
    DISCIPLINE: {
        "https://github.com/unclebob/ub-mode.git": "57a8bdd28e45ed41900ace0bafa2ff76dd9ed70f",
    },
    METRICS: {
        "https://github.com/unclebob/crapper.git": "6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d",
        "https://github.com/unclebob/dryer.git": "66ff6d21a42c04afcad89c78a80066176d1294b0",
        "https://github.com/unclebob/mutator.git": "a5a0cb803b66e0cdb8bf471b3b08af701d424a41",
        "https://github.com/unclebob/uml-viewer.git": "f65dafe93b3cb1b4e6bb02dbe41503ed05bd9ebf",
    },
}

# `## Overview` -> `## Key concepts` -> `## How to use` -> [## Business criteria] -> `## Constraints`.
BASE_SECTIONS = ("Overview", "Key concepts", "How to use", "Constraints")
METRICS_SECTIONS = ("Overview", "Key concepts", "How to use", "Business criteria", "Constraints")

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
HEADING_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# =============================================================================================
# Shared helpers
# =============================================================================================
def locate_root(start: pathlib.Path) -> pathlib.Path:
    """The repository root: the directory holding both `AGENTS.md` and the skill base."""
    for parent in (start, *start.parents):
        if (parent / "AGENTS.md").is_file() and (parent / SKILLS).is_dir():
            return parent
    return start.parents[3]


ROOT = locate_root(SCRIPT_DIR)


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the messages survive a legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def read(root: pathlib.Path, rel: pathlib.Path, errors: list[str]) -> str | None:
    """Text of a shipped file; a missing or non-UTF-8 file is an error, never an exception."""
    path = root / rel
    if not path.is_file():
        errors.append(f"{rel.as_posix()}: missing — the deliverable requires this file")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{rel.as_posix()}: not UTF-8 ({exc}) — every shipped artifact is UTF-8")
        return None


def frontmatter(text: str) -> dict[str, str] | None:
    """The `---` block as `key: value` pairs; None when absent or unterminated."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if line[:1] in (" ", "\t"):
            continue                                   # a continuation line of a long value
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return None                                        # unterminated block


def paragraphs(text: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


# =============================================================================================
# 1. The two skills: present, UTF-8, English only, frontmatter name, contract sections in order
# =============================================================================================
def check_skills(root: pathlib.Path) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []

    for name in (DISCIPLINE, METRICS):
        rel = SKILLS / name / "SKILL.md"
        text = read(root, rel, errors)
        if text is None:
            continue

        hit = CYRILLIC_RE.search(text)
        if hit:
            errors.append(f"{rel.as_posix()}:{line_of(text, hit.start())}: Cyrillic character "
                          f"{hit.group()!r} — every shipped artifact is English only")

        fields = frontmatter(text)
        if fields is None:
            errors.append(f"{rel.as_posix()}:1: no terminated `---` frontmatter block")
        else:
            if fields.get("name") != name:
                errors.append(f"{rel.as_posix()}:2: frontmatter name {fields.get('name')!r} does "
                              f"not match the directory {name!r}")
            if not fields.get("description", "").strip():
                errors.append(f"{rel.as_posix()}:2: the frontmatter description is empty")

        required = METRICS_SECTIONS if name == METRICS else BASE_SECTIONS
        headings = [match.group(1) for match in HEADING_RE.finditer(text)]
        found: list[int] = []
        for section in required:
            if section not in headings:
                errors.append(f"{rel.as_posix()}: missing required section `## {section}`")
            else:
                found.append(headings.index(section))
        if len(found) == len(required) and found != sorted(found):
            errors.append(f"{rel.as_posix()}: the sections are out of order ({', '.join(headings)}) "
                          f"— required order: {', '.join(required)}")

        notes.append(f"{rel.as_posix()}: {len(text)} chars, sections {', '.join(headings)}")

    return notes, errors


# =============================================================================================
# 2. The three metric gates with their thresholds, in the metrics skill
# =============================================================================================
GATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("the first gate's metric CRAP", re.compile(r"CRAP")),
    ("the CRAP threshold `CRAP < 10`", re.compile(r"CRAP\s*<\s*10")),
    ("the second gate's metric duplication", re.compile(r"duplication", re.I)),
    ("the duplication threshold `0.8 or above`", re.compile(r"0\.8\s+or\s+above")),
    ("the duplication rank `>= 0.8`", re.compile(r"rank\s*>=\s*0\.8")),
    ("the third gate's metric mutant", re.compile(r"mutant", re.I)),
    ("killing the surviving mutants", re.compile(r"kill\w*\s+(?:the|each)\s+surviving\s+mutant",
                                                 re.I)),
    ("dead code", re.compile(r"dead\s+code", re.I)),
    ("deleting the dead code", re.compile(r"(?:delete|remove|deleted|removed)s?\s+(?:the\s+)?dead"
                                          r"\s+code", re.I)),
)


def check_metric_gates(root: pathlib.Path) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    rel = SKILLS / METRICS / "SKILL.md"
    text = read(root, rel, errors)
    if text is None:
        return notes, errors

    for description, pattern in GATE_PATTERNS:
        if not pattern.search(text):
            errors.append(f"{rel.as_posix()}: the metrics skill no longer states {description}")
    notes.append(f"{rel.as_posix()}: {len(GATE_PATTERNS)} gate statements checked")
    return notes, errors


# =============================================================================================
# 3. The safety warnings the sources force onto every consumer
# =============================================================================================
INSTALL_PARAGRAPH_RE = re.compile(r"on their own initiative|without asking", re.I)
UNATTENDED_RE = re.compile(r"must not happen unattended", re.I)
# The prohibition must forbid EXECUTION of the diagram installer, not merely mention "never"
# somewhere in the same neighbourhood: the subject (installer/viewer) and the prohibition must
# belong to the same sentence.
PROHIBIT_INSTALLER_RE = re.compile(r"(?:installer|viewer|get-uml-viewer)\b[^.]{0,160}?"
                                   r"\b(?:must\s+not|must\s+never|never|do\s+not)\s+(?:be\s+)?"
                                   r"(?:executed|run)\b", re.I)


def check_tool_safety(root: pathlib.Path) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    rel = SKILLS / METRICS / "SKILL.md"
    text = read(root, rel, errors)
    if text is None:
        return notes, errors

    blocks = paragraphs(text)

    if not any("install" in block.lower() and INSTALL_PARAGRAPH_RE.search(block)
               for block in blocks):
        errors.append(f"{rel.as_posix()}: no warning that the measuring tools can install packages "
                      "on their own initiative")
    if not UNATTENDED_RE.search(text):
        errors.append(f"{rel.as_posix()}: the install warning no longer forbids it unattended "
                      "(`must not happen unattended`)")

    shell_block = [block for block in blocks
                   if re.search(r"shell", block, re.I)
                   and re.search(r"argument\s+vector", block, re.I)
                   and re.search(r"\bsafe\b", block, re.I)]
    if not shell_block:
        errors.append(f"{rel.as_posix()}: no single warning contrasts a coverage command given as "
                      "a shell string with the safe argument-vector form")
    elif not re.search(r"shell", text, re.I) or not re.search(r"argument\s+vector", text, re.I):
        errors.append(f"{rel.as_posix()}: the shell-string / argument-vector warning is incomplete")

    if not re.search(r"get-uml-viewer", text):
        errors.append(f"{rel.as_posix()}: no warning that `scripts/get-uml-viewer` must never be "
                      "executed")
    elif not PROHIBIT_INSTALLER_RE.search(text):
        errors.append(f"{rel.as_posix()}: `scripts/get-uml-viewer` is named without the prohibition "
                      "— the installer must be shown as something never to run")

    notes.append(f"{rel.as_posix()}: install, shell-string and viewer warnings all present")
    return notes, errors


# =============================================================================================
# 4. The manifest registration: source, 64-hex content hash, pinned revisions, four sources
# =============================================================================================
def check_entry_shape(name: str, entry: dict, primary: tuple[str, str]) -> list[str]:
    """The top-level fields of one registered skill: name, source, digest and pin."""
    primary_url, primary_rev = primary
    errors: list[str] = []
    if entry.get("name") != name:
        errors.append(f"{MANIFEST.as_posix()}: entry {name!r} declares name {entry.get('name')!r}")
    source = entry.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(f"{MANIFEST.as_posix()}: {name!r} has no source")
    if source != primary_url:
        errors.append(f"{MANIFEST.as_posix()}: {name!r} source {source!r} is not the pinned "
                      f"primary source {primary_url!r}")
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        errors.append(f"{MANIFEST.as_posix()}: {name!r} has no 64-hex content hash (got {sha!r})")
    revision = entry.get("resolved_revision")
    if revision != primary_rev:
        errors.append(f"{MANIFEST.as_posix()}: {name!r} resolved_revision {revision!r} is not the "
                      f"pinned revision {primary_rev}")
    return errors


def list_problems(name: str, sources, expected: int) -> list[str]:
    """The `sources` value itself: a list of exactly `expected` entries."""
    if not isinstance(sources, list) or len(sources) != expected:
        count = len(sources) if isinstance(sources, list) else sources
        return [f"{MANIFEST.as_posix()}: {name!r} must carry all {expected} sources in its "
                f"`sources` list (got {count!r})"]
    return []


def indexed_sources(name: str, sources: list) -> tuple[dict[str, dict], list[str]]:
    """The `sources` items keyed by their URL; an item without a usable URL is an error."""
    errors: list[str] = []
    seen: dict[str, dict] = {}
    for item in sources:
        url = item.get("source") if isinstance(item, dict) else None
        if not isinstance(url, str) or not url.strip():
            errors.append(f"{MANIFEST.as_posix()}: {name!r} has a source entry without a URL")
            continue
        seen[url] = item
    return seen, errors


def check_source_item(name: str, url: str, item: dict, revision: str) -> list[str]:
    """One pinned source: it must record its pinned revision and a 64-hex content hash."""
    errors: list[str] = []
    if item.get("resolved_revision") != revision:
        errors.append(f"{MANIFEST.as_posix()}: {name!r} source {url} resolved_revision "
                      f"{item.get('resolved_revision')!r} is not the pinned {revision}")
    if not isinstance(item.get("sha256"), str) or not SHA256_RE.match(item["sha256"]):
        errors.append(f"{MANIFEST.as_posix()}: {name!r} source {url} has no 64-hex content hash")
    return errors


def check_store_sources(name: str, sources, pinned: dict[str, str]) -> list[str]:
    """The `sources` list of a multi-source skill: every pinned source with its digest."""
    problems = list_problems(name, sources, len(pinned))
    if problems:
        return problems
    seen, errors = indexed_sources(name, sources)
    for url, revision in pinned.items():
        item = seen.get(url)
        if item is None:
            errors.append(f"{MANIFEST.as_posix()}: {name!r} does not list its source {url}")
            continue
        errors.extend(check_source_item(name, url, item, revision))
    return errors


def check_manifest(root: pathlib.Path) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    text = read(root, MANIFEST, errors)
    if text is None:
        return notes, errors
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{MANIFEST.as_posix()}:{exc.lineno}: not valid JSON ({exc.msg})")
        return notes, errors

    skills = manifest.get("skills")
    if not isinstance(skills, dict):
        errors.append(f"{MANIFEST.as_posix()}: no `skills` object")
        return notes, errors

    for name, pinned in PINNED.items():
        entry = skills.get(name)
        if not isinstance(entry, dict):
            errors.append(f"{MANIFEST.as_posix()}: the skill {name!r} is not registered")
            continue
        primary_url, primary_rev = next(iter(pinned.items()))
        errors.extend(check_entry_shape(name, entry, (primary_url, primary_rev)))
        if len(pinned) == 1:                       # a single-source skill carries no source list
            notes.append(f"{name}: {primary_url} @ {primary_rev}")
            continue
        errors.extend(check_store_sources(name, entry.get("sources"), pinned))
        notes.append(f"{name}: {len(pinned)} sources, primary {primary_url} @ {primary_rev}")
    return notes, errors


# =============================================================================================
# 4b. Focused cases of the manifest check: a malformed entry and a malformed source list
# =============================================================================================
def fixture_manifest(overrides: dict[str, dict]) -> dict:
    """A manifest whose registered skills are exactly the pinned ones, with entry overrides."""
    skills: dict[str, dict] = {}
    for name, pinned in PINNED.items():
        primary_url, primary_rev = next(iter(pinned.items()))
        entry: dict = {"name": name, "source": primary_url, "sha256": "a" * 64,
                       "resolved_revision": primary_rev}
        if len(pinned) > 1:
            entry["sources"] = [{"source": url, "sha256": "b" * 64, "resolved_revision": rev}
                                for url, rev in pinned.items()]
        skills[name] = entry
    for name, override in overrides.items():
        skills.setdefault(name, {}).update(override)
    return {"skills": skills}


def seed_manifest(root: pathlib.Path, manifest: dict) -> None:
    path = root / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def expect_error(root: pathlib.Path, fragment: str) -> str:
    """The error lines `check_manifest` reports; a silent pass is itself a failure."""
    _notes, errors = check_manifest(root)
    if not any(fragment in error for error in errors):
        raise AssertionError(f"check_manifest passed {fragment!r} without an error (got {errors})")
    return "\n".join(errors)


def test_malformed_entry(root: pathlib.Path) -> None:
    """A registered skill whose top-level fields are wrong is reported, field by field."""
    cases = {
        "has no source": {DISCIPLINE: {"source": ""}},
        "declares name": {DISCIPLINE: {"name": "other"}},
        "has no 64-hex content hash": {DISCIPLINE: {"sha256": "abc"}},
        "is not the pinned revision": {DISCIPLINE: {"resolved_revision": "0" * 40}},
        "is not the pinned primary source": {DISCIPLINE: {"source": "https://example.test/x.git"}},
    }
    for fragment, overrides in cases.items():
        seed_manifest(root, fixture_manifest(overrides))
        expect_error(root, fragment)


def test_malformed_sources(root: pathlib.Path) -> None:
    """A multi-source skill whose `sources` list is wrong is reported, item by item."""
    pinned = PINNED[METRICS]
    urls = list(pinned)
    cases = {
        "must carry all 4 sources": [{"source": urls[0], "sha256": "b" * 64,
                                      "resolved_revision": pinned[urls[0]]}],
        "without a URL": [*[{"source": url, "sha256": "b" * 64, "resolved_revision": rev}
                            for url, rev in pinned.items()][1:], {"sha256": "b" * 64}],
        "does not list its source": [*[{"source": url, "sha256": "b" * 64, "resolved_revision": rev}
                                       for url, rev in list(pinned.items())[1:]],
                                     {"source": "https://example.test/x.git", "sha256": "b" * 64,
                                      "resolved_revision": "0" * 40}],
    }
    for fragment, sources in cases.items():
        seed_manifest(root, fixture_manifest({METRICS: {"sources": sources}}))
        expect_error(root, fragment)
    bad_rev = [{"source": url, "sha256": "b" * 64, "resolved_revision": rev}
               for url, rev in pinned.items()]
    bad_rev[0]["resolved_revision"] = "0" * 40
    seed_manifest(root, fixture_manifest({METRICS: {"sources": bad_rev}}))
    expect_error(root, "is not the pinned")
    bad_hash = [{"source": url, "sha256": "b" * 64, "resolved_revision": rev}
                for url, rev in pinned.items()]
    bad_hash[1]["sha256"] = "short"
    seed_manifest(root, fixture_manifest({METRICS: {"sources": bad_hash}}))
    expect_error(root, "has no 64-hex content hash")


def test_manifest_cases() -> None:
    """The focused cases run against a temporary copy: the shipped manifest is never edited."""
    for case in (test_malformed_entry, test_malformed_sources):
        with tempfile.TemporaryDirectory() as td:
            case(pathlib.Path(td))


# =============================================================================================
# 5. The wiring: the reviewer's standing section, the role prompts' references
# =============================================================================================
GATE_SECTION_RE = re.compile(r"(?m)^##\s+2\.2\s+Metric gates\s*$")
NUMBERED_GATES = (
    ("gate 1", re.compile(r"(?m)^1\.\s+\*\*Complexity vs test coverage \(gate 1\)\*\*")),
    ("gate 2", re.compile(r"(?m)^2\.\s+\*\*Duplication \(gate 2\)\*\*")),
    ("gate 3", re.compile(r"(?m)^3\.\s+\*\*Test strength \(gate 3\)\*\*")),
)
DISCIPLINE_REF = "skill-base/skills/clean-code-discipline/SKILL.md"


def check_wiring(root: pathlib.Path) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []

    text = read(root, CODE_REVIEW, errors)
    if text is not None:
        if not GATE_SECTION_RE.search(text):
            errors.append(f"{CODE_REVIEW.as_posix()}: no standing `## 2.2 Metric gates` section — "
                          "the reviewer reference lost the gates")
        for label, pattern in NUMBERED_GATES:
            if not pattern.search(text):
                errors.append(f"{CODE_REVIEW.as_posix()}: the numbered gate `{label}` is missing "
                              "from `## 2.2 Metric gates`")
        if not errors:
            notes.append(f"{CODE_REVIEW.as_posix()}: `## 2.2 Metric gates` plus three numbered gates")

    for rel in (CODER, GUI_EXPERT):
        body = read(root, rel, errors)
        if body is not None and DISCIPLINE_REF not in body:
            errors.append(f"{rel.as_posix()}: does not reference {DISCIPLINE_REF} — the role that "
                          "writes code is not held to the discipline")
        elif body is not None:
            notes.append(f"{rel.as_posix()}: references the clean-code discipline")

    reviewer = read(root, CODE_REVIEWER, errors)
    if reviewer is not None:
        if not re.search(r"§\s*2\.2", reviewer) or not re.search(r"metric\s+gates?", reviewer,
                                                                 re.I):
            errors.append(f"{CODE_REVIEWER.as_posix()}: does not reference the metric gates of "
                          "`references/code-review.md` §2.2")
        else:
            notes.append(f"{CODE_REVIEWER.as_posix()}: references the metric gates section")

    return notes, errors


# =============================================================================================
# 6. The task's acceptance verify commands 2 and 3, re-implemented over the shipped skill base
# =============================================================================================
GATE_WORDS = ("CRAP", "duplication", "mutant")


def check_acceptance_verify(root: pathlib.Path) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []

    files = sorted((root / SKILLS).glob("**/SKILL.md")) if (root / SKILLS).is_dir() else []
    if not files:
        errors.append(f"{SKILLS.as_posix()}/: no `SKILL.md` in the skill base — the task's verify "
                      "commands have nothing to read")
        return notes, errors

    bodies: list[str] = []
    for path in files:
        body = read(root, path.relative_to(root), errors)
        if body is not None:
            bodies.append(body)
    if not bodies:
        return notes, errors
    text = "\n".join(bodies)

    missing = [word for word in GATE_WORDS if word.lower() not in text.lower()]
    if missing:
        errors.append("acceptance verify #2 fails over "
                      f"{len(files)} SKILL.md file(s): missing {missing}")

    low = text.lower()
    if "install" not in low:
        errors.append("acceptance verify #3 fails: no skill warns that the tools can install "
                      "packages")
    elif "shell" not in low or "argument vector" not in low:
        # BOTH halves are the warning: a shell string is executed through a shell, only the
        # argument-vector form is safe. Accepting either half alone would pass a body that names
        # "shell" somewhere and never warns about the unsafe form.
        errors.append("acceptance verify #3 fails: no skill warns about a shell string versus the "
                      "argument vector")

    if not errors:
        notes.append(f"verify #2 and #3 hold over {len(files)} SKILL.md file(s)")
    return notes, errors


def seed_skill_base(root: pathlib.Path, body: str) -> None:
    """One SKILL.md whose whole text is `body`, in a temporary skill base."""
    path = root / SKILLS / DISCIPLINE / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_acceptance_verify_one_sided() -> None:
    """A ONE-SIDED shell warning must fail verify #3: both halves of the warning are required."""
    wanted = "no skill warns about a shell string versus the argument vector"
    base = "install on their own initiative\n\nCRAP, duplication, mutant\n\n"
    cases = (
        ("only the shell string",
         base + "a coverage command given as a shell string runs through a shell\n", True),
        ("only the argument vector",
         base + "prefer the safe argument vector form\n", True),
        ("both halves",
         base + "a shell string runs through a shell; only the argument vector form is safe\n",
         False),
    )
    for label, body, must_fail in cases:
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            seed_skill_base(root, body)
            _notes, errors = check_acceptance_verify(root)
        hit = [error for error in errors if wanted in error]
        if must_fail and not hit:
            raise AssertionError(f"verify #3 passed a body carrying {label}: the warning needs both "
                                 f"halves (got {errors})")
        if not must_fail and hit:
            raise AssertionError(f"verify #3 rejected a body carrying {label}: {hit}")


# =============================================================================================
CASES: tuple[tuple[str, Callable[[pathlib.Path], tuple[list[str], list[str]]]], ...] = (
    ("skills-present", check_skills),
    ("metric-gates", check_metric_gates),
    ("tool-safety", check_tool_safety),
    ("manifest", check_manifest),
    ("wiring", check_wiring),
    ("acceptance-verify", check_acceptance_verify),
)

# A check that takes no root: it builds its own fixtures (and must not touch the shipped files).
FIXTURE_CASES: tuple[tuple[str, Callable[[], None]], ...] = (
    ("manifest-cases", test_manifest_cases),
    ("acceptance-verify-cases", test_acceptance_verify_one_sided),
)


def report(name: str, notes: list[str], errors: list[str]) -> int:
    """Print one case's notes and violations; returns 1 when the case failed."""
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if not errors:
        print(f"PASS {name}")
        return 0
    print(f"FAIL {name} - {len(errors)} violation(s):", file=sys.stderr)
    for message in errors:
        print(f"  {message}", file=sys.stderr)
    return 1


def main() -> int:
    use_utf8_output()
    failed = 0
    print(f"clean-code deliverable under {ROOT}")

    for name, case in CASES:
        try:
            notes, errors = case(ROOT)
        except Exception as exc:                  # a broken check must be loud, never silent
            notes, errors = [], [f"{name}: the check itself crashed: {exc!r}"]
        failed += report(name, notes, errors)

    for name, fixture in FIXTURE_CASES:
        try:
            fixture()
            notes, errors = [], []
        except Exception as exc:                  # a broken check must be loud, never silent
            notes, errors = [], [f"{name}: the check itself crashed: {exc!r}"]
        failed += report(name, notes, errors)

    total = len(CASES) + len(FIXTURE_CASES)
    if failed:
        print(f"FAIL - {failed} of {total} checks failed: the clean-code deliverable is not "
              "shipped and wired", file=sys.stderr)
        return 1
    print(f"PASS - the clean-code deliverable holds in {total} checks: both skills are "
          "English-only with the contract sections, the three metric gates carry their thresholds, "
          "the tool-safety warnings are explicit, the manifest pins every source (malformed entries "
          "and source lists are caught), the reviewer reference and the role prompts carry the "
          "wiring, and the task's verify commands pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
