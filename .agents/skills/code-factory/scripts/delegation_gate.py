#!/usr/bin/env python3
"""
Pre-delegation retry budgets for the factory (zero LLM tokens, stdlib only).

WHY THIS EXISTS

The rulebook gives every role its own retry budget (rule `retry-budgets`: coder=1, ba=2, planner=2,
diagnostician=1, advisor=1, infrastructure=3, reviewer=2) and keeps the counters in
`.code-factory/state/pipeline.yaml` (`retry_counters`). Until this script the counter was
SELF-REPORTED: whoever delegated a role also wrote the number, so a run could re-delegate a third
reviewer pass while the checkpoint still said `reviewer: 2` (or never wrote the increment at all) and
nothing refused it. The budget was counted by whoever reported, not by whoever executed.

THE RULE THIS SCRIPT IMPLEMENTS: the budget is counted by whoever EXECUTES, not by whoever REPORTS.
The main agent MUST run `check` before EVERY delegation of a budgeted role; `check` is the one place
that increments the counter, and it REFUSES the delegation once the budget is exhausted. A run that
skips the call is unauditable, and a later gate (`gate_all.py`, task_11) audits the counters against
the session wire.

WHAT `check` DOES (one atomic read-modify-write of ONE counter)

  0. a role WITHOUT a budget entry (analyzer, tester, business_tester, documenter,
     security_auditor, ...) that IS a registered factory role PASSES THROUGH with `allow: true`
     and `budgeted: false` — the budget is counted where the role has one, and the permit gate
     audits the delegation itself; a role nobody registered stays an input error;
  1. reads `.code-factory/state/pipeline.yaml` and its `retry_counters` block (a missing file or a
     missing block is an ACTIONABLE error — `init` is the explicit way to materialize the block);
  2. validates the inputs: `--role` must be a budgeted role (a registered but UNBUDGETED role was
     already passed through at step 0), `--mode` hitl|auto, and every counter
     value must be a non-negative integer (a bool, a numeric string, a negative value or junk is an
     input error, never silently read as zero);
  3. while `retry_counters.<role> < budget`: increments the counter by one, writes the file back
     ATOMICALLY (same-directory temp file + `os.replace`, so an interrupted run never leaves a
     half-written checkpoint) and answers `allow: true`;
  4. once the budget is exhausted: writes NOTHING, answers `allow: false`, and the reason says what
     the mode demands — hitl: the main agent must run the `AskUserQuestion` owner stop (this script
     cannot ask the user); auto: the run ends FAILED with that reason, never an override;
  5. `--owner-authorized` (hitl only — in auto it is an input error, because auto has no override)
     grants EXACTLY ONE extra delegation PER OWNER DECISION: the counter is incremented past the
     budget and a timestamped note is appended to the `owner_authorizations` block of the
     checkpoint. The allowance is budget + the number of notes recorded for that role, so a SECOND
     decision (the main agent asked the owner again) grants a SECOND single extra delegation
     instead of being refused forever — while an UNauthorized call at budget + N is still refused.
     Every authorization is recorded here and nowhere else: no counter is ever hand-written.

REVIEW ROUNDS (`check --role reviewer --round <id>`): a reviewer iteration is counted per LOGICAL
REVIEW ROUND, not per shard. The first `check` carrying a round id consumes one iteration (the
counter is incremented and the round is recorded in the checkpoint's `review_rounds` block); every
later `check` with the SAME round id — the shard fan-out of one whole-repo review, a report-only
review round, a calibration round — is one more delegation of the SAME round: it is allowed, the
counter does NOT move, and the shard is recorded so the finish audit can still account for every
spawn. A round id is a non-empty identifier (`[A-Za-z0-9._-]+`); `--round` is meaningful only for
the reviewer role.

The verdict is printed as ONE JSON object (`allow`, `role`, `mode`, `counter`, `budget`,
`owner_authorized`, `authorizations`, `ceiling`, `reason`, `pipeline`), so the caller branches on
data, not on parsing prose.

SUBCOMMANDS

  check --repo <root> --role <role> --mode hitl|auto [--owner-authorized] [--round <id>]
        the pre-delegation gate (exit 0 allow / 1 refuse / 2 input error)
  init  --repo <root>
        materialize the `retry_counters` block for every budgeted role at 0 (existing values are
        kept) — the only way a checkpoint without the block becomes usable
  audit --repo <root> [--session <dir|auto>] [--home <path>]
        the FINISH audit: every BUDGETED-role spawn in the session wire must have a counter trail -
        `retry_counters.<role>` plus that role's refunded settlements at least the number of times
        the wire spawned it; for the reviewer the trail also adds the recorded shard delegations
        of each logical review round (a round consumes ONE counter iteration but covers its whole
        fan-out). A malformed wire line fails closed; an absent session/wire is DEGRADED
        (exit 3), and a missing `retry_counters` block reads as "nothing was counted".
  settle --repo <root> --role reviewer --round <id> --evidence <path> --refuted-all
        REFUND the one reviewer iteration a WHOLLY REFUTED review round consumed (proposal P-8):
        the counter is decremented by exactly 1 (never below 0), the round is recorded in the
        `settled_rounds` block so a retried call is idempotent, and a MIXED round — or one without
        the evidence artifact — never refunds

EXIT CODES

  0  the delegation is allowed (the counter was incremented and persisted, the role has no budget
     and passed through, or the round was already counted; `init` reported its state)
  1  the delegation is REFUSED (budget exhausted, or the one owner authorization was already used):
     the JSON verdict carries `allow: false` and the reason the mode requires
  2  input error: a bad/absent `--role`, a role nobody registered, an unknown `--mode`, a missing or
     unreadable checkpoint, a missing `retry_counters` block, a malformed counter value, a `--round`
     outside the reviewer role, or `--owner-authorized` outside hitl (a message naming the fix,
     never a traceback)

Single-writer note: the main agent is the only writer of the checkpoint, so the read-modify-write is
safe by construction; the atomic replace exists so an interrupted write can never corrupt a
checkpoint the run depends on.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import tempfile

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The gate may be loaded BY PATH (gate_all.py, a test harness): the sibling role registry it
    # reuses must be importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
from model_matrix import ROLES  # noqa: E402

PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"

# The ONE budget table — the same numbers the canonical rule `retry-budgets` states. A role without
# an entry here has no budget, and the gate refuses to count for it (a made-up budget is worse than
# no gate: it would look enforced while nothing defines the limit).
BUDGETS: dict[str, int] = {"coder": 1, "ba": 2, "planner": 2, "diagnostician": 1, "advisor": 1,
                           "infrastructure": 3, "reviewer": 2}
MODES = ("hitl", "auto")

COUNTERS_HEADER = re.compile(r"^retry_counters:\s*(\{\s*\}|\[\s*\])?\s*(#.*)?$")
AUTHORIZATIONS_HEADER = re.compile(r"^owner_authorizations:\s*(#.*)?$|^owner_authorizations:\s*\[\s*\]\s*(#.*)?$")
# The review-round settlement record (proposal P-8): one note per WHOLLY REFUTED review round whose
# consumed reviewer iteration was refunded. It is what makes the settlement idempotent — the same
# round can never refund twice, however often the flow retries the call.
SETTLED_HEADER = re.compile(r"^settled_rounds:\s*(#.*)?$|^settled_rounds:\s*\[\s*\]\s*(#.*)?$")
# The logical review rounds the reviewer budget is counted in (one note per shard delegation, so
# the finish audit can account for every spawn of a fan-out): `round=<id>` per note.
ROUNDS_HEADER = re.compile(r"^review_rounds:\s*(#.*)?$|^review_rounds:\s*\[\s*\]\s*(#.*)?$")
ROUND_NOTE = re.compile(r"\bround=([A-Za-z0-9._-]+)\b")
SETTLE_ROLE = "reviewer"
ROUND_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ENTRY = re.compile(r"^(\s+)([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$")
LIST_ITEM = re.compile(r"^\s+-\s+(.*\S)\s*$")
UNSIGNED_INT = re.compile(r"^[0-9]+$")


class GateError(ValueError):
    """An input this script cannot honour: reported as a message + exit 2, never a traceback."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the verdict survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise GateError(f"repository root does not exist: {root}")
    return root


def _read_pipeline(path: pathlib.Path) -> str:
    """The checkpoint TEXT, or an actionable error naming the one command that fixes it."""
    if not path.is_file():
        raise GateError(f"no WIP checkpoint at {path}: the flow writes it at the start of a run "
                        f"(run_id, phase, status, updated_at, retry_counters); nothing was counted")
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except OSError as exc:
        raise GateError(f"cannot read {path}: {exc}") from exc


def validate_role(role: str) -> str:
    """The role must be a REGISTERED factory role (a made-up role must never pass the gate).

    A registered role WITHOUT a budget entry is not an error: `check` passes it through (the
    budget is counted where the role has one; the permit gate audits the delegation itself).
    """
    if role not in BUDGETS and role not in ROLES:
        raise GateError(f"role {role!r} is not a registered factory role and has no retry budget: "
                        f"budgeted roles are "
                        f"{', '.join(sorted(BUDGETS))} (coder=1, ba=2, planner=2, diagnostician=1, "
                        f"advisor=1, infrastructure=3, reviewer=2), registered unbudgeted roles "
                        f"pass through ({', '.join(role for role in ROLES if role not in BUDGETS)})")
    return role


def validate_mode(mode: str) -> str:
    if mode not in MODES:
        raise GateError(f"unknown mode {mode!r}: expected one of {', '.join(MODES)}")
    return mode


def _counter_value(role: str, raw: str, where: str) -> int:
    """A counter must be a non-negative INTEGER — `0` is legitimate, `true`/`-1`/`"2"` are not.

    A quoted value is a STRING in the checkpoint, not a number: accepting it would let a counter be
    written as prose and still compare as an int (`"2"` vs `2` would silently both be 2), so the
    quotes are deliberately not stripped here.
    """
    value = raw.strip()
    if not UNSIGNED_INT.match(value):
        raise GateError(f"{where}: retry_counters.{role} must be a non-negative integer, found "
                        f"{value!r}")
    return int(value)


# ---------------------------------------------------------------------------------- block surgery

def _lines(text: str) -> list[str]:
    """The checkpoint as lines WITHOUT their endings (the ending style is re-applied on write)."""
    return text.splitlines()


def _block(lines: list[str], header: re.Pattern) -> tuple[int, int] | None:
    """`(header_index, end_index)` of a top-level `key:` block, or None when it is absent.

    `end_index` is the first line AFTER the block: the first non-empty line that is not indented.
    Blank lines and INDENTED comments inside the block stay inside it (the checkpoint format allows
    them); a comment at column 0 ends the block, exactly like the next top-level key.
    """
    for index, line in enumerate(lines):
        if not header.match(line.rstrip()):
            continue
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if candidate.strip() and not candidate[0].isspace():
                break
            end += 1
        return index, end
    return None


def counters_block(lines: list[str]) -> tuple[int, int]:
    """`(header_index, end_index)` of `retry_counters`, or an actionable error naming `init`."""
    found = _block(lines, COUNTERS_HEADER)
    if found is None:
        raise GateError(f"the WIP checkpoint has no retry_counters block: run "
                        f"`delegation_gate.py init --repo <root>` once to materialize it")
    return found


def _flow_of(line: str) -> str:
    """The flow collection a top-level header spells (`{}` or `[]`), "" when it opens a block."""
    body = line.split(":", 1)[1] if ":" in line else ""
    body = re.sub(r"\s+#.*$", "", body).strip()
    return body if body in ("{}", "[]") else ""


def read_counters(text: str) -> dict[str, int]:
    """Every declared counter, validated (an absent role key is NOT listed here)."""
    lines = _lines(text)
    start, end = counters_block(lines)
    if _flow_of(lines[start]) == "[]":
        raise GateError(f"retry_counters must be a mapping of role -> integer, found a list: run "
                        f"`delegation_gate.py init --repo <root>` to rebuild the block")
    counters: dict[str, int] = {}
    for line in lines[start + 1:end]:
        entry = ENTRY.match(line)
        if entry:
            counters[entry.group(2)] = _counter_value(entry.group(2), entry.group(3),
                                                       "WIP checkpoint")
    return counters


def _set_counter(lines: list[str], role: str, value: int) -> list[str]:
    """The same lines with `retry_counters.<role>` set to `value` (every other byte preserved)."""
    start, end = counters_block(lines)
    lines = list(lines)
    if lines[start].strip() != "retry_counters:":
        # A flow collection on the header (`retry_counters: {}` / `[]`) cannot carry children:
        # normalize the header to the block form before a member line is written under it.
        lines[start] = "retry_counters:"
    indent = "  "
    for index in range(start + 1, end):
        entry = ENTRY.match(lines[index])
        if entry:
            indent = entry.group(1)
            if entry.group(2) == role:
                lines[index] = f"{indent}{role}: {value}"
                return lines
    # The role has no line yet: append it at the end of the block (before its trailing blanks).
    insert_at = end
    while insert_at - 1 > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"{indent}{role}: {value}")
    return lines


def authorization_notes(text: str) -> list[str]:
    """Every `owner_authorizations` note of the checkpoint (the owner's one-off permissions)."""
    lines = _lines(text)
    found = _block(lines, AUTHORIZATIONS_HEADER)
    if found is None:
        return []
    notes: list[str] = []
    for line in lines[found[0] + 1:found[1]]:
        item = LIST_ITEM.match(line)
        if item:
            notes.append(item.group(1))
    return notes


def _authorizations_for(text: str, role: str) -> int:
    """How many owner authorizations this role already consumed (`role=<role>` in a note)."""
    return sum(1 for note in authorization_notes(text) if f" role={role} " in f" {note} ")


def _list_notes(text: str, header: re.Pattern) -> list[str]:
    """Every item of one top-level list block of the checkpoint (`[]` when it is absent)."""
    lines = _lines(text)
    found = _block(lines, header)
    if found is None:
        return []
    notes: list[str] = []
    for line in lines[found[0] + 1:found[1]]:
        item = LIST_ITEM.match(line)
        if item:
            notes.append(item.group(1))
    return notes


def _append_note(lines: list[str], header: re.Pattern, name: str, note: str) -> list[str]:
    """Append `note` to the list block `name`, creating the block when it is absent."""
    lines = list(lines)
    found = _block(lines, header)
    if found is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"{name}:", f"  - {note}"])
        return lines
    start, end = found
    insert_at = end
    while insert_at - 1 > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    indent = "  "
    for line in lines[start + 1:end]:
        item = LIST_ITEM.match(line)
        if item:
            indent = line[:len(line) - len(line.lstrip())]
            break
    lines.insert(insert_at, f"{indent}- {note}")
    return lines


def _append_authorization(lines: list[str], note: str) -> list[str]:
    """Append `note` to the `owner_authorizations` list, creating the block when it is absent."""
    return _append_note(lines, AUTHORIZATIONS_HEADER, "owner_authorizations", note)


def _write_atomic(path: pathlib.Path, text: str) -> None:
    """Write `text` to `path` atomically (a same-directory temp file plus `os.replace`).

    An interrupted or failing write must never leave half a checkpoint behind: the file either
    keeps every byte it had or receives the complete new text. A filesystem failure is DATA for the
    caller — it names the path and the OS reason and exits 2 — never a traceback that hides which
    checkpoint could not be written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    except OSError as exc:
        raise GateError(f"cannot write the checkpoint {path}: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp, path)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise GateError(f"cannot write the checkpoint {path} (the file it had is untouched): "
                        f"{exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise


def _render(lines: list[str], text: str) -> str:
    """Re-apply the checkpoint's own line ending and its trailing newline state."""
    newline = "\r\n" if "\r\n" in text else "\n"
    body = newline.join(lines)
    return body + newline if text.endswith(("\n", "\r\n")) else body


def settled_rounds(text: str) -> list[str]:
    """Every already-refunded review round of the checkpoint (`round=<id>` in a note)."""
    return _list_notes(text, SETTLED_HEADER)


def _wholly_refuted(artifact: pathlib.Path, root: pathlib.Path, round_id: str) -> None:
    """Refuse the refund unless the round's artifact proves EVERY finding was refuted.

    `--refuted-all` is a claim, so it is checked against the artifact the round produced — the
    merged findings JSON of `scripts/merge_findings.py --round <id> --report <path>`: it must NAME
    this round (`round`, mandatory: one artifact settles exactly one round, so the same refuted
    report can never refund two ids), it must state findings at all (an empty round proves nothing),
    and every finding must carry `finding_disposition: refuted` WITH its own `finding_evidence`,
    which must itself be an existing artifact inside the repository. A mixed or accepted round, a
    report without its round identity, or a refutation nobody can point at keeps the iteration it
    consumed.
    """
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"--evidence {artifact.name!r} must be the merged-findings JSON report of "
                        f"the review round (scripts/merge_findings.py --report): {exc}") from exc
    if not isinstance(payload, dict):
        raise GateError(f"--evidence {artifact.name!r} must be a merged-findings JSON OBJECT, got "
                        f"{type(payload).__name__}")
    named = payload.get("round")
    if not isinstance(named, str) or not named.strip():
        raise GateError(f"--evidence {artifact.name!r} names no review round: the merged-findings "
                        f"report must carry its `round` (scripts/merge_findings.py --round "
                        f"<round id>), because one artifact settles exactly one round — an "
                        f"unattributed report could refund several")
    if not ROUND_RE.fullmatch(named):
        raise GateError(f"--evidence {artifact.name!r} names the round {named!r}, which is not a "
                        f"settlement identifier ([A-Za-z0-9._-]+ in FULL: no whitespace, no trailing "
                        f"newline): the report was stamped by hand or by an older producer, not by "
                        f"scripts/merge_findings.py --round")
    if named != round_id:
        raise GateError(f"--evidence {artifact.name!r} belongs to review round {named!r}, not "
                        f"{round_id!r}: a refund settles the round it was asked for")
    findings = payload.get("findings")
    if not isinstance(findings, list) or not findings:
        raise GateError(f"--evidence {artifact.name!r} states no findings: a round is wholly "
                        f"refuted only when it HAS findings and every one of them was refuted")
    repository = root.resolve()
    for index, finding in enumerate(findings):
        where = f"{artifact.name}: findings[{index}]"
        if not isinstance(finding, dict):
            raise GateError(f"{where} must be a JSON object")
        disposition = finding.get("finding_disposition")
        if disposition != "refuted":
            raise GateError(f"{where} is {disposition or 'undispositioned'!r}: one accepted or "
                            f"undispositioned finding makes the round MIXED, and a mixed round "
                            f"keeps the iteration it consumed")
        proof = finding.get("finding_evidence")
        if not isinstance(proof, str) or not proof.strip():
            raise GateError(f"{where} is refuted with no finding_evidence: an unprovable "
                            f"refutation is a suppression, not a refund")
        proof_path = pathlib.Path(proof)
        resolved = (proof_path if proof_path.is_absolute() else root / proof_path).resolve()
        if not resolved.is_relative_to(repository) or not resolved.is_file():
            raise GateError(f"{where} names the evidence {proof!r}, which is not an existing "
                            f"artifact inside {root}")


def settle(repo: str | pathlib.Path, role: str, round_id: str, evidence: str,
           refuted_all: bool = False) -> dict:
    """Refund ONE consumed reviewer iteration for a WHOLLY REFUTED review round (proposal P-8).

    The rule: a review round whose findings were ALL refuted WITH evidence proved nothing, so the
    iteration it consumed is refunded — exactly one, once. A MIXED round (some findings still
    accepted) never refunds: the reviewer really found something. The refund decrements
    `retry_counters.reviewer` by exactly 1 and can never drive it below 0; the round is recorded in
    the `settled_rounds` block, so a retried call is idempotent instead of refunding twice.
    """
    if role != SETTLE_ROLE:
        raise GateError(f"--role must be {SETTLE_ROLE}: only the review round consumes an "
                        f"iteration that a settlement can refund (got {role!r})")
    if not ROUND_RE.fullmatch(round_id or ""):
        raise GateError(f"--round must be a non-empty identifier ([A-Za-z0-9._-]+), got "
                        f"{round_id!r}: it is what makes the settlement idempotent")
    if not refuted_all:
        raise GateError("a settlement refunds only a WHOLLY REFUTED round: pass --refuted-all once "
                        "every finding of the round was refuted with evidence (a mixed round found "
                        "something real and keeps its consumed iteration)")
    if not evidence.strip():
        raise GateError("--evidence is required: a refund without the artifact that proves the "
                        "refutation cannot be checked")
    root = _checked_repo(repo)
    artifact = pathlib.Path(evidence)
    candidate = (artifact if artifact.is_absolute() else root / artifact).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise GateError(f"--evidence {evidence!r} must name an existing artifact inside {root}: a "
                        f"refutation nobody can read is a suppression")
    _wholly_refuted(candidate, root, round_id)
    path = root / PIPELINE_REL
    text = _read_pipeline(path)
    counters = read_counters(text)
    current = counters.get(SETTLE_ROLE, 0)
    verdict = {"role": SETTLE_ROLE, "round": round_id, "refunded": 0, "counter": current,
               "budget": BUDGETS[SETTLE_ROLE], "status": "", "reason": "", "pipeline": str(path)}
    if any(f" round={round_id} " in f" {note} " for note in settled_rounds(text)):
        verdict.update(status="already-settled",
                       reason=(f"round {round_id!r} was already settled: exactly one reviewer "
                               f"iteration is refunded per round, and the record in {path} proves "
                               f"it — nothing changed"))
        return verdict
    if current <= 0:
        verdict.update(status="refused",
                       reason=(f"retry_counters.{SETTLE_ROLE} is already {current}: a settlement "
                               f"refunds one CONSUMED iteration and never drives the counter below "
                               f"0 — nothing was refunded"))
        return verdict
    note = (f"{datetime.datetime.now(tz=datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"round={round_id} role={SETTLE_ROLE} refunded=1 evidence={evidence.strip()}")
    lines = _append_note(_set_counter(_lines(text), SETTLE_ROLE, current - 1), SETTLED_HEADER,
                         "settled_rounds", note)
    _write_atomic(path, _render(lines, text))
    verdict.update(status="settled", refunded=1, counter=current - 1,
                   reason=(f"round {round_id!r} was wholly refuted ({evidence.strip()}): the "
                           f"reviewer iteration it consumed is refunded "
                           f"({current} -> {current - 1}) and recorded in {path}"))
    return verdict


# --------------------------------------------------------------------------------------- commands

def init(repo: str | pathlib.Path) -> dict:
    """Materialize the `retry_counters` block for every budgeted role (existing values kept).

    This is the ONLY way a checkpoint without the block becomes usable: `check` never invents
    counters, because a silently created budget block would hide a checkpoint the flow never wrote.
    """
    root = _checked_repo(repo)
    path = root / PIPELINE_REL
    text = _read_pipeline(path)
    lines = _lines(text)
    found = _block(lines, COUNTERS_HEADER)
    existing: dict[str, int] = {}
    if found is None:
        lines = lines + ([""] if lines and lines[-1].strip() else [])
        lines.append("retry_counters:")
        for role in BUDGETS:
            lines.append(f"  {role}: 0")
        status = "initialized"
    else:
        existing = read_counters(text)
        added = 0
        for role in BUDGETS:
            if role not in existing:
                lines = _set_counter(lines, role, 0)
                added += 1
        status = "initialized" if added else "unchanged"
    counters = {role: existing.get(role, 0) for role in BUDGETS}
    if status == "initialized":
        _write_atomic(path, _render(lines, text))
        counters = {role: read_counters(_render(lines, text)).get(role, 0) for role in BUDGETS}
    return {"status": status, "pipeline": str(path), "counters": counters}


def review_rounds(text: str) -> list[str]:
    """Every recorded shard-delegation note of the checkpoint's `review_rounds` block."""
    return _list_notes(text, ROUNDS_HEADER)


def _round_note(round_id: str, shard: int) -> str:
    stamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{stamp} round={round_id} role={SETTLE_ROLE} shard={shard}"


def _shard_count(notes: list[str], round_id: str) -> int:
    """How many shard delegations of `round_id` are already recorded (the fan-out so far)."""
    return sum(1 for note in notes
               if (match := ROUND_NOTE.search(note)) and match.group(1) == round_id)


def check(repo: str | pathlib.Path, role: str, mode: str,
          owner_authorized: bool = False, round_id: str | None = None) -> dict:
    """The pre-delegation gate: increment the role's counter, or REFUSE the delegation.

    Returns the verdict dict (which is also what the CLI prints). Raises `GateError` for an input
    this script cannot honour; a refusal is DATA (`allow: false`), never an exception.
    """
    validate_role(role)
    validate_mode(mode)
    if owner_authorized and mode != "hitl":
        raise GateError("--owner-authorized is only meaningful in hitl: auto mode has no budget "
                        "override — the run ends FAILED with the reason")
    if round_id is not None:
        if role != SETTLE_ROLE:
            raise GateError(f"--round is meaningful only for the {SETTLE_ROLE} role (a reviewer "
                            f"iteration is counted per LOGICAL REVIEW ROUND), got --role {role!r}")
        if not ROUND_RE.fullmatch(round_id or ""):
            raise GateError(f"--round must be a non-empty identifier ([A-Za-z0-9._-]+), got "
                            f"{round_id!r}: it is what makes the shard fan-out of one logical "
                            f"review round count as ONE iteration")
    root = _checked_repo(repo)
    if role not in BUDGETS:
        # A registered role WITHOUT a budget entry passes through: the budget is counted where the
        # role has one, and the permit gate audits the delegation itself. Nothing is written —
        # there is no counter to move.
        return {"role": role, "mode": mode, "allow": True, "budgeted": False, "counter": None,
                "budget": None, "owner_authorized": False,
                "reason": (f"role {role!r} carries no retry budget: the delegation is allowed and "
                           f"NOT counted here — the budget is counted where the role has one, and "
                           f"the permit gate audits the delegation itself"),
                "pipeline": str(root / PIPELINE_REL)}
    path = root / PIPELINE_REL
    text = _read_pipeline(path)
    counters = read_counters(text)
    budget = BUDGETS[role]
    current = counters.get(role, 0)
    verdict = {"role": role, "mode": mode, "allow": False, "counter": current, "budget": budget,
               "owner_authorized": bool(owner_authorized), "reason": "", "pipeline": str(path)}
    if round_id is not None:
        verdict["round"] = round_id

    # A REPEATED round id is another shard delegation of the SAME logical review round: it is
    # allowed, the counter does not move, and the shard is recorded so the finish audit can still
    # account for every spawn of the fan-out.
    notes = review_rounds(text) if round_id is not None else []
    shard = _shard_count(notes, round_id) if round_id is not None else 0
    if round_id is not None and shard:
        lines = _append_note(_lines(text), ROUNDS_HEADER, "review_rounds",
                             _round_note(round_id, shard + 1))
        _write_atomic(path, _render(lines, text))
        verdict.update(allow=True, round_counted=False,
                       reason=(f"review round {round_id!r} is already counted: shard delegation "
                               f"{shard + 1} of the SAME logical round consumes no new iteration "
                               f"(the counter stays {current} of {budget}), and the shard is "
                               f"recorded in {path}"))
        return verdict

    # The allowance is PER OWNER DECISION: the budget plus one extra delegation for every
    # authorization already recorded for this role. A second `--owner-authorized` call is a NEW
    # decision (the main agent asked again), so it records a new note and grants a new single extra
    # delegation instead of being refused forever.
    authorizations = _authorizations_for(text, role)
    ceiling = budget + authorizations
    verdict.update(authorizations=authorizations, ceiling=ceiling)

    if current < ceiling:
        lines = _set_counter(_lines(text), role, current + 1)
        if round_id is not None:
            lines = _append_note(lines, ROUNDS_HEADER, "review_rounds", _round_note(round_id, 1))
        _write_atomic(path, _render(lines, text))
        band = (f"delegation {current + 1} of the {budget} allowed for role {role!r}"
                if current < budget else
                f"delegation {current + 1} of the {budget} allowed for role {role!r} "
                f"+ {authorizations} owner-authorized extra delegation(s)")
        if round_id is not None:
            band += f" (review round {round_id!r}, shard 1: the ROUND consumes the iteration)"
        verdict.update(allow=True, counter=current + 1,
                       reason=f"{band}: the counter was incremented in {path}")
        if round_id is not None:
            verdict["round_counted"] = True
        return verdict

    if owner_authorized:
        note = (f"{datetime.datetime.now(tz=datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
                f"role={role} counter={current + 1} mode=hitl")
        lines = _append_authorization(_set_counter(_lines(text), role, current + 1), note)
        if round_id is not None:
            lines = _append_note(lines, ROUNDS_HEADER, "review_rounds", _round_note(round_id, 1))
        _write_atomic(path, _render(lines, text))
        verdict.update(allow=True, counter=current + 1, authorizations=authorizations + 1,
                       ceiling=ceiling + 1,
                       reason=(f"the owner authorized ONE extra delegation beyond the {budget} + "
                               f"{authorizations} already authorized of role {role!r}: the counter "
                               f"is {current + 1} and authorization {authorizations + 1} is "
                               f"recorded in {path} (the next one needs a new owner decision)"))
        if round_id is not None:
            verdict["round_counted"] = True
        return verdict

    if mode == "hitl":
        verdict["reason"] = (
            f"the retry budget of role {role!r} is exhausted ({current} of {budget} delegations "
            f"used): the delegation is REFUSED and the counter was not incremented. The main agent "
            f"MUST run the AskUserQuestion owner stop now and ask whether to change the approach, "
            f"to authorize exactly one extra delegation (rerun this check with "
            f"--owner-authorized, recorded in the checkpoint as a NEW decision) or to stop the "
            f"run")
    else:
        verdict["reason"] = (
            f"the retry budget of role {role!r} is exhausted ({current} of {budget} delegations "
            f"used): the delegation is REFUSED and the counter was not incremented. Auto mode has "
            f"no override — the run ends FAILED with this reason (reviewer budget exhausted with "
            f"open findings: a conditional pass is recorded, never a silent loop)")
    return verdict


# --------------------------------------------------------------------------------------------
# `audit`: every budgeted-role spawn in the wire must have a counter trail
# --------------------------------------------------------------------------------------------
class GateDegraded(RuntimeError):
    """There is no session wire to audit (exit 3): nothing was proven either way."""


def _attribution():
    """The sibling `model_attribution` module (session resolution), imported on demand.

    `check` and `settle` must not depend on the model layer — the gate is a control that has to work
    when everything else is broken — so the audit imports it lazily.
    """
    scripts = pathlib.Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import model_attribution  # noqa: PLC0415  (deliberately lazy)
    except ImportError as exc:
        raise GateError(f"the delegation audit reuses model_attribution.py's session resolution, "
                        f"which cannot be imported: {exc}") from exc
    return model_attribution


def wire_spawns(session_dir: pathlib.Path) -> tuple[dict[str, int], list[str], int]:
    """`({role: spawn count}, malformed, events)` of every `agents/*/wire.jsonl` of one session.

    Data only: the events are READ, never executed. A malformed line (not a JSON object) or a spawn
    whose role cannot be read FAILS THE AUDIT CLOSED — an unreadable wire is exactly the state in
    which "every delegation was counted" cannot be claimed.
    """
    attribution = _attribution()
    agents_dir = session_dir / attribution.AGENTS_DIR
    wires = (sorted(wire for wire in agents_dir.glob(f"*/{attribution.WIRE_FILE}") if wire.is_file())
             if agents_dir.is_dir() else [])
    if not wires:
        raise GateDegraded(f"session {session_dir.name} has no {attribution.AGENTS_DIR}/*/"
                           f"{attribution.WIRE_FILE}: there is no spawn evidence to audit")
    spawns: dict[str, int] = {}
    malformed: list[str] = []
    events = 0
    for wire in wires:
        try:
            text = wire.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise GateError(f"cannot read the wire {wire}: {exc}") from exc
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(f"{wire}:{number}: not a JSON object (an unreadable wire cannot "
                                 f"prove that no delegation went uncounted)")
                continue
            if not isinstance(event, dict):
                malformed.append(f"{wire}:{number}: the event is not a JSON object")
                continue
            events += 1
            if event.get("type") != "subagent.spawned":
                continue
            role = attribution.role_from_profile(str(event.get("subagentName") or ""))
            if not role:
                malformed.append(f"{wire}:{number}: a spawn names no factory role "
                                 f"({event.get('subagentName')!r}) - it cannot be matched to a "
                                 f"budget")
                continue
            spawns[role] = spawns.get(role, 0) + 1
    return spawns, malformed, events


def audit(repo: str | pathlib.Path, session: str = "auto", home: str | None = None) -> dict:
    """The finish audit: every BUDGETED-role spawn in the wire has a counter trail.

    For each budgeted role the wire spawned N times, `retry_counters.<role>` plus that role's
    refunded settlements must account for at least N delegations — a spawn with no counted
    delegation means the flow skipped `delegation_gate.py check`, and the budget enforced nothing.
    A missing `retry_counters` block is read as "nothing was counted" (every spawn is then
    uncounted); a malformed counter is an input error; an absent session/wire is DEGRADED.
    """
    attribution = _attribution()
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise GateError(f"repository root does not exist: {root}")
    wire_home = pathlib.Path(home) if home else attribution.WIRE_HOME
    try:
        info = attribution.resolve_session(str(root), session, wire_home)
    except attribution.Degraded as exc:
        raise GateDegraded(str(exc)) from exc
    except attribution.AttributionError as exc:
        raise GateError(str(exc)) from exc
    session_dir = pathlib.Path(info["session_dir"])
    spawns, malformed, events = wire_spawns(session_dir)
    path = root / PIPELINE_REL
    text = _read_pipeline(path)
    counters = {} if _block(_lines(text), COUNTERS_HEADER) is None else read_counters(text)
    refunded: dict[str, int] = {}
    for note in settled_rounds(text):
        match = re.search(r"\brole=(\S+)", note)
        if match and "refunded=1" in note:
            refunded[match.group(1)] = refunded.get(match.group(1), 0) + 1
    # Logical review rounds: each recorded round consumed ONE counter iteration but covers every
    # shard delegation of its fan-out, so the trail adds the recorded shard notes back.
    round_ids: set[str] = set()
    shard_notes = 0
    round_problems: list[str] = []
    for note in review_rounds(text):
        match = ROUND_NOTE.search(note)
        if not match:
            round_problems.append(f"unreadable review-round note: {note!r} (a review_rounds entry "
                                  f"must name its round=<id>)")
            continue
        round_ids.add(match.group(1))
        shard_notes += 1
    problems: list[str] = ([f"malformed wire evidence: {entry}" for entry in malformed]
                           + round_problems)
    for role in sorted(spawns):
        if role not in BUDGETS:
            continue                                    # a role without a budget: nothing to count
        counted = counters.get(role, 0) + refunded.get(role, 0)
        detail = (f" (+{refunded[role]} refunded)" if refunded.get(role) else "")
        if role == SETTLE_ROLE and (round_ids or shard_notes):
            counted = counted - len(round_ids) + shard_notes
            detail += (f" ({len(round_ids)} logical round(s) covering {shard_notes} shard "
                       f"delegation(s))")
        if spawns[role] > counted:
            problems.append(f"uncounted delegation: the wire spawned role {role!r} "
                            f"{spawns[role]} time(s), but retry_counters.{role} is "
                            f"{counters.get(role, 0)}"
                            + detail
                            + " - the flow delegated without `delegation_gate.py check`")
    return {"status": "failed" if problems else "ok", "repo": str(root),
            "session": str(session_dir), "pipeline": str(path), "events": events,
            "spawns": spawns, "counters": {role: counters.get(role, 0) for role in BUDGETS},
            "problems": problems}


# -------------------------------------------------------------------------------------------- CLI

def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="delegation_gate.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("check", help="count (and possibly refuse) one delegation of a role")
    check_p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    check_p.add_argument("--role", required=True,
                         help="budgeted role: " + ", ".join(f"{r}={b}" for r, b in BUDGETS.items()))
    check_p.add_argument("--mode", required=True, choices=MODES,
                         help="hitl (the owner stop is available) or auto (no override)")
    check_p.add_argument("--owner-authorized", action="store_true", dest="owner_authorized",
                         help="hitl only: the owner allowed ONE extra delegation beyond the budget")
    check_p.add_argument("--round", default=None,
                         help="reviewer only: the LOGICAL REVIEW ROUND id ([A-Za-z0-9._-]+) — the "
                              "shard fan-out of one round counts as ONE iteration")
    check_p.set_defaults(func=_cmd_check)

    init_p = sub.add_parser("init", help="materialize the retry_counters block of the checkpoint")
    init_p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    init_p.set_defaults(func=_cmd_init)

    settle_p = sub.add_parser("settle", help="refund ONE reviewer iteration for a wholly refuted "
                                             "review round (proposal P-8)")
    settle_p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    settle_p.add_argument("--role", required=True, choices=(SETTLE_ROLE,),
                          help="the role whose consumed iteration is refunded (reviewer only)")
    settle_p.add_argument("--round", required=True,
                          help="the review round id ([A-Za-z0-9._-]+): the settlement key")
    settle_p.add_argument("--evidence", required=True,
                          help="the artifact (inside --repo) that proves the round was wholly "
                               "refuted")
    settle_p.add_argument("--refuted-all", action="store_true", dest="refuted_all",
                          help="confirm EVERY finding of the round was refuted with evidence (a "
                               "mixed round never refunds)")
    settle_p.set_defaults(func=_cmd_settle)

    audit_p = sub.add_parser("audit", help="finish audit: every budgeted-role spawn has a counter "
                                           "trail in the checkpoint")
    audit_p.add_argument("--repo", required=True, help="repository root holding .code-factory/")
    audit_p.add_argument("--session", default="auto",
                         help="a session directory, or 'auto' for the current one (default)")
    audit_p.add_argument("--home", default=None, help="the CLI's wire root (default: ~/.kimi-code)")
    audit_p.set_defaults(func=_cmd_audit)
    return ap


def _cmd_check(args: argparse.Namespace) -> int:
    verdict = check(args.repo, args.role, args.mode, args.owner_authorized, args.round)
    _emit(verdict)
    return 0 if verdict["allow"] else 1


def _cmd_init(args: argparse.Namespace) -> int:
    _emit(init(args.repo))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    try:
        result = audit(args.repo, args.session, args.home)
    except GateDegraded as exc:
        print(f"DEGRADED - the delegation audit cannot prove anything: {exc}")
        return 3
    print(f"session: {result['session']}")
    print(f"pipeline: {result['pipeline']}")
    spawns = ", ".join(f"{role}={count}" for role, count in sorted(result["spawns"].items()))
    print(f"events: {result['events']}, budgeted-role spawns: {spawns or 'none'}")
    for problem in result["problems"]:
        print(f"violation: {problem}")
    if result["status"] == "ok":
        print("PASS - every budgeted-role spawn in the wire has a counter trail")
        return 0
    print(f"FAIL - {len(result['problems'])} delegation-audit violation(s)")
    return 1


def _cmd_settle(args: argparse.Namespace) -> int:
    verdict = settle(args.repo, args.role, args.round, args.evidence, args.refuted_all)
    _emit(verdict)
    return 0 if verdict["status"] in ("settled", "already-settled") else 1


def main() -> int:
    use_utf8_output()
    ap = build_parser()
    args = ap.parse_args()
    try:
        return args.func(args)
    except GateError as exc:
        print(f"delegation_gate.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
