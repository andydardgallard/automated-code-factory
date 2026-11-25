#!/usr/bin/env python3
"""
The supervisor permit gate (proposal P-8's machine backstop, violation N-5) — zero LLM tokens.

WHY THIS EXISTS

task_15 registers `factory-supervisor`, a JUDGE-side role that reviews a proposed delegation's permit
against the rulebook and the approved plan. That verdict is MODEL-ENFORCED: a main agent that skips
the step is not physically stopped by a model reading prose. This script is the deterministic half:

  - a delegation is described by a PERMIT (`.code-factory/state/permits.yaml`), which must exist
    BEFORE the subagent is spawned;
  - the supervisor's `allow`|`deny` verdict and its evidence are recorded ON that permit;
  - the spawned agent id is bound to the permit it ran under;
  - the FINISH AUDIT joins the permits with the session wire (`subagent.spawned` events) and with the
    approved plan's task list: every spawn must match a unique, allowed, already-judged permit whose
    scope is a subset of the plan task's files, and every allowed permit must either have run or be
    explicitly closed.

FORMAT: `permits.yaml` is a JSON-compatible YAML document and is parsed with the STDLIB json module
(no YAML dependency, no hand-written parser). Shape:

  {"run_id": "<YYYYMMDD>-<8 hex>",
   "permits": [{"permit_id": "<id>", "kind": "plan" | "bootstrap",
                "task_id": "<plan task id>" | "bootstrap", "role": "<factory role>",
                "phase": "<lifecycle phase>", "scope": ["<repo-relative path>", ...],
                "constraints": ["<text>", ...], "created_at": "<ISO>",
                "verdict": null | "allow" | "deny", "evidence": "<text>",
                "verdict_at": "<ISO>", "verdict_at_ms": <int>,
                "agent_id": null | "<agent id>", "bound_at": null | "<ISO>",
                "session_id": null | "<CLI session id the binding was recorded in>",
                "closed": null | {"at": "<ISO>", "reason": "<text>"}}]}

Every field is TYPE- AND VOCABULARY-VALIDATED when the file is loaded (a scalar `agent_id`, string
lists for `scope`/`constraints`, the verdict and phase vocabularies, the timestamp shapes): a
malformed file is a PermitError (exit 2), never a crash inside the audit.

THE LEDGER: `permits.yaml` alone cannot prove it is THE run's registry — a flow can delete it,
re-initialise it and re-register the same permits as if a deny had never happened. So every
transition ALSO appends one line to the append-only `permits.ledger.jsonl`
(`.code-factory/state/permits.ledger.jsonl`), a hash chain over the resulting state. A LAUNCH-SCOPED
registry is the same pair under the launch's own key:
`.code-factory/state/permits.launch-<launch id>.yaml` and
`.code-factory/state/permits.ledger.launch-<launch id>.jsonl` — one launch, one chain.

  {"seq": <1-based int>, "run_id": "<run the state belonged to>",
   "prev": "<hash of the previous line, 64 zeros for the first>",
   "action": "init" | "add" | "verdict" | "bind" | "close" | "reinit" | "repair",
   "permit_id": "<permit id or null>", "at": "<ISO>", "state": "<sha256 of the state>",
   "hash": "<sha256 of the line's seq/prev/run_id/action/permit_id/at/state>"}

`state` is the CANONICAL serialization (sorted keys, no whitespace) of `{run_id, permits}` with
every field of every permit, one documented exception: `owner_authorized` is never hashed, and for
an owner-authorized permit `evidence`/`verdict_at`/`verdict_at_ms` are not either — the run-bound
`owner_authorizations` note, not the editable field, is what disposition that annotation has.
Formatting, key order and a re-serialization are therefore irrelevant; the CONTENT is not.

The chain itself must verify (every line's hash, the `prev` link and the `seq` counter), and its
head must equal the state on disk. The check runs BEFORE every write and at the finish audit, so a
reset (an emptied registry), a truncated tail, an edited record and a post-deny repair are all
refusals: they are rewritten history, never a permitted transition. A registry that lists permits
but has no journal is UNPROVEN (an earlier factory wrote it) — that is reported, never silently
adopted, because adopting it would erase whatever it already lost.

THE LEGACY SNAPSHOT (`snapshot-legacy`): a run whose `permits.yaml` predates this journal cannot
append honestly — the pre-journal transitions were never recorded, and inventing them would be the
fabrication this gate exists to prevent. The ONE honest transition such a run can take is to attest
the registry AS IT STANDS: `snapshot-legacy` appends a single, clearly marked `snapshot` event whose
recorded state is the CURRENT file, whose `at` is NOW, and whose note says the earlier history is
unproven. It never touches `permits.yaml`, never creates an `init`/`add`/`verdict`/`bind` event,
never back-dates anything, and refuses once a journal exists (a snapshot is taken once, before the
first post-upgrade write) or when the file belongs to another run. The audit still applies every
check to the attested permits: a snapshot attests WHICH records exist, never that they were
permitted.

THE TRANSACTION AND THE REPAIR: a state write and its journal append are ONE transaction — a failed
append rolls the file back to the byte image it had before (the FIRST write, which has no previous
file, is rolled back by deleting it), a PARTIAL journal line is restored to the journal's previous
byte image (or the newly created journal is removed), and a failed rollback is a loud critical error
rather than a silently advanced registry. The "already done" shortcuts (`init`, `bind`, `close`,
`bind-run`) verify the history before they answer `unchanged`, so a retry on a DIVERGED registry
fails (exit 2) instead of re-blessing the divergence. Recovery is the owner's explicit `repair`: no
`--mode` only reports the divergence; `--mode restore` re-derives `permits.yaml` from the ledger
head's recorded projection (the unjournaled transition is lost, deliberately); `--mode attest
--note <why>` keeps the file on disk and appends ONE marked `repair` event that re-anchors the
chain, recording no transition that did not happen.

BOOTSTRAP PERMITS (`add --kind bootstrap`): before the plan is APPROVED no delegation can name a
plan task, so the run's first delegations answer the TASK itself. A bootstrap permit is limited to
the pre-plan read-only roles (`analyzer`, `planner` — the initial planning — and `supervisor`,
which is launched under the run's own authority), carries `--task-id bootstrap`, and is validated
against the PARSED task (`.code-factory/state/task.yaml`) instead of the plan — except the
SUPERVISOR's own permit, which is anchored on the RUN (`_run_authority`: the checkpoint's validated
`run_id`) because the watchdog is launched BEFORE Phase 0 parses the task, so no parsed task exists
at that moment and the record must still be auditable pre-spawn (role, phase, the run binding and
the supervisor's verdict). On a FRESH run there is not even a `run_id` yet (`begin` is
run-id-independent): `init --launch-dir` / `add --launch-dir` anchor that permit to the launch
bootstrap's `begun_at` and leave the registry UNBOUND, and `bind-run` binds it once, atomically,
when `activate` writes the checkpoint — the pre-run transitions keep the timestamps they were
recorded with. A LAUNCH-SCOPED registry is KEYED by the launch id `begin` minted: several factories
may be launched from one folder (each into its own `repo_path`), so a launch's permits and journal
are `permits.launch-<launch id>.yaml` / `permits.ledger.launch-<launch id>.jsonl` and never one
shared file. `--launch-id` says WHICH launch a command addresses; without it the folder resolves
only while exactly ONE bootstrap is uncompleted, and several open launches are a loud refusal that
lists them. The unkeyed launch-only files a pre-key run left behind stay resolvable where they are
(never migrated) until `bind-run` retires them; a launch folder that IS the resolved repository
still transfers its KEYED registry to the run's own (unkeyed) name, so the launch copy is retired
instead of being left as a second live registry beside the run's. The approved-plan task checks
apply to `plan` permits only (implementation and later delegations).

THE SUPERVISOR'S OWN SPAWNS: the supervisor is a run-long WATCHDOG launched at run start under the
run's own authority — it cannot judge its own permit before it exists (bootstrap circularity). The
finish audit therefore EXEMPTS supervisor spawns from the permit-less check; a supervisor spawn that
IS bound to a permit is audited like any other (role, verdict order, plan scope).

SUBCOMMANDS

  init    --repo <root> [--launch-dir <dir>] [--launch-id <id>]
                                              create the skeleton {run_id, permits: []} (refuses to
                                              overwrite a file that already lists permits). With
                                              `--launch-dir` the registry is created UNBOUND
                                              (`run_id: ""`) against the launch bootstrap `begin`
                                              wrote — the only authority that exists before Phase 0 —
                                              and it is KEYED by that launch (`permits.launch-<id>
                                              .yaml` + `permits.ledger.launch-<id>.jsonl`), so
                                              concurrent factories in one folder never share a file
  bind-run --repo <root> [--run-id <id>] [--launch-dir <dir>] [--launch-id <id>]
                                              bind a launch-scoped registry to the run its
                                              activation recorded (once, atomic, journaled); with
                                              `--launch-dir` that launch's registry is TRANSFERRED
  add     --repo <root> --permit-id <id> --task-id <plan task id> --role <role> --phase <phase>
          [--kind plan|bootstrap] [--launch-dir <dir>] [--launch-id <id>]
          [--scope <repo-relative path> ...]
          [--constraint <text> ...]
                                              register ONE permit; the task id must exist in the
                                              approved plan (a `--kind bootstrap` permit answers the
                                              TASK itself instead — see BOOTSTRAP PERMITS above),
                                              the role must be registered, the phase
                                              must be a known lifecycle phase, every scope must be a
                                              confined repo-relative path, and an EMPTY scope is only
                                              allowed for a read-only / business-test role
  verdict --repo <root> --permit-id <id> --verdict allow|deny --evidence <text>
          [--launch-dir <dir>] [--launch-id <id>]
                                              record the supervisor's verdict (evidence is
                                              mandatory; a second verdict on the same permit fails)
  bind    --repo <root> --permit-id <id> --agent-id <id> [--launch-dir <dir>] [--launch-id <id>]
                                              record the agent id a permitted delegation spawned
                                              (only on an ALLOWED, judged permit; an agent id is
                                              unique within the run's CLI session — ids restart in
                                              every session, so an earlier session's binding never
                                              blocks this one. The binding also records the CLI
                                              session it was made in (`session_id`, from the
                                              checkpoint's `session_dir` `state.json`; null when
                                              the run cannot prove it), which is what tells two
                                              OVERLAPPING sessions apart)
  close   --repo <root> --permit-id <id> --reason <text>
                                              mark an allowed permit as NOT executed (the only way an
                                              unused allow stops being an audit failure)
  snapshot-legacy --repo <root> [--note <text>]
                                              attest a PRE-JOURNAL registry as it stands: ONE marked
                                              `snapshot` event, `permits.yaml` untouched, no
                                              transition invented (see THE LEGACY SNAPSHOT)
  repair  --repo <root> [--mode restore|attest] [--note <text>]
                                              the owner's EXPLICIT recovery from a divergence (see
                                              THE REPAIR): no `--mode` only reports it
  audit   --repo <root> [--session <dir|auto>] [--home <path>]
                                              the FINISH gate (see below)

THE AUDIT (exit codes: 0 pass, 1 violation, 2 input error, 3 DEGRADED — no session wire to audit)

  Before ANY spawn is evaluated the ledger is verified (see THE LEDGER) — a registry whose history
  was rewritten fails the audit even when its CURRENT content looks consistent — and the permits
  file's run_id must equal the current pipeline run id:
  permits of ANOTHER run never authorize this run's delegations (stale permits are a violation, not
  a fallback). Then, every `subagent.spawned` in the session wire must match a permit BY AGENT ID
  AND ROLE — an agent id is ONE delegation, so a RESUMED agent's later spawn lines are that same
  delegation and its role is the one its ORIGINAL spawn carried (a resume's generic profile name is
  no role claim); the permit
  must be `allow` (a DENIED permit may never acquire an agent id, so a spawn under it is a breach);
  its verdict time must PRECEDE the spawn time; its scope must be a SUBSET of the files the approved
  plan declares for its task id; every allowed permit must be bound to a spawn or explicitly closed;
  and two permits may never share a permit id, and may never share an agent id WITHIN one CLI
  session (`bind` and the audit judge that collision on the same evidence).
  A binding is judged PER CLI SESSION: agent ids restart at `agent-0` in every session, so a permit
  bound by ANOTHER session is neither a `bound but never spawned` of the audited one nor a collision
  with its ids. WHICH session a binding belongs to is decided by the strongest evidence available:
  (a) the `session_id` `bind` records on every permit from the run's own session (`session_dir` ->
  `state.json`'s id) — decisive in both directions, so two bindings recorded in one earlier session
  still collide while two bindings of two DIFFERENT earlier sessions do not; (b) for a permit bound
  before that field existed, its `bound_at` against the audited session's `createdAt` — it proves
  the binding is NOT the audited session's, but not WHICH earlier session made it, so such a permit
  is never asserted to share a session with another (`createdAt` cannot separate two OVERLAPPING
  sessions); and (c) with no session start, no session id and an unreadable `bound_at`, the binding
  is judged as this session's (fail closed). A wire line that is
  not a JSON object
  FAILS THE AUDIT CLOSED — an unreadable wire is exactly the state in which "every delegation was
  permitted" cannot be claimed. An absent session/wire is DEGRADED (exit 3), like the action audit.

  OWNER AUTHORIZATIONS are RUN-BOUND, never self-attested: a permit's `owner_authorized: true` flag
  lives in this hand-editable file, so it is not evidence by itself. The retroactive bootstrap
  exception applies only when THIS run's `.code-factory/state/pipeline.yaml` independently records
  the decision — an `owner_authorizations:` list item naming `permit=<id>` (the journal
  `delegation_gate.py` appends to). A flag without that note is an `unverified owner authorization`
  violation and the out-of-order verdict stands.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import pathlib
import re
import sys
import tempfile

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    # The gate may be loaded BY PATH (gate_all.py, a test harness): the sibling modules it reuses
    # must be importable without depending on the caller's sys.path.
    sys.path.insert(0, str(_SCRIPTS_DIR))
from manifest import ManifestError, confined_relpath  # noqa: E402
from model_matrix import ROLES  # noqa: E402

PERMITS_REL = pathlib.Path(".code-factory") / "state" / "permits.yaml"
LEDGER_REL = pathlib.Path(".code-factory") / "state" / "permits.ledger.jsonl"
# A LAUNCH-SCOPED registry is KEYED by the launch nonce `supervisor_watchdog.py begin --launch-dir`
# mints: one launch folder may carry several in-flight factories (each with its own `repo_path`), so
# a launch's permits and its journal are named after THAT launch — never one shared mutable file.
# The unkeyed names above stay the RUN's registry, and the launch-only legacy files a pre-key run
# left behind (they are resolved as they stand, never migrated).
LAUNCH_PERMITS_FMT = "permits.launch-{launch_id}.yaml"
LAUNCH_LEDGER_FMT = "permits.ledger.launch-{launch_id}.jsonl"
PLAN_REL = pathlib.Path(".code-factory") / "state" / "plan.md"
PIPELINE_REL = pathlib.Path(".code-factory") / "state" / "pipeline.yaml"
TASK_REL = pathlib.Path(".code-factory") / "state" / "task.yaml"

VERDICTS = ("allow", "deny")
PERMIT_KINDS = ("plan", "bootstrap")
# A bootstrap permit answers the TASK itself (no plan exists yet), so it carries this fixed task id.
BOOTSTRAP_TASK_ID = "bootstrap"
# The pre-plan bootstrap set: the read-only analysis/planning roles, plus the supervisor itself —
# the watchdog is launched at run start under the run's OWN authority (it cannot judge its own
# permit before it exists). Every other role needs an approved-plan task and a `plan` permit.
BOOTSTRAP_ROLES = frozenset({"analyzer", "planner", "supervisor"})
SUPERVISOR_ROLE = "supervisor"
# The lifecycle phases a permit may be issued in: the factory's own phase names (analysis ->
# acceptance) plus the finish checkpoint. A closed vocabulary so `--phase nonsense` cannot pass.
PERMIT_PHASES = ("analysis", "plan", "implement", "review", "refactor", "security_audit",
                 "acceptance", "finish")
# The roles that produce NO file change — a read-only analysis or a business test — may carry an
# empty scope. Every other role must say which files it will touch: an empty scope for a coder or a
# documenter would permit an unbounded change behind a permit.
READ_ONLY_ROLES = frozenset({"analyzer", "planner", "reviewer", "diagnostician", "advisor",
                             "business_tester", "supervisor"})
PERMIT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
RUN_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{8}$")
RUN_ID_LINE = re.compile(r"^run_id:\s*(.*)$")
# The launch nonce `supervisor_watchdog.py begin` mints, validated HERE too: it becomes the filename
# component of a launch-scoped registry, so separators, `..` and an empty value have no legitimacy.
LAUNCH_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
# The checkpoint's `owner_authorizations:` list (written by `delegation_gate.py`): one plain YAML
# list item per owner decision, e.g.
#   - 2026-11-05T16:59:25Z permit=PB role=supervisor mode=hitl
AUTHORIZATIONS_HEADER = re.compile(r"^owner_authorizations:\s*(?:\[\s*\]\s*)?(?:#.*)?$")
AUTHORIZATION_ITEM = re.compile(r"^\s*-\s+(?P<note>\S.*?)\s*$")
TASK_LINE = re.compile(r"^-\s+(?P<id>[A-Za-z][A-Za-z0-9_]*)\s*:\s*(?P<rest>.*)$")
FILES_FIELD = re.compile(r"\bfiles\s*:\s*(?P<files>.*?)(?:;\s*(?:deps|verify)\b|$)")
# The ledger's own vocabulary: the fields a line's hash covers, and the genesis link a chain starts
# from. An unknown extra key on a line does not contribute to its hash and is ignored. `doc` is the
# recorded projection of the state, kept so an annotation amendment (only) can be reconciled against
# what was actually recorded; `note` carries the transition's marking (the legacy snapshot's own
# marker) inside the hash, so the marker cannot be removed without breaking the chain.
LEDGER_FIELDS = ("seq", "prev", "run_id", "action", "permit_id", "at", "note", "state", "doc")
LEDGER_ACTIONS = ("init", "add", "verdict", "bind", "close", "reinit", "snapshot", "bind-run",
                  "repair")
# The one transition a PRE-JOURNAL registry may take: attest the current state, invent nothing.
SNAPSHOT_ACTION = "snapshot"
# The owner's explicit recovery from a divergence (`repair`): the ONLY way a registry whose history
# no longer matches its file may move again. Its modes are the owner's choice, never a default.
REPAIR_ACTION = "repair"
REPAIR_MODES = ("restore", "attest")
REPAIR_MARKER = ("owner repair: the registry's file no longer continued the recorded permit "
                 "history and the owner chose this recovery explicitly")
LEGACY_SNAPSHOT_MARKER = ("legacy snapshot: the current registry state only — the transitions "
                          "before this point were never journaled and are UNPROVEN, never invented")
GENESIS_HASH = "0" * 64
# The permit fields the ledger does NOT hash. `owner_authorized` is a hand-editable annotation and
# is never hashed; for a permit that carries it, `LEDGER_AUTHORIZATION_FIELDS` may additionally be
# read as part of that annotation (see `_annotation_amendment`) because the run-bound
# `owner_authorizations` note — not the editable field — is the decision (see
# `_verdict_order_problems`). Every other field is history.
LEDGER_ANNOTATION_FIELDS = frozenset({"owner_authorized"})
LEDGER_AUTHORIZATION_FIELDS = frozenset({"evidence", "verdict_at", "verdict_at_ms"})
NOTE_STAMP = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z$")
# The group-key PREFIX of a binding made BEFORE permits recorded their CLI session: `bound_at`
# proves it is not the audited session's but never WHICH earlier session made it, so each such
# binding gets a group of its OWN — a collision between two of them would be asserted, not proven
# (`createdAt` cannot separate two OVERLAPPING sessions).
UNIDENTIFIED_SESSION_PREFIX = "session:<unidentified>:"


class PermitError(ValueError):
    """An input this script cannot honour: a message + exit 2, never a traceback."""


class PermitDegraded(RuntimeError):
    """There is no session wire to audit (exit 3): nothing was proven either way."""


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and the verdicts survive a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def _now() -> tuple[str, int]:
    """`(ISO timestamp, epoch milliseconds)` of the moment a record is written."""
    moment = datetime.datetime.now(tz=datetime.timezone.utc)
    return moment.isoformat(timespec="seconds"), int(moment.timestamp() * 1000)


# -------------------------------------------------------------------------------------------- input

def _checked_repo(repo: str | pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(os.path.abspath(str(repo)))
    if not root.is_dir():
        raise PermitError(f"repository root does not exist: {root}")
    return root


def plan_text(root: pathlib.Path) -> str:
    """The approved plan's text; a missing plan is an actionable error (there is nothing to check)."""
    path = root / PLAN_REL
    if not path.is_file():
        raise PermitError(f"no approved plan at {path}: a permit answers a PLAN task, so the plan "
                          f"must exist before any delegation is permitted")
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PermitError(f"cannot read {path}: {exc}") from exc


def plan_tasks(root: pathlib.Path) -> dict[str, list[str]]:
    """`{task_id: [declared file, ...]}` of the approved plan's DAG.

    A plan line `- task_09: ... files: a.py, b.py; deps: [...]` declares the files that task may
    touch; a task whose entry carries no `files:` field maps to an EMPTY list, which the audit treats
    as "the plan does not say", never as "anything is allowed".
    """
    tasks: dict[str, list[str]] = {}
    current: str | None = None
    for line in plan_text(root).splitlines():
        match = TASK_LINE.match(line)
        if match:
            current = match.group("id")
            tasks.setdefault(current, [])
            body = match.group("rest")
        elif current is not None and line.startswith((" ", "\t")) and line.strip():
            body = line.strip()                     # a wrapped continuation of the same entry
        else:
            current = None
            continue
        files = FILES_FIELD.search(body)
        if files and current is not None:
            declared = [item.strip() for item in files.group("files").split(",") if item.strip()]
            tasks[current] = declared
    return tasks


def pipeline_run_id(root: pathlib.Path) -> str:
    """The run id of the WIP checkpoint, format-checked (a permit belongs to exactly one run)."""
    path = root / PIPELINE_REL
    if not path.is_file():
        raise PermitError(f"no WIP checkpoint at {path}: the flow writes it (with the run_id) at the "
                          f"start of a run")
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = RUN_ID_LINE.match(line.rstrip())
            if match:
                run_id = match.group(1).strip().strip("'\"")
                if RUN_ID_RE.match(run_id):
                    return run_id
                raise PermitError(f"{path} carries run_id {run_id!r}, which is not "
                                  f"YYYYMMDD-<8 lowercase hex> (scripts/run_id.py gen computes it)")
    except OSError as exc:
        raise PermitError(f"cannot read {path}: {exc}") from exc
    raise PermitError(f"{path} declares no run_id: a permit must belong to exactly one run")


def _authorization_notes(root: pathlib.Path) -> list[str]:
    """Every `owner_authorizations:` list item of THIS run's checkpoint (its journal of decisions)."""
    path = root / PIPELINE_REL
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PermitError(f"cannot read {path}: {exc}") from exc
    notes: list[str] = []
    inside = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            inside = AUTHORIZATIONS_HEADER.match(line.strip()) is not None
            continue
        item = AUTHORIZATION_ITEM.match(line) if inside else None
        if item:
            notes.append(item.group("note"))
    return notes


def authorized_permit_ids(root: pathlib.Path) -> set[str]:
    """The permit ids THIS run's checkpoint independently records as owner-authorized.

    `owner_authorizations:` in `.code-factory/state/pipeline.yaml` is the run's journal of owner
    decisions (`delegation_gate.py` appends to it). A note naming `permit=<id>` is the ONLY thing
    that can discharge a permit's own `owner_authorized` flag: the flag lives in the hand-editable
    `permits.yaml`, so a self-attested boolean alone is neither evidence nor a decision. The
    checkpoint is run-bound (its `run_id` is compared with the permits file before any spawn is
    evaluated), so an authorization of ANOTHER run cannot authorize this one.
    """
    ids: set[str] = set()
    for note in _authorization_notes(root):
        for token in note.split():
            if token.startswith("permit=") and len(token) > len("permit="):
                ids.add(token[len("permit="):].strip("'\""))
    return ids


def _note_stamp_ms(note: str) -> int | None:
    """The millisecond stamp a note OPENS with (`<ISO>Z ...`), or None when it carries none.

    `delegation_gate.py` writes `2026-11-05T16:59:25Z role=... mode=hitl`; the stamp is what makes
    the decision ORDERABLE against the spawn it excuses, so an undated note is unprovable.
    """
    head = (note.split() or [""])[0]
    match = NOTE_STAMP.match(head)
    if not match:
        return None
    try:
        moment = datetime.datetime.strptime(match.group("stamp"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return int(moment.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _timestamp_ms(value: object) -> int | None:
    """A recorded moment as epoch MILLISECONDS, or None when the value is not a readable stamp.

    The factory writes its own moments as ISO-8601 (`_now()` -> `2026-11-23T07:10:42+00:00`), while
    the CLI's session state records the same kind of moment as a bare epoch-millisecond number, so
    both spellings are read. Anything else — a bool, a string no parser accepts, NaN, an infinity —
    is UNREADABLE and stays None: a moment this gate cannot place is never guessed.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return int(stamp.timestamp() * 1000)


def authorization_stamps(root: pathlib.Path) -> dict[str, int | None]:
    """`{permit id: note stamp in ms or None}` for every authorization note of this run."""
    stamps: dict[str, int | None] = {}
    for note in _authorization_notes(root):
        stamp = _note_stamp_ms(note)
        for token in note.split():
            if token.startswith("permit=") and len(token) > len("permit="):
                permit_id = token[len("permit="):].strip("'\"")
                stamps[permit_id] = stamp if permit_id not in stamps else stamps[permit_id] or stamp
    return stamps


def _normalize_scope(root: pathlib.Path, raw: str) -> str:
    """One confined repo-relative scope path (a trailing `/` marks a directory and is dropped)."""
    text = (raw or "").strip().replace("\\", "/").rstrip("/")
    try:
        return confined_relpath(root, text)
    except ManifestError as exc:
        raise PermitError(str(exc)) from exc


def _within_plan(scope: str, declared: list[str]) -> bool:
    """Is `scope` EQUAL TO or BELOW one of the plan task's declared entries?

    The plan task grants a scope; a permit may narrow it, never widen it. So a permit on a FILE is
    inside a plan entry that declares that file or an ancestor DIRECTORY of it, and a permit on a
    DIRECTORY is inside a plan entry that declares the same directory or one of its ancestors — a
    permit on `src/` under a plan entry of `src/main.py` would authorise files the plan never
    mentions, which is exactly what the containment has to refuse.
    """
    for entry in declared:
        base = entry.rstrip("/")
        if scope == base or scope.startswith(base + "/"):
            return True
    return False


def _outside_plan(scopes: list[str], declared: list[str]) -> list[str]:
    """The permit scopes that are neither equal to nor beneath a declared plan entry."""
    return [scope for scope in scopes if not _within_plan(scope, declared)]


def _validate_role(role: str) -> str:
    if role == "main" or role not in ROLES:
        raise PermitError(f"role {role!r} is not a registered delegate role: the factory has "
                          f"{', '.join(ROLES)} (and `main` is the session itself, never a "
                          f"delegation)")
    return role


def _validate_permit_id(value: str, label: str = "permit id") -> str:
    if not PERMIT_ID_RE.match(value or ""):
        raise PermitError(f"the {label} must be a non-empty identifier ([A-Za-z0-9._-]+), got "
                          f"{value!r}")
    return value


# ------------------------------------------------------------------------------------------ storage

def _registry_paths(root: pathlib.Path,
                    launch_id: str | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    """`(permits, journal)` of the registry `root` addresses: keyed for a LAUNCH-scoped one.

    `launch_id=None` is the run's registry (and the launch-only legacy one a pre-key run left): the
    documented unkeyed names. A launch id names THAT launch's own pair, so two factories in one
    launch folder never read or rewrite each other's permits and permit history.
    """
    if launch_id is None:
        return root / PERMITS_REL, root / LEDGER_REL
    state = root / PERMITS_REL.parent
    return (state / LAUNCH_PERMITS_FMT.format(launch_id=launch_id),
            state / LAUNCH_LEDGER_FMT.format(launch_id=launch_id))


def _empty(run_id: str) -> dict:
    return {"run_id": run_id, "permits": []}


def read_permits(root: pathlib.Path, launch_id: str | None = None) -> dict:
    """The parsed permits file; an absent/malformed/ill-shaped one is an input error (exit 2)."""
    path, _ledger = _registry_paths(root, launch_id)
    if not path.is_file():
        where = (f"init --launch-dir {root} --launch-id {launch_id}" if launch_id is not None
                 else f"init --repo {root}")
        raise PermitError(f"no permits file at {path}: run `permit_gate.py {where}` first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermitError(f"{path} is not readable JSON (permits.yaml is JSON-compatible YAML): "
                          f"{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("permits"), list):
        raise PermitError(f"{path} must be an object with a 'permits' list")
    # `run_id` may be EMPTY: a launch-scoped registry is created before the run exists and is bound
    # once, at activation (`bind-run`). Anything non-empty must be a real run id.
    recorded_run = data.get("run_id")
    if recorded_run not in (None, "") and not RUN_ID_RE.match(str(recorded_run)):
        raise PermitError(f"{path}: run_id {recorded_run!r} is not YYYYMMDD-<8 lowercase hex> "
                          f"(an unbound launch-scoped registry carries \"\")")
    for index, permit in enumerate(data["permits"]):
        _validate_permit_shape(path, index, permit)
    return data


def _validate_permit_shape(path: pathlib.Path, index: int, permit: object) -> None:
    """Type- and vocabulary-validate EVERY field of one loaded permit.

    The permits file is data on disk: it may have been written by hand or by an older version, and
    the audit joins on its fields (`agent_id` becomes a dictionary key, `scope` is iterated, the
    verdict is compared). A field of the wrong type must be a controlled input error HERE — never
    a crash deep inside the audit.
    """
    where = f"{path}: permits[{index}]"
    if not isinstance(permit, dict) or not isinstance(permit.get("permit_id"), str):
        raise PermitError(f"{where} must be an object with a 'permit_id'")
    kind = permit.get("kind", "plan")
    if kind not in PERMIT_KINDS:
        raise PermitError(f"{where}: kind must be one of {list(PERMIT_KINDS)}, got {kind!r}")
    for key in ("task_id", "role", "phase", "evidence"):
        if not isinstance(permit.get(key), str):
            raise PermitError(f"{where}: {key} must be a string, got {permit.get(key)!r}")
    if permit["role"] not in ROLES:
        raise PermitError(f"{where}: role {permit['role']!r} is not a registered factory role "
                          f"({', '.join(ROLES)})")
    if permit["phase"] not in PERMIT_PHASES:
        raise PermitError(f"{where}: phase {permit['phase']!r} is not a known lifecycle phase "
                          f"({', '.join(PERMIT_PHASES)})")
    for key in ("scope", "constraints"):
        value = permit.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise PermitError(f"{where}: {key} must be a list of strings, got {value!r}")
    verdict = permit.get("verdict")
    if verdict is not None and verdict not in VERDICTS:
        raise PermitError(f"{where}: verdict must be null or one of {list(VERDICTS)}, got "
                          f"{verdict!r}")
    for key in ("created_at", "verdict_at", "agent_id", "bound_at", "session_id"):
        value = permit.get(key)
        if value is not None and not isinstance(value, str):
            raise PermitError(f"{where}: {key} must be null or a SCALAR string, got {value!r}")
    stamp = permit.get("verdict_at_ms")
    if stamp is not None and (isinstance(stamp, bool) or not isinstance(stamp, (int, float))):
        raise PermitError(f"{where}: verdict_at_ms must be null or a number, got {stamp!r}")
    # A NaN/infinity FLOAT passes this shape check deliberately: it is a well-typed but unusable
    # stamp, and the AUDIT owns the "unreadable verdict time" violation (exit 1) for it.
    closed = permit.get("closed")
    if closed is not None and (not isinstance(closed, dict)
                               or not isinstance(closed.get("at"), str)
                               or not isinstance(closed.get("reason"), str)):
        raise PermitError(f"{where}: closed must be null or an object with string 'at' and "
                          f"'reason', got {closed!r}")
    override = permit.get("owner_authorized")
    if override is not None and not isinstance(override, bool):
        raise PermitError(f"{where}: owner_authorized must be null or a bool, got {override!r}")


def _canonical(value: object) -> str:
    """The canonical serialization the ledger hashes: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def permit_projection(permit: dict) -> dict:
    """The permit fields the ledger records: every field except the hand-editable annotation."""
    return {key: value for key, value in permit.items() if key not in LEDGER_ANNOTATION_FIELDS}


def state_projection(data: dict) -> dict:
    """The recorded form of one state: `{run_id, permits}` in the strict projection."""
    return {"run_id": data.get("run_id", ""),
            "permits": [permit_projection(permit) for permit in data.get("permits", [])]}


def state_hash(data: dict) -> str:
    """`sha256` of the canonical `{run_id, permits}` projection of one registry state."""
    return hashlib.sha256(_canonical(state_projection(data)).encode("utf-8")).hexdigest()


def read_ledger(root: pathlib.Path, launch_id: str | None = None) -> list[dict]:
    """The parsed ledger lines; an absent journal is an EMPTY chain, an unreadable one is exit 2."""
    path = _registry_paths(root, launch_id)[1]
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PermitError(f"cannot read the permit ledger {path}: {exc}") from exc
    entries: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PermitError(f"{path}:{number} is not readable JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise PermitError(f"{path}:{number} is not a JSON object")
        entries.append(entry)
    return entries


def _entry_hash(entry: dict) -> str:
    """`sha256` of the line's own chain fields (its `hash` field is not part of its own hash)."""
    payload = {key: entry.get(key) for key in LEDGER_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _chain_problems(entries: list[dict], label: str | None = None) -> list[str]:
    """Why the chain itself is broken: an altered line, a broken link, a gap, a bad field shape."""
    problems: list[str] = []
    expected_prev = GENESIS_HASH
    name = label or LEDGER_REL.as_posix()
    for position, entry in enumerate(entries, 1):
        label = f"{name} line {position}"
        seq = entry.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            problems.append(f"permit ledger integrity: {label} carries no readable sequence number "
                            f"({seq!r})")
            continue
        if seq != position:
            problems.append(f"permit ledger integrity: {label} is numbered {seq}, so a transition "
                            f"was removed from the chain (a gap is a rewritten history)")
        for key in ("prev", "run_id", "action", "at", "state"):
            if not isinstance(entry.get(key), str):
                problems.append(f"permit ledger integrity: {label} carries no readable {key} "
                                f"({entry.get(key)!r})")
        if entry.get("permit_id") is not None and not isinstance(entry.get("permit_id"), str):
            problems.append(f"permit ledger integrity: {label} carries an unreadable permit_id "
                            f"({entry.get('permit_id')!r})")
        recorded = entry.get("doc")
        if not isinstance(recorded, dict) or not isinstance(recorded.get("permits"), list):
            problems.append(f"permit ledger integrity: {label} carries no readable recording of "
                            f"the state it produced ({recorded!r})")
        if entry.get("action") not in LEDGER_ACTIONS:
            problems.append(f"permit ledger integrity: {label} records the unknown transition "
                            f"{entry.get('action')!r}")
        if entry.get("note") is not None and not isinstance(entry.get("note"), str):
            problems.append(f"permit ledger integrity: {label} carries an unreadable note "
                            f"({entry.get('note')!r})")
        if entry.get("prev") != expected_prev:
            problems.append(f"permit ledger integrity: {label} does not continue the previous "
                            f"transition (its prev link is {str(entry.get('prev'))[:12]}…, the "
                            f"chain's head is {expected_prev[:12]}…): the history was edited or "
                            f"re-ordered")
        if entry.get("hash") != _entry_hash(entry):
            problems.append(f"permit ledger integrity: {label} does not match its own hash — the "
                            f"line was tampered with after it was appended")
        expected_prev = str(entry.get("hash"))
    return problems


def _empty_run_rebind(head: dict, data: dict) -> bool:
    """A new run taking over an EMPTY registry: the only transition that changes `run_id` alone.

    The recorded line must prove the registry held ZERO permits (re-hash its permits list under the
    run it recorded) — otherwise an emptied file could be re-bound to a fresh run and its history
    laundered through an `init`.
    """
    if data.get("permits"):
        return False
    return state_hash({"run_id": head.get("run_id"), "permits": []}) == head.get("state")


def ledger_problems(root: pathlib.Path, *, launch_id: str | None = None,
                    allow_empty_rebind: bool = False) -> list[str]:
    """Every way this registry's history is not the append-only one the run recorded.

    An absent journal with an EMPTY registry is the pre-first-write state (nothing to lose yet); an
    absent journal with permits in it is UNPROVEN history, which the factory reports rather than
    adopts. A journal whose head does not equal the file on disk is a rewritten ledger.
    """
    path, ledger = _registry_paths(root, launch_id)
    entries = read_ledger(root, launch_id)
    problems = _chain_problems(entries, ledger.as_posix())
    if not entries:
        if path.is_file():
            recorded = read_permits(root, launch_id)
            if recorded["permits"]:
                problems.append(
                    f"permit ledger integrity: {path} lists {len(recorded['permits'])} permit(s) "
                    f"but {ledger.as_posix()} records no history — this registry predates the "
                    f"append-only chain, so its transitions cannot be proven. A run must attest it "
                    f"as it stands with `permit_gate.py snapshot-legacy --repo <root>` (ONE marked "
                    f"snapshot of the CURRENT state; it records no earlier transition and claims "
                    f"none), never adopt or re-initialize it silently")
        return problems
    head = entries[-1]
    if not path.is_file():
        problems.append(
            f"permit ledger integrity: {path} is missing while {ledger.as_posix()} records "
            f"{len(entries)} transition(s) — deleting the registry does not delete the run's "
            f"permit history, and a re-created file is not that history")
        return problems
    current = read_permits(root, launch_id)
    strict = state_hash(current)
    if head.get("state") != strict and not _annotation_amendment(root, head, current) \
            and not (allow_empty_rebind and _empty_run_rebind(head, current)):
        problems.append(
            f"permit ledger integrity: {path} no longer continues the run's recorded permit "
            f"history (the ledger's head hashes to {str(head.get('state'))[:12]}…, the file on "
            f"disk to {strict[:12]}…) — a reset, a truncated tail or an edited "
            f"record is a rewritten history, never a permitted transition")
    return problems


def _annotation_amendment(root: pathlib.Path, head: dict, current: dict) -> bool:
    """Is the file on disk the recorded state PLUS one legitimate owner annotation?

    The ONE difference a hand-editable file is allowed to show is the annotation a run-bound
    `owner_authorizations` note is the real decision for: `owner_authorized` together with the
    evidence/stamps of the delegation whose verdict could only be recorded after it ran. The
    recorded projection is compared field by field, so ANY other difference — a verdict, an agent
    id, a scope, a closure, a timestamp of an unannotated permit — is a rewritten record, not an
    amendment. The comparison is PER PERMIT: an ORDINARY permit in the same registry is history and
    must still be byte-for-byte the recorded projection, so authorizing one bootstrap never demands
    that every other permit be annotated too (and never lets one be edited). At least one permit
    must actually be annotated — a difference the note does not explain is no amendment. The note
    must exist: an annotation this run never decided on is a forged flag, and the ordering of that
    note against the spawn is `_verdict_order_problems`' business.
    """
    recorded = head.get("doc")
    if not isinstance(recorded, dict) or not isinstance(recorded.get("permits"), list):
        return False
    if recorded.get("run_id") != current.get("run_id"):
        return False
    before, now = recorded["permits"], current["permits"]
    if len(before) != len(now):
        return False
    notes = authorization_stamps(root)
    amended = False
    for was, is_now in zip(before, now):
        if not isinstance(was, dict) or not isinstance(is_now, dict) \
                or was.get("permit_id") != is_now.get("permit_id"):
            return False
        if is_now.get("owner_authorized") is not True:
            # An ORDINARY permit is history: its recorded fields may not differ in any way.
            if "owner_authorized" in is_now or permit_projection(was) != permit_projection(is_now):
                return False
            continue
        if str(is_now.get("permit_id")) not in notes:
            return False
        for key in set(was) | set(is_now):
            if key in LEDGER_ANNOTATION_FIELDS or key in LEDGER_AUTHORIZATION_FIELDS:
                continue
            if was.get(key) != is_now.get(key):
                return False
        amended = True
    return amended


def _require_ledger(root: pathlib.Path, *, launch_id: str | None = None,
                    allow_empty_rebind: bool = False) -> None:
    """Refuse a write on a registry whose history does not continue the recorded chain."""
    problems = ledger_problems(root, launch_id=launch_id, allow_empty_rebind=allow_empty_rebind)
    if problems:
        raise PermitError("; ".join(problems))


def _append_line(path: pathlib.Path, line: str) -> None:
    """Append ONE line to the journal — the write half of the journal transaction (see below)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(line)


def _rollback_ledger(path: pathlib.Path, previous: bytes | None,
                     failure: BaseException) -> None:
    """Undo a PARTIAL journal append; a failed undo is a LOUD critical error, never swallowed.

    A short write leaves a truncated line at the tail, and the chain check would then report the
    run's own half-written history as corruption — the run would be locked out of its registry by
    its own failed command. So the journal is restored to the byte image read BEFORE the append, and
    a journal that did not exist yet is removed: the retried command must find exactly the history
    it had. A path that is not a regular file carried no bytes to undo (the append never wrote one).
    """
    try:
        if previous is None:
            if path.is_file():
                path.unlink()
        elif not path.is_file() or path.read_bytes() != previous:
            _replace_atomic(path, previous, "the permit ledger")
    except (OSError, PermitError) as exc:
        raise PermitError(
            f"CRITICAL: a partial transition was left in the permit ledger {path} ({failure}) and "
            f"the journal ROLLBACK failed too ({exc}): the recorded history no longer ends on a "
            f"chained entry. Restore it explicitly with `permit_gate.py repair --repo <root> "
            f"--mode restore` and do NOT continue the run on the current state") from failure


def _append_ledger(root: pathlib.Path, action: str, permit_id: str | None, data: dict,
                   note: str | None = None, launch_id: str | None = None) -> None:
    """Append the transition for the state just written; a filesystem failure is exit 2.

    The append itself is the second half of ONE transaction: a fault in the middle of the write
    leaves a partial line behind, so the journal's byte image is taken first and restored on
    failure (see `_rollback_ledger`) — a failed transition must be absolutely invisible to the
    chain, never a corrupt tail the run then has to work around.
    """
    path = _registry_paths(root, launch_id)[1]
    entries = read_ledger(root, launch_id)
    previous = entries[-1] if entries else {}
    stamp, _ms = _now()
    seq = int(previous.get("seq") or 0) + 1
    entry = {"seq": seq, "prev": str(previous.get("hash") or GENESIS_HASH),
             "run_id": str(data.get("run_id", "")), "action": action, "permit_id": permit_id,
             "at": stamp, "note": note, "state": state_hash(data), "doc": state_projection(data)}
    entry["hash"] = _entry_hash(entry)
    try:
        before = path.read_bytes() if path.is_file() else None
    except OSError as exc:
        raise PermitError(f"cannot read the permit ledger {path} before appending to it: "
                          f"{exc}") from exc
    try:
        _append_line(path, _canonical(entry) + "\n")
    except BaseException as exc:
        _rollback_ledger(path, before, exc)
        if isinstance(exc, PermitError):
            raise
        raise PermitError(f"cannot append to the permit ledger {path}: {exc}") from exc


def _replace_atomic(path: pathlib.Path, payload: bytes, label: str) -> None:
    """Replace `path` with `payload` atomically: same-directory temp file plus `os.replace`."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    except OSError as exc:
        raise PermitError(f"cannot write {label} {path}: {exc}") from exc
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temp, path)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise PermitError(f"cannot write {label} {path} (the previous one is untouched): "
                          f"{exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise


def _rollback_state(path: pathlib.Path, previous: bytes | None, failure: BaseException,
                    ledger: pathlib.Path | None = None) -> None:
    """Undo a state write whose journal append failed; a failed undo is a LOUD critical error.

    The state file and the journal are ONE transaction, so a registry must never advance past the
    history the run recorded. `previous` is the byte image read BEFORE the replace: `None` means the
    run had no permits file yet (the first write), which is undone by DELETING the new file — a
    registry without its history is the divergence itself, and the retried command must find a clean
    slate instead of an unproven file to work around.
    """
    label = (ledger or (path.parent / LEDGER_REL.name)).as_posix()
    try:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            _replace_atomic(path, previous, "the permits file")
    except (OSError, PermitError) as exc:
        raise PermitError(
            f"CRITICAL: {path} was written but the matching transition could not be appended to "
            f"{label} ({failure}), and the ROLLBACK failed too ({exc}): the "
            f"registry now holds a transition its own history never recorded. Restore it "
            f"explicitly with `permit_gate.py repair --repo <root> --mode restore` and do NOT "
            f"continue the run on the current state") from failure


def _write_permits(root: pathlib.Path, data: dict, action: str = "init",
                   permit_id: str | None = None,
                   allow_empty_rebind: bool = False,
                   note: str | None = None,
                   require_chain: bool = True,
                   launch_id: str | None = None) -> pathlib.Path:
    """Write the permits file deterministically and ATOMICALLY, then journal the transition.

    The ledger is verified FIRST (see THE LEDGER): a registry whose recorded history does not reach
    the file on disk is refused, so a reset or an edit can never be papered over by the next append.
    A filesystem failure is DATA: it names the path and the OS reason and exits 2, and the permits
    file the run already had stays byte-identical (an audit must never read a half-written permit).

    The write and its journal append are ONE transaction: the byte image from before the replace is
    kept, and a failed append rolls the file back (see `_rollback_state`), so the state on disk
    always continues the history the run recorded.
    """
    if require_chain:
        _require_ledger(root, launch_id=launch_id, allow_empty_rebind=allow_empty_rebind)
    payload = {"run_id": data.get("run_id", ""), "permits": data.get("permits", [])}
    path, ledger = _registry_paths(root, launch_id)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    try:
        previous = path.read_bytes() if path.is_file() else None
    except OSError as exc:
        raise PermitError(f"cannot read the permits file {path} before writing it: {exc}") from exc
    _replace_atomic(path, text.encode("utf-8"), "the permits file")
    try:
        _append_ledger(root, action, permit_id, payload, note=note, launch_id=launch_id)
    except BaseException as exc:
        _rollback_state(path, previous, exc, ledger)
        raise
    return path


def _permit(data: dict, permit_id: str) -> dict:
    for permit in data["permits"]:
        if permit.get("permit_id") == permit_id:
            return permit
    known = ", ".join(sorted(str(permit.get("permit_id")) for permit in data["permits"])) or "none"
    raise PermitError(f"no permit {permit_id!r} in the file (known: {known})")


# -------------------------------------------------------------------------------------- subcommands

def _parsed_task(root: pathlib.Path) -> None:
    """Require the run's task to exist and to PARSE — the anchor of the TASK-answering permits.

    `analyzer` and `planner` answer the task itself, so their bootstrap permit is only meaningful
    against a task that parses. The SUPERVISOR is not anchored here: it is launched BEFORE Phase 0
    parses the task, and its authority is the RUN (`_run_authority`).
    """
    path = root / TASK_REL
    if not path.is_file():
        raise PermitError(f"no task at {path}: a bootstrap permit is validated against the parsed "
                          f"task the run answers, so the task must exist before any pre-plan "
                          f"delegation is permitted")
    try:
        import task_parser  # noqa: PLC0415  (deliberately lazy: only bootstrap permits need it)
    except ImportError as exc:
        raise PermitError(f"the bootstrap validation reuses task_parser.py, which cannot be "
                          f"imported: {exc}") from exc
    try:
        task_parser.parse_file(path)
    except task_parser.TaskError as exc:
        raise PermitError(f"{path} does not parse as a valid task: {exc}") from exc
    except OSError as exc:
        raise PermitError(f"cannot read {path}: {exc}") from exc


def _run_authority(root: pathlib.Path) -> str:
    """The RUN a pre-parse supervisor permit answers: the WIP checkpoint's validated `run_id`.

    The supervisor is launched at run start — before Phase 0 parses the task — so the task cannot be
    its anchor; the run's own identity is the only authority that exists at that moment. The id is
    format-checked here and the permits file's `run_id` is compared with it at the audit, so this is
    a real, auditable binding (the run's checkpoint), never a waiver: it applies to `supervisor`
    bootstrap permits only and to nothing else.
    """
    return pipeline_run_id(root)


def _validate_launch_id(launch_id: str) -> str:
    """`--launch-id` becomes a filename component: only the documented nonce shape is legitimate."""
    if not LAUNCH_ID_RE.fullmatch(launch_id or ""):
        raise PermitError(f"--launch-id must be the launch nonce `supervisor_watchdog.py begin "
                          f"--launch-dir <dir>` minted (^\\d{{8}}-\\d{{6}}-[0-9a-f]{{6}}$), got "
                          f"{launch_id!r}: it names this launch's OWN registry file, so separators, "
                          f"`..` and an empty value have no legitimacy")
    return launch_id


def _launch_watchdog():
    """The sibling `supervisor_watchdog` module (the ONE launch-bootstrap resolver)."""
    scripts = pathlib.Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import supervisor_watchdog  # noqa: PLC0415  (deliberately lazy: only launches need it)
    except ImportError as exc:
        raise PermitError(f"the launch-scoped registry reuses supervisor_watchdog.py's bootstrap "
                          f"resolver, which cannot be imported: {exc}") from exc
    return supervisor_watchdog


def launch_anchor(launch_dir: str | pathlib.Path,
                  launch_id: str | None = None) -> dict:
    """`{launch_dir, launch_id, begun_at, activated}` of the launch bootstrap a permit answers.

    `supervisor_watchdog.py begin --launch-dir <launch>` writes this record BEFORE any task or
    `run_id` exists, so it is the only authority available at that moment. The lookup goes through
    `supervisor_watchdog.resolve_bootstrap` (ONE resolver, ONE contract): an explicit `launch_id`
    names exactly that launch, and without it the folder resolves only while exactly ONE bootstrap
    is uncompleted — several open launches are a loud refusal, never a guess, because which run a
    permit belongs to must not be inferred. A missing/malformed bootstrap, an unknown launch id or
    an ambiguity is an actionable error: a launch-scoped registry is never created out of nothing.
    """
    root = pathlib.Path(os.path.abspath(str(launch_dir)))
    if not root.is_dir():
        raise PermitError(f"the launch directory does not exist: {root}")
    if launch_id is not None:
        _validate_launch_id(launch_id)
    watchdog = _launch_watchdog()
    try:
        resolved = watchdog.resolve_bootstrap(root, launch_id)
    except watchdog.WatchdogError as exc:
        raise PermitError(str(exc)) from exc
    data = resolved["bootstrap"]
    begun_at = data.get("begun_at")
    if not isinstance(begun_at, str) or not begun_at.strip():
        raise PermitError(f"{resolved['path']} carries no usable `begun_at`: a launch bootstrap "
                          f"without the moment it began cannot anchor a permit")
    return {"launch_dir": str(root), "launch_id": resolved["launch_id"],
            "begun_at": begun_at.strip(), "activated": data.get("activated")}


def _launch_key(root: pathlib.Path, anchor: dict, explicit: bool = False) -> str | None:
    """The launch id a launch-only registry is addressed by; `None` for a legacy unkeyed launch.

    A pre-key run left ONE unkeyed launch registry behind. It stays resumable exactly where it is —
    with no keyed registry of that launch beside it — because migrating live history would be the
    silent rewrite this gate exists to prevent. The legacy file is retired by the transfer. An
    EXPLICIT `--launch-id` is never softened that way: it names one launch's keyed records and
    nothing else, so a missing one is an error instead of a silent fallback.
    """
    key = anchor.get("launch_id")
    if key is None or explicit:
        return key
    keyed_permits = _registry_paths(root, key)[0]
    legacy_permits = root / PERMITS_REL
    if not keyed_permits.is_file() and legacy_permits.is_file():
        return None
    return key


def init(root: str | pathlib.Path | None = None,
         launch_dir: str | pathlib.Path | None = None,
         launch_id: str | None = None) -> dict:
    """Create the skeleton `{run_id, permits: []}`; a file that already lists permits is kept.

    Before Phase 0 there is no parsed task, no computed `run_id` AND no resolved `repo_path`, so the
    mandated order (`supervisor_watchdog.py begin` -> the supervisor permit -> `activate`) would
    otherwise be impossible. That registry is LAUNCH-ONLY: `--launch-dir` alone puts it in the launch
    directory, KEYED by the launch id its bootstrap carries (`permits.launch-<id>.yaml`, unbound)
    against that bootstrap's `begun_at`, and `bind-run` transfers it to the resolved repository at
    activation. `--repo` (alone, or with `--launch-dir`) keeps the run-anchored behaviour: the
    checkpoint decides the id.
    """
    if launch_id is not None and launch_dir is None:
        raise PermitError("init: --launch-id names a LAUNCH registry, so it needs --launch-dir "
                          "<dir> (the folder `supervisor_watchdog.py begin` recorded)")
    launch_only = root is None
    if launch_only:
        if launch_dir is None:
            raise PermitError("init needs --repo <root> (the run's repository) or --launch-dir <dir> "
                              "(the LAUNCH-ONLY pre-run registry: no target exists yet)")
        root = launch_dir
    root = _checked_repo(root)
    anchor = launch_anchor(launch_dir, launch_id) if launch_dir is not None else None
    key = (_launch_key(root, anchor, launch_id is not None)
           if launch_only and anchor is not None else None)
    pipeline = root / PIPELINE_REL
    if launch_only:
        run_id = ""                             # the launch is not the run: unbound until bind-run
    elif pipeline.is_file():
        run_id = pipeline_run_id(root)          # the run already exists: the checkpoint decides
    elif anchor is not None:
        run_id = ""                             # launch-scoped; `bind-run` binds it at activation
    else:
        run_id = pipeline_run_id(root)          # raises the documented "no WIP checkpoint" error
    path = _registry_paths(root, key)[0]
    note = None if anchor is None else (
        f"launch-scoped registry: anchored to the launch bootstrap at {anchor['launch_dir']} "
        f"(launch id {anchor['launch_id'] or 'legacy, unkeyed'}, begun_at {anchor['begun_at']}); "
        f"unbound until `bind-run`")
    if path.is_file():
        existing = read_permits(root, key)
        if existing["permits"]:
            raise PermitError(f"{path} already lists {len(existing['permits'])} permit(s): it is "
                              f"created ONCE per run — a second init would forget them")
        if existing.get("run_id", "") == run_id:
            # "Already done" is NOT a licence to bless a registry whose file no longer continues the
            # run's recorded history: the shortcut must look at the journal before it answers.
            _require_ledger(root, launch_id=key)
            return {"status": "unchanged", "run_id": run_id, "permits": str(path)}
        _write_permits(root, _empty(run_id), action="reinit", allow_empty_rebind=True, note=note,
                       launch_id=key)
        return {"status": "reinitialized", "run_id": run_id, "permits": str(path)}
    _write_permits(root, _empty(run_id), action="init", note=note, launch_id=key)
    return {"status": "created", "run_id": run_id, "permits": str(path)}


def add(root: str | pathlib.Path | None = None, permit_id: str = "", task_id: str = "",
        role: str = "", phase: str = "", scopes: list[str] | None = None,
        constraints: list[str] | None = None, kind: str = "plan",
        launch_dir: str | pathlib.Path | None = None,
        launch_id: str | None = None) -> dict:
    """Register ONE permit (validated against the plan — or, bootstrap, the task or the launch).

    With `--launch-dir` alone the permit belongs to the LAUNCH-ONLY pre-run registry (no resolved
    `repo_path` exists yet), and it is written into THAT launch's own keyed registry; `--repo`
    (alone or with `--launch-dir`) names the run's repository.
    """
    if launch_id is not None and launch_dir is None:
        raise PermitError("add: --launch-id names a LAUNCH registry, so it needs --launch-dir <dir>")
    launch_only = root is None
    if launch_only:
        if launch_dir is None:
            raise PermitError("add needs --repo <root> or the LAUNCH-ONLY --launch-dir <dir>")
        root = launch_dir
    root = _checked_repo(root)
    _validate_permit_id(permit_id)
    _validate_role(role)
    if kind not in PERMIT_KINDS:
        raise PermitError(f"unknown kind {kind!r}: a permit is one of {', '.join(PERMIT_KINDS)}")
    if phase not in PERMIT_PHASES:
        raise PermitError(f"unknown phase {phase!r}: a permit names one of "
                          f"{', '.join(PERMIT_PHASES)}")
    tasks: dict[str, list[str]] = {}
    anchor: dict | None = None
    key: str | None = None
    if kind == "bootstrap":
        if role not in BOOTSTRAP_ROLES:
            raise PermitError(f"a bootstrap permit is limited to the pre-plan read-only roles "
                              f"({', '.join(sorted(BOOTSTRAP_ROLES))}): role {role!r} touches the "
                              f"implementation, so it needs an approved-plan task and a plan "
                              f"permit")
        if task_id != BOOTSTRAP_TASK_ID:
            raise PermitError(f"a bootstrap permit answers the TASK itself: --task-id must be "
                              f"{BOOTSTRAP_TASK_ID!r} (plan task ids exist only once the plan is "
                              f"approved), got {task_id!r}")
        if role == SUPERVISOR_ROLE:
            # The watchdog is launched BEFORE Phase 0 parses the task — and, on a fresh run, before
            # a `run_id` exists. Its authority is the RUN's checkpoint when there is one, otherwise
            # the launch bootstrap `begin` wrote. `analyzer`/`planner` keep the parsed-task anchor.
            constraints = list(constraints or [])
            if launch_dir is not None:
                anchor = launch_anchor(launch_dir, launch_id)
                if launch_only:
                    key = _launch_key(root, anchor, launch_id is not None)
                constraints.append(
                    f"launch-authority anchor: launch {anchor['launch_dir']} (launch id "
                    f"{anchor['launch_id'] or 'legacy, unkeyed'}, begun_at {anchor['begun_at']}); "
                    f"the registry is unbound until `bind-run`")
            else:
                if launch_id is not None:
                    raise PermitError("add: --launch-id names a LAUNCH registry, so it needs "
                                      "--launch-dir <dir>")
                run_authority = _run_authority(root)
                constraints.append(
                    f"run-authority anchor: run {run_authority} (the supervisor is launched "
                    f"before the task is parsed, so the WIP checkpoint is its anchor)")
        else:
            _parsed_task(root)
            if launch_dir is not None:
                raise PermitError(f"--launch-dir anchors the PRE-RUN supervisor's permit only: "
                                  f"role {role!r} answers the parsed task, so it needs the task and "
                                  f"not the launch bootstrap")
    else:
        if launch_dir is not None:
            raise PermitError(f"--launch-dir is only valid with --kind bootstrap --role "
                              f"{SUPERVISOR_ROLE}: a plan permit answers an approved plan and the "
                              f"run it belongs to")
        tasks = plan_tasks(root)
        if task_id not in tasks:
            raise PermitError(f"task id {task_id!r} does not exist in the approved plan "
                              f"({PLAN_REL.as_posix()}): a permit may only answer a planned task "
                              f"({len(tasks)} task(s) known)")
    scopes_in = scopes or []
    normalized = [_normalize_scope(root, scope) for scope in scopes_in]
    duplicated = sorted({scope for scope in normalized if normalized.count(scope) > 1})
    if duplicated:
        raise PermitError(f"scope lists {', '.join(duplicated)} more than once")
    if not normalized and role not in READ_ONLY_ROLES:
        raise PermitError(f"role {role!r} changes files, so its permit needs at least one --scope "
                          f"(empty scope is allowed only for the read-only/business-test roles: "
                          f"{', '.join(sorted(READ_ONLY_ROLES))})")
    if kind == "plan":
        declared = tasks[task_id]
        if not declared:
            raise PermitError(f"plan task {task_id!r} declares no files, so the scope of this "
                              f"permit cannot be proven a subset of it: name the files in "
                              f"{PLAN_REL.as_posix()} first")
        outside = _outside_plan(normalized, declared)
        if outside:
            raise PermitError(f"scope {', '.join(outside)} is not declared by plan task {task_id!r}"
                              f" ({', '.join(declared)}): a permit may narrow the plan task's "
                              f"scope, never widen it")
    data = read_permits(root, key)
    if anchor is not None and data.get("run_id"):
        raise PermitError(
            f"{_registry_paths(root, key)[0]} is already bound to run {data['run_id']!r}: a "
            f"launch-scoped permit belongs to the PRE-RUN registry, and a bound registry gets its "
            f"permits through the run (drop --launch-dir)")
    if any(permit.get("permit_id") == permit_id for permit in data["permits"]):
        raise PermitError(f"permit id {permit_id!r} is already used: a permit id is unique")
    created, _ms = _now()
    permit = {"permit_id": permit_id, "kind": kind, "task_id": task_id, "role": role,
              "phase": phase,
              "scope": normalized, "constraints": [str(text).strip() for text in constraints or []
                                                   if str(text).strip()],
              "created_at": created, "verdict": None, "evidence": "", "verdict_at": None,
              "verdict_at_ms": None, "agent_id": None, "bound_at": None, "closed": None}
    data["permits"].append(permit)
    path = _write_permits(root, data, action="add", permit_id=permit_id, launch_id=key)
    return {"status": "added", "permit": permit, "permits": str(path)}


def _registry_target(root: str | pathlib.Path | None,
                     launch_dir: str | pathlib.Path | None, command: str,
                     launch_id: str | None = None) -> tuple[pathlib.Path, str | None]:
    """The ONE registry a lifecycle command acts on, plus the launch key it addresses.

    Before the transfer the run's registry lives in the launch directory, so `verdict`/`bind` must
    act THERE (`--launch-dir`) — otherwise the supervisor's verdict and its spawn binding could not
    precede the delegation they permit. A launch-only registry is the one THAT launch owns (its
    keyed file), resolved through the shared bootstrap resolver; the run's registry is unkeyed.
    Naming both roots is refused: a lifecycle command records one transition, in one registry.
    """
    if launch_id is not None and launch_dir is None:
        raise PermitError(f"{command}: --launch-id names a LAUNCH registry, so it needs "
                          f"--launch-dir <dir>")
    if root is None:
        if launch_dir is None:
            raise PermitError(f"{command} needs --repo <root> or --launch-dir <dir>")
        anchor = launch_anchor(launch_dir, launch_id)
        directory = pathlib.Path(anchor["launch_dir"])
        return directory, _launch_key(directory, anchor, launch_id is not None)
    if launch_dir is not None:
        raise PermitError(f"{command} names ONE registry: pass --repo (the run's repository) or "
                          f"--launch-dir (the launch-only registry), never both")
    return _checked_repo(root), None


def verdict(root: str | pathlib.Path | None = None, permit_id: str = "", decision: str = "",
            evidence: str = "", launch_dir: str | pathlib.Path | None = None,
            launch_id: str | None = None) -> dict:
    """Record the supervisor's verdict (evidence mandatory; one verdict per permit)."""
    root, key = _registry_target(root, launch_dir, "verdict", launch_id)
    if decision not in VERDICTS:
        raise PermitError(f"verdict must be one of {list(VERDICTS)}, got {decision!r}")
    text = (evidence or "").strip()
    if not text:
        raise PermitError("--evidence is required: a verdict without the artifact or rule it rests "
                          "on cannot be audited (an allow especially: it authorises a delegation)")
    data = read_permits(root, key)
    permit = _permit(data, permit_id)
    if permit.get("verdict") is not None:
        raise PermitError(f"permit {permit_id!r} already carries the verdict "
                          f"{permit['verdict']!r}: one permit, one verdict (open a new permit for a "
                          f"re-judged delegation)")
    if permit.get("agent_id"):
        raise PermitError(f"permit {permit_id!r} is already bound to agent "
                          f"{permit['agent_id']!r}: a verdict cannot follow the spawn")
    stamp, stamp_ms = _now()
    permit.update(verdict=decision, evidence=text, verdict_at=stamp, verdict_at_ms=stamp_ms)
    path = _write_permits(root, data, action="verdict", permit_id=permit_id, launch_id=key)
    return {"status": "recorded", "permit_id": permit_id, "verdict": decision, "evidence": text,
            "verdict_at": stamp, "permits": str(path)}


def bind(root: str | pathlib.Path | None = None, permit_id: str = "", agent_id: str = "",
         launch_dir: str | pathlib.Path | None = None,
         launch_id: str | None = None) -> dict:
    """Bind the spawned agent id to an ALLOWED permit (unique within the run's CLI session)."""
    root, key = _registry_target(root, launch_dir, "bind", launch_id)
    if not AGENT_ID_RE.match(agent_id or ""):
        raise PermitError(f"--agent-id must be a non-empty identifier ([A-Za-z0-9._-]+), got "
                          f"{agent_id!r}")
    data = read_permits(root, key)
    permit = _permit(data, permit_id)
    if permit.get("closed"):
        raise PermitError(f"permit {permit_id!r} is closed as NOT executed: a closed permit cannot "
                          f"acquire an agent id")
    if permit.get("verdict") != "allow":
        raise PermitError(f"permit {permit_id!r} is not allowed (verdict {permit.get('verdict')!r}):"
                          f" only an ALLOWED permit may be bound to a spawned agent — a denied "
                          f"permit NEVER acquires an agent id")
    # One evidence source for both the collision test and the identity this binding RECORDS.
    run_session = _run_session_id(root)
    run_start = _run_session_start_ms(root)
    for other in data["permits"]:
        if other is not permit and other.get("agent_id") == agent_id:
            if _binding_session_key(other, run_start, run_session) is not None:
                # A DIFFERENT CLI session's delegation: agent ids restart at `agent-0` in every
                # session, so this session's own agent may carry the id that one used.
                continue
            raise PermitError(f"agent id {agent_id!r} is already bound to permit "
                              f"{other.get('permit_id')!r}: one agent, one permit per session")
    if permit.get("agent_id") == agent_id:
        _require_ledger(root, launch_id=key)    # an idempotent retry still verifies the history
        return {"status": "unchanged", "permit_id": permit_id, "agent_id": agent_id,
                "permits": str(_registry_paths(root, key)[0])}
    if permit.get("agent_id"):
        raise PermitError(f"permit {permit_id!r} is already bound to agent "
                          f"{permit['agent_id']!r}: a permit records the ONE agent it spawned")
    stamp, _ms = _now()
    permit.update(agent_id=agent_id, bound_at=stamp, session_id=run_session or None)
    path = _write_permits(root, data, action="bind", permit_id=permit_id, launch_id=key)
    return {"status": "bound", "permit_id": permit_id, "agent_id": agent_id,
            "session_id": permit["session_id"], "permits": str(path)}


def close(root: str | pathlib.Path, permit_id: str, reason: str) -> dict:
    """Mark an ALLOWED, never-spawned permit as NOT executed (the reason is mandatory)."""
    root = _checked_repo(root)
    text = (reason or "").strip()
    if not text:
        raise PermitError("--reason is required: an unused permit is closed WITH the reason it was "
                          "not executed")
    data = read_permits(root)
    permit = _permit(data, permit_id)
    if permit.get("verdict") != "allow":
        raise PermitError(f"permit {permit_id!r} is not an allowed permit (verdict "
                          f"{permit.get('verdict')!r}): a denied permit needs no closure")
    if permit.get("agent_id"):
        raise PermitError(f"permit {permit_id!r} already ran under agent {permit['agent_id']!r}: a "
                          f"permit that spawned is not 'not executed'")
    if permit.get("closed"):
        _require_ledger(root)               # an idempotent retry still verifies the history
        return {"status": "unchanged", "permit_id": permit_id,
                "permits": str(root / PERMITS_REL)}
    stamp, _ms = _now()
    permit["closed"] = {"at": stamp, "reason": text}
    path = _write_permits(root, data, action="close", permit_id=permit_id)
    return {"status": "closed", "permit_id": permit_id, "reason": text, "permits": str(path)}


def snapshot_legacy(root: str | pathlib.Path, note: str = "") -> dict:
    """Attest a PRE-JOURNAL registry exactly as it stands: ONE marked event, nothing invented.

    This is the only honest transition a run whose `permits.yaml` predates the journal can take.
    The recorded state is the file ON DISK at this moment, the stamp is NOW (never a back-dated
    verdict or spawn time), the marking says the earlier history is unproven, `permits.yaml` is not
    touched, and the single event is named `snapshot` so no reader can mistake it for an `init`, an
    `add`, a `verdict` or a `bind` that never happened. Everything the audit checks afterwards still
    applies: a snapshot attests WHICH records exist, never that they were permitted.
    """
    root = _checked_repo(root)
    path = root / PERMITS_REL
    ledger = root / LEDGER_REL
    if not path.is_file():
        raise PermitError(f"no permits file at {path}: there is no pre-journal registry to attest "
                          f"(a run without one starts its journal with `init`)")
    recorded = read_ledger(root)
    if recorded:
        raise PermitError(f"{ledger} already records {len(recorded)} transition(s): the registry's "
                          f"history is already being journaled, and a second legacy snapshot would "
                          f"only blur the point at which honest recording began (a snapshot is "
                          f"taken ONCE, before the first post-upgrade write)")
    data = read_permits(root)
    if not data["permits"]:
        raise PermitError(f"{path} lists no permit(s): an empty registry carries no pre-journal "
                          f"state to attest — `init` starts the journal instead")
    current = pipeline_run_id(root)
    if data["run_id"] != current:
        raise PermitError(f"{path} belongs to run {data['run_id']!r}, but the current pipeline run "
                          f"is {current!r}: a legacy snapshot attests THIS run's registry only")
    text = LEGACY_SNAPSHOT_MARKER
    extra = (note or "").strip()
    if extra:
        text = f"{text}; operator note: {extra}"
    _append_ledger(root, SNAPSHOT_ACTION, None, data, note=text)
    return {"status": "snapshot", "run_id": data["run_id"], "permits_count": len(data["permits"]),
            "permits": str(path), "ledger": str(ledger), "note": text}


def repair(root: str | pathlib.Path, mode: str = "", note: str = "") -> dict:
    """The owner's EXPLICIT recovery from a divergence — never a default, never a no-op.

    A registry whose file no longer continues the journal is refused by every write and by the
    finish audit, so it needs a deliberate way out. Without `--mode` this only REPORTS the
    divergence (exit 2, nothing written, the owner has not chosen yet). Two modes exist:

      restore  re-derive `permits.yaml` from the ledger head's recorded projection. The unjournaled
               transition — the one that never reached the journal — is LOST, deliberately: the
               journal is the history, and this is the state it recorded.
      attest   KEEP the file on disk and append ONE marked event re-anchoring the chain to it. The
               gap has to be explained, so `--note` is mandatory; the attestation records no
               transition that did not happen (`repair`, not an `init`/`add`/`verdict`/`bind`).

    Neither mode is reachable by omitting an argument, and neither invents an earlier transition.
    """
    root = _checked_repo(root)
    path = root / PERMITS_REL
    entries = read_ledger(root)
    chain = _chain_problems(entries)
    if chain:
        raise PermitError(
            f"the permit ledger {root / LEDGER_REL} does not verify, so no repair can be anchored "
            f"on it ({'; '.join(chain)}) — an edited chain is restored from the run's own "
            f"evidence, never re-anchored from a broken head")
    problems = ledger_problems(root)
    if not mode:
        if not problems:
            return {"status": "consistent", "permits": str(path), "ledger": str(root / LEDGER_REL),
                    "problems": []}
        raise PermitError(
            f"the registry {path} does not continue its permit history and the recovery is the "
            f"owner's explicit choice ({'; '.join(problems)}): pass `--mode restore` (re-derive "
            f"the file from the ledger head, LOSING the unjournaled transition) or `--mode attest "
            f"--note <why>` (keep the file and append ONE marked re-anchoring event)")
    if mode not in REPAIR_MODES:
        raise PermitError(f"repair --mode must be one of {list(REPAIR_MODES)}, got {mode!r}: a "
                          f"recovery is named, never inferred")
    if not problems:
        raise PermitError(f"{path} already continues its permit history: there is nothing to "
                          f"repair (a repair would only rewrite history that is intact)")
    if mode == "restore":
        return _repair_restore(root, entries, problems)
    text = (note or "").strip()
    if not text:
        raise PermitError("repair --mode attest needs --note <why>: the attested gap has to be "
                          "explained by the owner — an unexplained re-anchoring is exactly the "
                          "silent rewriting the ledger exists to prevent")
    data = read_permits(root)
    attestation = f"{REPAIR_MARKER} — attested as it stands; owner note: {text}"
    _append_ledger(root, REPAIR_ACTION, None, data, note=attestation)
    return {"status": "attested", "run_id": data.get("run_id") or None, "permits": str(path),
            "ledger": str(root / LEDGER_REL), "note": attestation, "problems": problems}


def _repair_restore(root: pathlib.Path, entries: list[dict],
                    problems: list[str]) -> dict:
    """Re-derive `permits.yaml` from the ledger head's recorded projection (one atomic write)."""
    if not entries:
        raise PermitError(f"the permit ledger {root / LEDGER_REL} records no transition, so there "
                          f"is no recorded state to restore: an unproven registry is attested with "
                          f"`snapshot-legacy`, never re-derived")
    head = entries[-1]
    recorded = head.get("doc") or {}
    restored = {"run_id": recorded.get("run_id", ""), "permits": recorded.get("permits", [])}
    if state_hash(restored) != head.get("state"):
        raise PermitError(
            f"the ledger head of {root / LEDGER_REL} does not carry a re-derivable state (it "
            f"hashes to {state_hash(restored)[:12]}…, the line records "
            f"{str(head.get('state'))[:12]}…): nothing is written — restore the run's registry by "
            f"hand and attest where the history actually ends")
    note = (f"{REPAIR_MARKER} — restore: re-derived from the ledger head; the unjournaled "
            f"transition is dropped")
    _write_permits(root, restored, action=REPAIR_ACTION, note=note, require_chain=False)
    return {"status": "restored", "run_id": restored["run_id"],
            "permits_count": len(restored["permits"]), "permits": str(root / PERMITS_REL),
            "ledger": str(root / LEDGER_REL), "note": note, "problems": problems}


def _copy_atomic(source: pathlib.Path, target: pathlib.Path) -> None:
    """Copy one file to `target` atomically (same-directory temp + `os.replace`)."""
    try:
        payload = source.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".",
                                        suffix=".tmp")
    except OSError as exc:
        raise PermitError(f"cannot copy {source} to {target}: {exc}") from exc
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temp, target)
    except OSError as exc:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise PermitError(f"cannot copy {source} to {target} (nothing was replaced): {exc}") from exc
    except BaseException:
        pathlib.Path(temp).unlink(missing_ok=True)
        raise


def _transferred_paths(root: pathlib.Path, run_id: str,
                       launch_id: str | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    """Where a transferred launch registry is RETIRED to (an archive, never a live fork).

    The archive keeps the launch's own name when the registry was keyed, so a folder that carried
    several launches still shows WHICH launch's history was retired under which run.
    """
    state = root / PERMITS_REL.parent
    if launch_id is None:
        return (state / f"permits.transferred-{run_id}.yaml",
                state / f"permits.ledger.transferred-{run_id}.jsonl")
    return (state / f"permits.launch-{launch_id}.transferred-{run_id}.yaml",
            state / f"permits.ledger.launch-{launch_id}.transferred-{run_id}.jsonl")


def _bind_in_place(root: pathlib.Path, run_id: str | None,
                   launch_id: str | None = None) -> dict:
    """Bind ONE registry to THIS run's checkpoint, once, atomically and journaled."""
    data = read_permits(root, launch_id)
    current = pipeline_run_id(root)                     # the checkpoint activation wrote
    wanted = (run_id or "").strip() or current
    if wanted != current:
        raise PermitError(f"the registry may only be bound to THIS run: --run-id {wanted!r} is not "
                          f"the current pipeline run {current!r} ({PIPELINE_REL.as_posix()})")
    path = _registry_paths(root, launch_id)[0]
    if data.get("run_id"):
        if data["run_id"] == current:
            _require_ledger(root, launch_id=launch_id)    # a retry still verifies the history
            return {"status": "unchanged", "run_id": current, "permits": str(path)}
        raise PermitError(f"{path} is already bound to run {data['run_id']!r}: ONE binding per "
                          f"registry — a later run must not inherit another run's permit history")
    data["run_id"] = current
    _write_permits(root, data, action="bind-run", launch_id=launch_id,
                   note=f"launch-scoped registry bound to run {current} at activation")
    return {"status": "bound", "run_id": current, "permits": str(path)}


def bind_run(root: str | pathlib.Path | None = None, run_id: str | None = None,
             launch_dir: str | pathlib.Path | None = None,
             launch_id: str | None = None) -> dict:
    """Bind a LAUNCH-SCOPED registry to the run its activation recorded — once, explicitly.

    The pre-run registry is created before any resolved `repo_path` exists, so it lives in the
    LAUNCH directory, KEYED by the launch id `begin` minted, and carries `run_id: ""`.
    `--launch-dir` with `--repo` TRANSFERS that same registry — the identical permits and the
    identical journal — to the resolved repository and then binds it (`bind-run --repo` alone just
    binds in place, as before). The launch folder MAY BE the resolved repository itself (a factory
    launched from its own directory): a KEYED launch registry is still not the run's registry, so it
    travels to the run's unkeyed name in the same folder and its launch copy is retired, while a
    LEGACY unkeyed launch registry — which already IS that name — is bound where it lies. `--launch-id`
    says WHICH launch of a shared folder travels; without
    it the folder must hold exactly ONE open launch, because a transfer never guesses (two open
    launches with no id are a loud refusal). The destination must not already hold a registry (a
    transfer never merges or overwrites one), the source must be unbound and its chain intact, the
    binding must MATCH the destination's checkpoint, and the launch copy is retired to an archive
    name so it cannot become a second, competing registry. Every step is a file-atomic write plus
    its own journaled `bind-run` event (`at` = now): nothing is back-dated and no earlier
    transition is re-stated — the permits keep the timestamps they were recorded with.
    """
    if root is None:
        raise PermitError("bind-run needs --repo <root>: the run's checkpoint lives in the resolved "
                          "repository, so --launch-dir alone names the registry to transfer but not "
                          "where the run is")
    target = _checked_repo(root)
    if launch_id is not None and launch_dir is None:
        raise PermitError("bind-run: --launch-id names a LAUNCH registry, so it needs --launch-dir "
                          "<dir>")
    if launch_dir is None:
        return _bind_in_place(target, run_id)
    source = pathlib.Path(os.path.abspath(str(launch_dir)))
    if not source.is_dir():
        raise PermitError(f"the launch directory does not exist: {source}")
    anchor = launch_anchor(source, launch_id)
    key = _launch_key(source, anchor, launch_id is not None)
    if source == target and key is None:
        # A LEGACY unkeyed launch registry IS the run's own registry here, so there is nothing to
        # move: it is bound where it already lies. A KEYED launch registry is not the run's
        # registry even in the same folder — it travels and is retired like any other transfer.
        return _bind_in_place(target, run_id)
    source_permits, source_ledger = _registry_paths(source, key)
    data = read_permits(source, key)
    current = pipeline_run_id(target)                   # the checkpoint activation wrote
    wanted = (run_id or "").strip() or current
    if wanted != current:
        raise PermitError(f"the registry may only be bound to THIS run: --run-id {wanted!r} is not "
                          f"the current pipeline run {current!r} ({PIPELINE_REL.as_posix()})")
    if data.get("run_id"):
        raise PermitError(f"{source_permits} is already bound to run {data['run_id']!r}: a "
                          f"launch registry is transferred ONCE, before any run binding")
    for path in (target / PERMITS_REL, target / LEDGER_REL):
        if path.exists():
            raise PermitError(f"{path} already exists: a transfer must never merge into, or "
                              f"overwrite, another registry — resolve the target and bind ITS "
                              f"registry instead")
    problems = ledger_problems(source, launch_id=key)
    if problems:
        raise PermitError("; ".join(problems))
    archive_permits, archive_ledger = _transferred_paths(source, current, key)
    for path in (archive_permits, archive_ledger):
        if path.exists():
            raise PermitError(f"{path} already exists: this launch registry was already "
                              f"transferred once")
    # The SAME registry travels: identical permits, identical journal, the run binding AND the
    # retirement of the launch copy. The whole thing is ONE transaction: a fault in ANY write —
    # a copy, the binding or either retirement rename — leaves no target registry and restores the
    # launch registry byte-identically (still unbound, with no archive), so the same command can be
    # retried WITHOUT preconditions only when that rollback succeeds; an incomplete rollback is
    # reported as such (see `_untransfer`) and the state must be reconciled before anything else.
    retired: list[tuple[pathlib.Path, pathlib.Path]] = []       # (archive, live path)
    try:
        _copy_atomic(source_permits, target / PERMITS_REL)
        if source_ledger.is_file():
            _copy_atomic(source_ledger, target / LEDGER_REL)
        binding = _bind_in_place(target, current)
        os.replace(source_permits, archive_permits)
        retired.append((archive_permits, source_permits))
        if source_ledger.is_file():
            os.replace(source_ledger, archive_ledger)
            retired.append((archive_ledger, source_ledger))
    except BaseException as exc:
        problems = _untransfer(target, retired)
        if problems:
            raise PermitError(
                f"the transfer to {target} was interrupted ({exc}) and could NOT be rolled back "
                f"cleanly: {'; '.join(problems)} — the launch registry is NOT restored as it was, "
                f"so the state above must be reconciled before anything else; do not assume a "
                f"plain retry") from exc
        if isinstance(exc, PermitError):
            raise
        raise PermitError(f"the transfer could not be completed ({exc}): the launch registry at "
                          f"{source} was restored unchanged and nothing was left at {target} — "
                          f"retry `bind-run --launch-dir {source} --repo {target}`") from exc
    return {"status": "transferred", "run_id": current, "permits": str(target / PERMITS_REL),
            "ledger": str(target / LEDGER_REL), "binding": binding,
            "archived": [str(archive_permits), str(archive_ledger)]}


def _untransfer(target: pathlib.Path, retired: list[tuple[pathlib.Path, pathlib.Path]]) -> list[str]:
    """Undo a half-finished transfer and REPORT every step that could not be undone.

    Called for EVERY failure inside the transfer transaction. The launch copy is the source of
    truth, so each completed retirement rename is reversed first; the target's files are removed
    only when the source is whole again — otherwise they are kept, because deleting them would
    destroy the only remaining copy of the transferred state. A cleanup that fails is NOT swallowed:
    the caller must tell the operator the real state (which path remains, where the launch registry
    actually is) instead of promising a clean restore and a plain retry.
    """
    problems: list[str] = []
    for archive, live in reversed(retired):
        try:
            if archive.exists() and not live.exists():
                os.replace(archive, live)
        except OSError as exc:
            problems.append(f"the launch copy could not be restored from {archive} to {live}: {exc}")
    if problems:
        kept = [str(path) for path in (target / PERMITS_REL, target / LEDGER_REL) if path.exists()]
        if kept:
            problems.append(f"the target copies at {', '.join(kept)} were kept as the remaining "
                            f"evidence of the interrupted transfer")
        return problems
    for leftover in (target / PERMITS_REL, target / LEDGER_REL):
        try:
            leftover.unlink(missing_ok=True)
        except OSError as exc:
            problems.append(f"the half-written registry at {leftover} could not be removed, so it "
                            f"is left behind: {exc}")
    return problems


# -------------------------------------------------------------------------------------------- audit

def _attribution():
    """The sibling `model_attribution` module (session resolution), imported on demand."""
    scripts = pathlib.Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import model_attribution  # noqa: PLC0415  (deliberately lazy)
    except ImportError as exc:
        raise PermitError(f"the permit audit reuses model_attribution.py's session resolution, "
                          f"which cannot be imported: {exc}") from exc
    return model_attribution


def wire_spawns(session_dir: pathlib.Path) -> tuple[list[dict], list[str], int]:
    """`(spawns, malformed, events)` of every `agents/*/wire.jsonl` of one session.

    A spawn is `{agent_id, role, time_ms, wire}`; a malformed line (not a JSON object) or a spawn
    with no readable time/role is REPORTED, never skipped.

    ONE AGENT ID IS ONE DELEGATION (ADV-1). A resumed agent appends a SECOND `subagent.spawned`
    line for the same id, and a resume carries a generic profile name (`coder`) instead of the
    factory profile the delegation was spawned with. Judging each line on its own turned every
    resume into a bogus `role mismatch`/`permit-less delegation` (47 on one real wire). So the
    events are correlated by `subagentId`: the ORIGINAL spawn — the earliest readable one — is the
    delegation and decides the role; later lines for that id are resumes of the same delegation and
    are neither a second spawn nor a role claim. The original role always wins: a resume naming the
    role the permit happens to want never repairs a genuine mismatch.
    """
    attribution = _attribution()
    agents_dir = session_dir / attribution.AGENTS_DIR
    wires = sorted(wire for wire in agents_dir.glob(f"*/{attribution.WIRE_FILE}") if wire.is_file()) \
        if agents_dir.is_dir() else []
    if not wires:
        raise PermitDegraded(f"session {session_dir.name} has no {attribution.AGENTS_DIR}/*/"
                             f"{attribution.WIRE_FILE}: there is no spawn evidence to audit")
    by_agent: dict[str, dict] = {}
    malformed: list[str] = []
    events = 0
    for wire in wires:
        try:
            text = wire.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise PermitError(f"cannot read the wire {wire}: {exc}") from exc
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(f"{wire}:{number}: not a JSON object (an unreadable wire cannot "
                                 f"prove that every delegation was permitted)")
                continue
            if not isinstance(event, dict):
                malformed.append(f"{wire}:{number}: the event is not a JSON object")
                continue
            events += 1
            if event.get("type") != "subagent.spawned":
                continue
            agent_id = event.get("subagentId")
            role = attribution.role_from_profile(str(event.get("subagentName") or ""))
            at = event.get("time")
            where = f"{wire}:{number}"
            if not isinstance(agent_id, str) or not agent_id:
                malformed.append(f"{where}: a spawn with no subagentId cannot be matched to a permit")
                continue
            if not role:
                malformed.append(f"{where}: spawn {agent_id!r} names no factory role "
                                 f"({event.get('subagentName')!r})")
                continue
            if not _usable_stamp(at):
                malformed.append(f"{where}: spawn {agent_id!r} carries no usable time "
                                 f"({at!r}): a millisecond stamp must be a finite number, never a "
                                 f"bool, a string, NaN or an infinity")
                continue
            candidate = {"agent_id": agent_id, "role": role, "time_ms": int(at), "wire": where}
            original = by_agent.get(agent_id)
            # The FIRST spawn of an agent id is the delegation; a later line is a resume of it.
            if original is None or candidate["time_ms"] < original["time_ms"]:
                by_agent[agent_id] = candidate
    spawns = sorted(by_agent.values(), key=lambda spawn: (spawn["time_ms"], spawn["agent_id"]))
    return spawns, malformed, events


def _session_bindings(permits: list[dict], session_start_ms: int | None = None,
                      session_id: str = "") -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """`(this session's bindings by agent id, OTHER sessions' bindings grouped by session)`.

    Agent ids restart at `agent-0` in EVERY CLI session, so a permit bound in another session and
    this session's own permit may legitimately name the SAME agent id — comparing the two is what
    refused the tester's `agent-3` because a previous session's supervisor had used it. The groups
    are what keeps that honest at the OTHER end too: two bindings of two different earlier sessions
    are not a collision, so they never share a group (`_binding_session_key`). Without a session id
    and without the session's own start every binding counts as this session's, which is the
    fail-closed reading.
    """
    current: dict[str, list[dict]] = {}
    others: dict[str, dict] = {}
    for permit in permits:
        agent_id = permit.get("agent_id")
        if not agent_id:
            continue
        key = _binding_session_key(permit, session_start_ms, session_id)
        index = current if key is None else others.setdefault(key, {})
        index.setdefault(agent_id, []).append(permit)
    return current, others


def _ownership_problems(permits: list[dict], session_start_ms: int | None = None,
                        session_id: str = "") -> tuple[dict[str, list[dict]], list[str]]:
    """`(this session's permits by agent id, problems)`: a permit id, and an agent id PER PROVEN
    SESSION, each name ONE permit.

    A duplicate WITHIN one session is the breach the rule exists for (two delegations claiming one
    agent id), and it is reported for either side of the boundary: two permits that RECORD the same
    earlier `session_id` are just as unprovable as two of this session's. Two earlier bindings whose
    session is unidentified are never paired — the evidence cannot tell two overlapping sessions
    apart, and asserting the collision is the false duplicate this gate must not produce.
    """
    current, others = _session_bindings(permits, session_start_ms, session_id)
    permit_ids = [permit.get("permit_id") for permit in permits]
    problems: list[str] = []
    for duplicate in sorted({pid for pid in permit_ids if permit_ids.count(pid) > 1}):
        problems.append(f"duplicate permit id {duplicate!r}: one permit, one id")
    groups = [current, *(group for _key, group in sorted(others.items()))]
    for agent_id in sorted({agent for group in groups for agent in group}):
        for group in groups:
            owners = group.get(agent_id, [])
            if len(owners) > 1:
                problems.append(
                    f"agent id {agent_id!r} is bound to {len(owners)} permits "
                    f"({', '.join(str(owner.get('permit_id')) for owner in owners)}): one agent, one "
                    f"permit per session")
    return current, problems


def _usable_stamp(value: object) -> bool:
    """Can the gate COMPARE this value as a millisecond stamp?

    A stamp is a real number of milliseconds, never a bool, a string, NaN or an infinity. A Python
    int is unbounded and finite by nature, so `10**1000` is USABLE — it simply orders last, and
    converting it to float to "check" it would raise `OverflowError` instead of judging it. The
    predicate therefore never converts an int; only a float is tested with `math.isfinite`.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _verdict_order_problems(permit: dict, label: str, spawn: dict, authorized: set[str],
                            stamps: dict[str, int | None] | None = None) -> list[str]:
    """The verdict stamp must be readable AND precede the spawn it permits.

    The stamp is a millisecond number this gate writes itself, so anything else — missing, a bool, a
    string, NaN, an infinity — makes the ORDER unprovable: that is an explicit violation, never a
    check silently skipped because an `isinstance(int)` test did not hold.

    The ONE legitimate exception: a hitl owner may retroactively authorize a BOOTSTRAP delegation
    that ran before the bootstrap-permit mechanism existed (or before the plan was approved). The
    permit then carries `owner_authorized: true` and a non-empty evidence string — but that flag is
    self-attested in the hand-editable permits file, so it is NOT the decision: `authorized` holds
    the permit ids THIS run's checkpoint independently records (`owner_authorizations:` notes naming
    `permit=<id>`), and only a permit named there is discharged. A flag without that record is an
    explicit `unverified owner authorization` violation (the forged-flag case) and the order
    violation stands. A plan-kind permit never qualifies: by the time a plan exists every verdict
    can precede its spawn.

    `stamps` (the note's own millisecond stamp, keyed by permit id) closes the remaining hole: an
    authorization APPENDED AFTER the delegation ran is the post-hoc acceptance this gate forbids, so
    the note must predate the spawn it excuses — and an undated note proves nothing. A caller that
    does not pass `stamps` (the helper's unit contract) keeps the membership test alone.
    """
    claims_override = (permit.get("owner_authorized") is True
                       and permit.get("kind") == "bootstrap"
                       and bool(str(permit.get("evidence") or "").strip()))
    if claims_override:
        permit_id = str(permit.get("permit_id") or "")
        if permit_id not in authorized:
            return [f"unverified owner authorization: {label} claims owner_authorized, but this run's "
                    f"{PIPELINE_REL.as_posix()} records no `owner_authorizations` note naming "
                    f"`permit={permit.get('permit_id')}` — a flag set by hand in the editable permits "
                    f"file is not an owner decision, so the verdict order stands as a violation"]
        if stamps is not None:
            recorded = stamps.get(permit_id)
            if recorded is None:
                return [f"retroactive owner authorization: {label} is named by an "
                        f"`owner_authorizations` note of this run that carries no readable stamp, so "
                        f"the decision cannot be proven to precede agent {spawn['agent_id']!r} "
                        f"({spawn['wire']})"]
            if recorded > spawn["time_ms"]:
                return [f"retroactive owner authorization: {label} was authorized AFTER agent "
                        f"{spawn['agent_id']!r} spawned ({spawn['wire']}) — an owner decision "
                        f"appended after the delegation ran excuses nothing, so the out-of-order "
                        f"verdict stands"]
        return []
    judged = permit.get("verdict_at_ms")
    if judged is None:
        return [f"unreadable verdict time: {label} carries no verdict_at_ms, so the order of the "
                f"verdict and the spawn {spawn['agent_id']!r} cannot be proven ({spawn['wire']})"]
    if not _usable_stamp(judged):
        return [f"unreadable verdict time: {label} carries verdict_at_ms {judged!r}, which is not "
                f"a finite number ({spawn['wire']})"]
    if judged > spawn["time_ms"]:
        return [f"out-of-order verdict: {label} was allowed at {permit.get('verdict_at')}, AFTER "
                f"agent {spawn['agent_id']!r} spawned ({spawn['wire']}): a verdict precedes the "
                f"spawn it permits"]
    return []


def _spawn_problems(spawn: dict, by_agent: dict[str, list[dict]],
                    tasks: dict[str, list[str]], authorized: set[str],
                    stamps: dict[str, int | None] | None = None) -> list[str]:
    """Why one wire spawn is not covered by a valid permit (empty = the delegation was permitted)."""
    owners = by_agent.get(spawn["agent_id"], [])
    if not owners:
        if spawn["role"] == SUPERVISOR_ROLE:
            # The supervisor watchdog is launched at run start under the run's OWN authority — it
            # can never carry a verdict that precedes its own spawn (bootstrap circularity), so
            # its spawns are exempt from the permit-less check. A supervisor spawn that IS bound
            # to a permit falls through to the full audit below.
            return []
        return [f"permit-less delegation: agent {spawn['agent_id']!r} (role {spawn['role']!r}) "
                f"spawned at {spawn['wire']} with NO permit"]
    if len(owners) > 1:
        return []                                        # already reported as a duplicate
    permit = owners[0]
    label = f"permit {permit.get('permit_id')!r}"
    problems: list[str] = []
    if permit.get("verdict") == "deny":
        return [f"denied permit executed: {label} was DENIED and agent {spawn['agent_id']!r} "
                f"spawned anyway ({spawn['wire']})"]
    if permit.get("verdict") != "allow":
        return [f"unjudged permit executed: {label} has no allow verdict, yet agent "
                f"{spawn['agent_id']!r} spawned ({spawn['wire']})"]
    if permit.get("role") != spawn["role"]:
        problems.append(f"role mismatch: {label} permits role {permit.get('role')!r}, but agent "
                        f"{spawn['agent_id']!r} is {spawn['role']!r} ({spawn['wire']})")
    problems += _verdict_order_problems(permit, label, spawn, authorized, stamps)
    problems += _plan_problems(permit, label, tasks)
    return problems


def _plan_problems(permit: dict, label: str, tasks: dict[str, list[str]]) -> list[str]:
    """The permit must answer a planned task, and its scope must sit inside that task's files."""
    if permit.get("kind", "plan") == "bootstrap":
        # A pre-plan bootstrap permit was validated against the PARSED TASK at `add` time; the
        # approved-plan task checks apply to implementation and later (plan) delegations only.
        return []
    task_id = str(permit.get("task_id") or "")
    declared = tasks.get(task_id)
    if declared is None:
        return [f"unplanned task: {label} answers {task_id!r}, which is not a task of the approved "
                f"plan"]
    if not declared:
        return [f"unprovable scope: {label} answers {task_id!r}, whose plan entry declares no "
                f"files — the scope cannot be proven a subset"]
    outside = _outside_plan(permit.get("scope") or [], declared)
    if outside:
        return [f"scope violation: {label} includes {', '.join(outside)}, which {task_id!r} does "
                f"not declare in the approved plan"]
    return []


def _session_state(directory: pathlib.Path) -> dict:
    """One session's `state.json` as a dict ({} when absent or malformed — never a crash)."""
    try:
        state = json.loads((directory / _attribution().STATE_FILE).read_text(encoding="utf-8",
                                                                            errors="replace"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _session_start_ms(state: dict) -> int | None:
    """When the audited CLI session BEGAN (epoch ms), or None when it records no such moment.

    A session's `state.json` carries `createdAt`, the moment the CLI created that session. It is the
    only evidence a permit BINDING can be placed on the far side of: the wire's own stamps are
    events of the session, and they say nothing about when the session started.
    """
    return _timestamp_ms(state.get("createdAt")) if isinstance(state, dict) else None


def _run_session_dir(root: pathlib.Path) -> pathlib.Path | None:
    """The CLI session directory the run's checkpoint records at activation, or None.

    `bind` and the audit MUST judge a binding on the same evidence, or `bind` would refuse a
    delegation the audit then accepts (the defect this closes). The checkpoint's `session_dir` is
    that ONE source: no checkpoint, no `session_dir`, no readable state — the session is UNPROVEN.
    """
    path = root / PIPELINE_REL
    if not path.is_file():
        return None
    attribution = _attribution()
    try:
        declared = str(attribution.read_pipeline_contract(path)["run_binding"].get("session_dir")
                       or "").strip()
    except attribution.AttributionError:
        return None
    return pathlib.Path(declared).expanduser() if declared else None


def _run_session_start_ms(root: pathlib.Path) -> int | None:
    """When THIS RUN's CLI session began (epoch ms), or None when the run cannot prove it."""
    directory = _run_session_dir(root)
    if directory is None:
        return None
    return _session_start_ms(_session_state(directory))


def _run_session_id(root: pathlib.Path) -> str:
    """The CLI session id THIS RUN is bound to (the checkpoint's session), or "" when unproven.

    The identity is `state.json`'s `id` — the same value `model_attribution.py` resolves a session
    by — with the session directory's own name as the fallback (the CLI names the directory after
    the id). It is what a recorded binding names, so two OVERLAPPING CLI sessions stay separable
    where two `createdAt` stamps cannot: a session's start says when it began, never when it ended.
    """
    directory = _run_session_dir(root)
    if directory is None:
        return ""
    recorded = _session_state(directory).get("id")
    if isinstance(recorded, str) and recorded.strip():
        return recorded.strip()
    return directory.name if directory.is_dir() else ""


def _recorded_session_id(permit: dict) -> str:
    """The CLI session id a permit's binding RECORDS (`""` for a pre-identity or unproven binding)."""
    value = permit.get("session_id")
    return value.strip() if isinstance(value, str) else ""


def _bound_before_session(permit: dict, session_start_ms: int | None) -> bool:
    """Was this permit bound to its agent BEFORE the audited session existed?

    One agent id is ONE delegation PER CLI SESSION: agent ids restart at `agent-0` in every session,
    so a permit bound in an earlier session names an agent id the current wire can never hold.
    Reporting that as `bound but never spawned` accused a run of a delegation it never made — the
    supervisor's own bootstrap permit, bound in the previous session, failed a phase K that had
    nothing to do with it. The binding's own stamp against the session's `createdAt` is that
    evidence, and it is the ONLY evidence accepted: with no session start (or an unreadable
    `bound_at`) the binding is judged as this session's, so a genuine `bound but never spawned`
    still fails closed. It is the LEGACY fallback: a recorded `session_id` outranks it, because this
    stamp proves the binding is not the audited session's but never WHICH session made it — two
    overlapping sessions both being alive is exactly what a start instant cannot see.
    """
    if session_start_ms is None:
        return False
    bound = _timestamp_ms(permit.get("bound_at"))
    return bound is not None and bound < session_start_ms


def _binding_session_key(permit: dict, session_start_ms: int | None, session_id: str) -> str | None:
    """WHICH CLI session a binding belongs to: None for the audited one, else its own group key.

    The evidence ladder, strongest first:

    1. the session id `bind` recorded with the binding — decisive BOTH ways, so two bindings of one
       earlier session still collide while two bindings of two different earlier sessions never do;
    2. the legacy `bound_at` boundary — it proves the binding is another session's, yet says nothing
       about WHICH, so such a binding gets a group of its OWN (`UNIDENTIFIED_SESSION_PREFIX`):
       asserting that two of them shared one session is exactly the false duplicate an overlapping
       session produced, so it is never asserted;
    3. neither — the binding is judged as the audited session's (fail closed).

    A recorded other session keys as `session:<id>`; an unidentified one cannot be paired with
    anything, so the two spellings never collide.
    """
    recorded = _recorded_session_id(permit)
    if recorded:
        return None if recorded == session_id else f"session:{recorded}"
    if _bound_before_session(permit, session_start_ms):
        return f"{UNIDENTIFIED_SESSION_PREFIX}{permit.get('permit_id')}"
    return None


def _lifecycle_problems(permits: list[dict], by_agent: dict[str, list[dict]],
                        spawned_agents: set[str]) -> list[str]:
    """Permits that were allowed but never resolved, and bindings the wire never confirms.

    `by_agent` is THIS session's index (`_session_bindings`): a binding an earlier session recorded
    is not this session's spawn, so it is neither `bound but never spawned` nor an `unused permit`.
    """
    problems: list[str] = []
    for permit in permits:
        if permit.get("verdict") != "allow" or permit.get("agent_id") or permit.get("closed"):
            continue
        problems.append(f"unused permit: {permit.get('permit_id')!r} was allowed but never spawned "
                        f"and is not closed — close it with the reason it was not executed")
    for agent_id, owners in sorted(by_agent.items()):
        if agent_id in spawned_agents or len(owners) != 1:
            continue
        problems.append(f"bound but never spawned: permit "
                        f"{owners[0].get('permit_id')!r} claims agent {agent_id!r}, which the "
                        f"session wire does not hold")
    return problems


def audit(root: str | pathlib.Path, session: str = "auto", home: str | None = None) -> dict:
    """The finish gate: the ledger, the permits, the session wire and the approved plan.

    The checks are focused helpers — the ledger's history (`ledger_problems`), ownership (one permit
    id, one agent id), the spawn coverage and the permit lifecycle — so each failure class is
    testable on its own and the backstop stays readable.

    The run's own checkpoint is handed to the resolver: a run launched OUTSIDE its target repository
    has its session `cwd` at the launch directory, so `auto` needs `launch_dir`/`session_dir`/
    `started_at` to find THIS run's wire instead of matching an older target-cwd session
    (factory-defect-session-resolution.md).
    """
    attribution = _attribution()
    root = _checked_repo(root)
    wire_home = pathlib.Path(home) if home else attribution.WIRE_HOME
    pipeline = root / PIPELINE_REL
    # Run evidence is what `auto` needs to find the CURRENT run's wire; an explicit directory is
    # the caller's declaration of which run is being closed, and is used as given.
    binding = pipeline if str(session).strip().lower() == "auto" and pipeline.is_file() else None
    try:
        info = attribution.resolve_session(str(root), session, wire_home, binding)
    except attribution.Degraded as exc:
        raise PermitDegraded(str(exc)) from exc
    except attribution.AttributionError as exc:
        raise PermitError(str(exc)) from exc
    session_dir = pathlib.Path(info["session_dir"])
    spawns, malformed, events = wire_spawns(session_dir)
    path = root / PERMITS_REL
    if path.is_file():
        data = read_permits(root)
    else:
        data = _empty("")
    permits = data["permits"]

    problems: list[str] = [f"malformed wire evidence: {entry}" for entry in malformed]
    # The registry's HISTORY is judged before any spawn: a file whose recorded transitions do not
    # reach the state on disk was reset, truncated or edited, and no current content can undo that.
    problems += ledger_problems(root)
    if path.is_file() and not data.get("run_id"):
        # A launch-scoped registry belongs to a run that does not exist yet: no checkpoint is
        # required to say so, and it authorizes nothing until activation binds it.
        problems.append(
            f"unbound permits: {path} is launch-scoped (no run_id yet) — a launch-scoped registry "
            f"authorizes no run's delegations; bind it once at activation with `permit_gate.py "
            f"bind-run --repo {root}` (the run comes from {PIPELINE_REL.as_posix()})")
        return {"status": "failed", "repo": str(root), "session": str(session_dir),
                "permits": str(path), "run_id": None, "events": events,
                "spawns": len(spawns), "permits_count": len(permits), "problems": problems}
    if path.is_file():
        # The permits file must belong to THIS run before any spawn is evaluated: permits of
        # another run never authorize this run's delegations (a reused agent id would otherwise
        # inherit a stale allow).
        current_run = pipeline_run_id(root)
        if data["run_id"] != current_run:
            problems.append(f"stale permits: {path} belongs to run {data['run_id']!r}, but the "
                            f"current pipeline run is {current_run!r} — permits of another run "
                            f"never authorize this run's delegations (archive or re-initialize "
                            f"the file)")
            return {"status": "failed", "repo": str(root), "session": str(session_dir),
                    "permits": str(path), "run_id": data.get("run_id") or None, "events": events,
                    "spawns": len(spawns), "permits_count": len(permits), "problems": problems}
    authorized = authorized_permit_ids(root)
    stamps = authorization_stamps(root)
    # The plan is read only once the registry is proven to belong to THIS run: a launch-scoped
    # (unbound) registry answers no plan at all, and its audit refusal is the binding.
    tasks = plan_tasks(root)
    # Agent ids restart in every CLI session, so the by-agent index is THIS session's: a binding
    # another session recorded neither covers a spawn of this session nor collides with its ids. The
    # session's own identity (recorded on new bindings) and, failing that, its start instant are the
    # evidence that places a binding on the other side of that boundary.
    by_agent, ownership = _ownership_problems(permits,
                                              _session_start_ms(info.get("state") or {}),
                                              str(info.get("session_id") or ""))
    problems += ownership
    for spawn in spawns:
        problems += _spawn_problems(spawn, by_agent, tasks, authorized, stamps)
    problems += _lifecycle_problems(permits, by_agent,
                                    {spawn["agent_id"] for spawn in spawns})
    return {"status": "failed" if problems else "ok", "repo": str(root),
            "session": str(session_dir), "permits": str(path), "run_id": data.get("run_id") or None,
            "events": events, "spawns": len(spawns), "permits_count": len(permits),
            "problems": problems}


# -------------------------------------------------------------------------------------------- CLI

def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=False))


# The shared `--launch-id` help: the flag names WHICH launch of a shared folder a command addresses.
LAUNCH_ID_HELP = ("the launch nonce `supervisor_watchdog.py begin` returned "
                  "(YYYYMMDD-HHMMSS-<6 hex>): it names THIS launch's own registry, so several "
                  "factories in one launch folder never share one. Omit it when the folder holds "
                  "exactly ONE uncompleted launch")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="permit_gate.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create the permits file skeleton")
    p.add_argument("--repo", default=None,
                   help="repository root holding .code-factory/ (omit it with --launch-dir: the "
                        "LAUNCH-ONLY pre-run registry lives in the launch directory)")
    p.add_argument("--launch-dir", default=None, dest="launch_dir",
                   help="the launch directory whose supervisor bootstrap (`begin`) anchors a "
                        "PRE-RUN registry: the skeleton is created unbound (run_id \"\") and "
                        "`bind-run` binds it at activation")
    p.add_argument("--launch-id", default=None, dest="launch_id",
                   help=LAUNCH_ID_HELP)
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("add", help="register one permit")
    p.add_argument("--repo", default=None,
                   help="the run's repository (omit it with --launch-dir for the launch-only "
                        "registry)")
    p.add_argument("--launch-dir", default=None, dest="launch_dir",
                   help="the launch bootstrap a PRE-RUN supervisor permit answers "
                        "(bootstrap + supervisor only)")
    p.add_argument("--launch-id", default=None, dest="launch_id",
                   help=LAUNCH_ID_HELP)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--task-id", required=True, dest="task_id",
                   help="a task id of the approved plan (.code-factory/state/plan.md); with "
                        "--kind bootstrap it must be 'bootstrap' (the permit answers the task)")
    p.add_argument("--kind", default="plan", choices=PERMIT_KINDS,
                   help="plan (default): validated against the approved plan; bootstrap: a "
                        "pre-plan permit for analyzer/planner/supervisor, validated against the "
                        "parsed task")
    p.add_argument("--role", required=True, help="a registered delegate role")
    p.add_argument("--phase", required=True, help="one of " + ", ".join(PERMIT_PHASES))
    p.add_argument("--scope", action="append", default=[],
                   help="repo-relative path the delegation may touch (repeatable)")
    p.add_argument("--constraint", action="append", default=[],
                   help="a rule the delegation must honour (repeatable)")
    p.set_defaults(func=_cmd_add)

    p = sub.add_parser("verdict", help="record the supervisor verdict for a permit")
    p.add_argument("--repo", default=None,
                   help="the run's repository (omit it with --launch-dir: the pre-run registry "
                        "lives in the launch directory)")
    p.add_argument("--launch-dir", default=None, dest="launch_dir",
                   help="the launch directory holding the launch-only registry")
    p.add_argument("--launch-id", default=None, dest="launch_id",
                   help=LAUNCH_ID_HELP)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--verdict", required=True, choices=VERDICTS)
    p.add_argument("--evidence", required=True,
                   help="the artifact or rule the verdict rests on (never empty)")
    p.set_defaults(func=_cmd_verdict)

    p = sub.add_parser("bind", help="record the agent id an allowed permit spawned")
    p.add_argument("--repo", default=None,
                   help="the run's repository (omit it with --launch-dir)")
    p.add_argument("--launch-dir", default=None, dest="launch_dir",
                   help="the launch directory holding the launch-only registry")
    p.add_argument("--launch-id", default=None, dest="launch_id",
                   help=LAUNCH_ID_HELP)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--agent-id", required=True, dest="agent_id")
    p.set_defaults(func=_cmd_bind)

    p = sub.add_parser("close", help="mark an allowed permit as NOT executed")
    p.add_argument("--repo", required=True)
    p.add_argument("--permit-id", required=True, dest="permit_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=_cmd_close)

    p = sub.add_parser("bind-run", help="bind (and, with --launch-dir, transfer) a launch registry")
    p.add_argument("--repo", default=None,
                   help="the resolved repository whose checkpoint names the run")
    p.add_argument("--launch-dir", default=None, dest="launch_dir",
                   help="the launch directory holding the PRE-RUN registry: it is TRANSFERRED here")
    p.add_argument("--launch-id", default=None, dest="launch_id",
                   help=LAUNCH_ID_HELP)
    p.add_argument("--run-id", default=None, dest="run_id",
                   help="the run to bind (default: the WIP checkpoint's; must match it)")
    p.set_defaults(func=_cmd_bind_run)

    p = sub.add_parser("snapshot-legacy",
                       help="attest a pre-journal registry as it stands (one marked snapshot)")
    p.add_argument("--repo", required=True)
    p.add_argument("--note", default="",
                   help="an optional operator note recorded WITH the snapshot (it is marked as "
                        "unproven history, never as a transition that happened)")
    p.set_defaults(func=_cmd_snapshot_legacy)

    p = sub.add_parser("repair", help="the owner's explicit recovery from a diverged registry")
    p.add_argument("--repo", required=True)
    p.add_argument("--mode", default="", metavar="restore|attest",
                   help="restore: re-derive permits.yaml from the ledger head (loses the "
                        "unjournaled transition); attest: keep the file and append ONE marked "
                        "re-anchoring event (needs --note). Omit it to only REPORT the divergence")
    p.add_argument("--note", default="",
                   help="why the attested gap exists (mandatory for --mode attest)")
    p.set_defaults(func=_cmd_repair)

    p = sub.add_parser("audit", help="finish gate: permits vs the session wire vs the plan")
    p.add_argument("--repo", required=True)
    p.add_argument("--session", default="auto",
                   help="a session directory, or 'auto' for the current one (default)")
    p.add_argument("--home", default=None, help="the CLI's wire root (default: ~/.kimi-code)")
    p.set_defaults(func=_cmd_audit)
    return ap


def _cmd_init(args: argparse.Namespace) -> int:
    _emit(init(args.repo, args.launch_dir, args.launch_id))
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    _emit(add(args.repo, args.permit_id, args.task_id, args.role, args.phase, args.scope,
              args.constraint, args.kind, args.launch_dir, args.launch_id))
    return 0


def _cmd_bind_run(args: argparse.Namespace) -> int:
    _emit(bind_run(args.repo, args.run_id, args.launch_dir, args.launch_id))
    return 0


def _cmd_verdict(args: argparse.Namespace) -> int:
    _emit(verdict(args.repo, args.permit_id, args.verdict, args.evidence, args.launch_dir,
                  args.launch_id))
    return 0


def _cmd_bind(args: argparse.Namespace) -> int:
    _emit(bind(args.repo, args.permit_id, args.agent_id, args.launch_dir, args.launch_id))
    return 0


def _cmd_close(args: argparse.Namespace) -> int:
    _emit(close(args.repo, args.permit_id, args.reason))
    return 0


def _cmd_snapshot_legacy(args: argparse.Namespace) -> int:
    _emit(snapshot_legacy(args.repo, args.note))
    return 0


def _cmd_repair(args: argparse.Namespace) -> int:
    _emit(repair(args.repo, args.mode, args.note))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    try:
        result = audit(args.repo, args.session, args.home)
    except PermitDegraded as exc:
        print(f"DEGRADED - the permit audit cannot prove anything: {exc}")
        return 3
    print(f"session: {result['session']}")
    print(f"permits: {result['permits']} ({result['permits_count']} permit(s))")
    print(f"events: {result['events']}, spawns: {result['spawns']}")
    for problem in result["problems"]:
        print(f"violation: {problem}")
    if result["status"] == "ok":
        print(f"PASS - every delegation in the wire ({result['spawns']}) is covered by an allowed, "
              f"judged, in-scope permit and no permit is left unused")
        return 0
    print(f"FAIL - {len(result['problems'])} permit-audit violation(s)")
    return 1


def main() -> int:
    use_utf8_output()
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except PermitError as exc:
        print(f"permit_gate.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
