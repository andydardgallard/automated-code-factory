#!/usr/bin/env python3
"""
Regression test for the factory's sub-agent catalog stability (Defect A, zero LLM tokens).

WHY THIS EXISTS

The CLI has intermittently answered "Unknown agent type" for a factory role whose profile file was
on disk: its profile registry reloaded and lost the entry. The caller cannot tell that CLI-side loss
from a profile that is really MISSING or INVALID, and the two need opposite reactions — retry the
SAME role with the SAME model, or stop the run as a factory defect. This test is the vaccination:
it pins the observable contract of the deterministic probe `agent_catalog_check.py` and the
`AGENT_CATALOG` degradation route BEFORE they existed, so the replacement (not the test) is written
against the failing pin.

COVERED, through the shipped CLI (a subprocess, exactly as the flow calls it) and its public API:

  - REAL-TREE INTEGRITY: the repository's own 16 profiles are all present and valid, every declared
    `name:` resolves back to its own role, the names are unique, and the declared
    `model_preference` is one the CLI knows — `skill_manager`, `diagnostician` and `coder` (the
    business scenario's roles) carry exactly the identity and model side they should;
  - REPOSITORY ROOT: `--root <repository root>` resolves the DEPLOYED `.agents/agents/sub-agents`
    catalog — the exact invocation that once reported all 16 profiles missing — and yields the same
    mapping as the default probe, so the deployed layout wins over a legacy/hermetic
    `agents/sub-agents` copy that happens to sit next to it;
  - REPEATED LIVE REFRESH STABILITY: probing several times in a row yields the SAME role -> name /
    model mapping each time — a reload changes nothing on disk, so the probe cannot drift;
  - HERMETIC REMOVE/RE-ADD (three cycles over `skill_manager`, `diagnostician`, `coder`): removing
    a profile from a COPY of the catalog makes the probe say INVALID (exit 1) with the role, the
    file and the restore action named, `--role <the failed role>` reports 1 while a `--role` of an
    intact profile still reports 0, and re-adding the SAME bytes brings the catalog back to OK
    (exit 0) with identity and model side unchanged — no silent substitution is possible;
  - INVALID VARIANTS: no `name:`, a `name:` that resolves to ANOTHER role (the substitution trap), a
    `model_preference` outside `primary|secondary`, unreadable frontmatter, and a stray profile that
    re-declares a claimed identity are each a loud exit 1, never a clean result;
  - FRONTMATTER SYNTAX: YAML the CLI cannot parse — an unterminated quoted scalar, an unterminated
    flow list/map, a line that is neither a key nor a sequence item — is a loud exit 1 naming the
    profile and the frontmatter, while what the profiles legitimately carry (a quoted scalar, an
    inline `#` comment AFTER the value, a balanced flow list) still parses to the SAME identity and
    model side. The adversarial finding was the opposite pair: a malformed quote was accepted and a
    valid inline comment was rejected;
  - THE DEGRADATION ROUTE: an `Unknown agent type` line classifies (end to end, through
    `error_router.py classify`) as `AGENT_CATALOG` / `infrastructure`, budget 3, and the route's
    documentation and the probe's own verdict tie exit 0 to "retry the SAME role with the SAME
    model, never a substitution" and exit 1/2 to a FACTORY DEFECT that stops the run;
  - INPUT BOUNDARIES (exit 2, actionable message, no traceback): a `--root` that is missing or not a
    directory (a wrong root must never look CLEAN), a `--role` outside `model_matrix.ROLES`, and the
    argparse contract (`--help` 0 on any console code page, a usage error 2);
  - ONE ROSTER: the probe resolves its roles and the `factory-<role>` name through
    `model_matrix.ROLES`/`ROLE_FILES` and `model_attribution.role_from_profile` — no third copy of
    the catalog that could disagree with the factory.

Exit code 0 = every assertion passes, 1 = the catalog-stability contract is not met.
A missing `agent_catalog_check.py` is reported as a plain FAIL (this file ships BEFORE the
implementation: that failure is the vaccination evidence, not a broken test).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

TOOL = SCRIPTS / "agent_catalog_check.py"
ROUTER = SCRIPTS / "error_router.py"
DOC = SCRIPTS.parent / "references" / "error-routing.md"
PATTERNS = SCRIPTS.parent / "references" / "error-patterns.default.json"
# `.agents/skills/code-factory/scripts` -> `.agents/agents/sub-agents` (the shipped profiles).
REAL_PROFILES = SCRIPTS.parents[2] / "agents" / "sub-agents"
# The repository root — the directory a real invocation passes as `--root`; its deployed catalog
# lives under `.agents/` and must be what gets probed.
REPO_ROOT = REAL_PROFILES.parents[2]
LEGACY_ENV = {**os.environ, "PYTHONIOENCODING": "cp1251"}

# The business scenario's roles: the catalog must survive their loss and return unchanged.
SCENARIO_ROLES = ("skill_manager", "diagnostician", "coder")
# What the shipped profiles declare; identity and model side must never drift (never substituted).
SCENARIO_IDENTITY = {
    "skill_manager": ("factory-skill-manager", "primary"),
    "diagnostician": ("factory-diagnostician", "primary"),
    "coder": ("factory-coder", "secondary"),
}
# A role the removals never touch, used to prove `--role` scoping (`--role` asks about ONE role).
BYSTANDER_ROLE = "tester"

# One result line of `check`: `OK|INVALID  <role>: name=<n> model_preference=<p>`.
RESULT_LINE = re.compile(r"^(OK|INVALID)\s+([a-z_]+): name=(\S+) model_preference=(\S+)$")


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", env=env)


def output(res: subprocess.CompletedProcess[str]) -> str:
    """What the probe said, stdout and stderr together."""
    return f"{res.stdout}\n{res.stderr}"


def expect(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: no traceback allowed: {res.stderr!r}")


def report(res: subprocess.CompletedProcess[str]) -> dict[str, tuple[str, str, str]]:
    """`role -> (status, name, model_preference)` from a `check` run's result lines."""
    found: dict[str, tuple[str, str, str]] = {}
    for line in res.stdout.splitlines():
        match = RESULT_LINE.match(line.strip())
        if match:
            status, role, name, preference = match.groups()
            found[role] = (status, name, preference)
    return found


def fixture(tmp: pathlib.Path, name: str) -> pathlib.Path:
    """A throwaway repository root carrying a COPY of the shipped profiles (hermetic).

    Nothing below ever writes into `.agents/agents/`: the real catalog is read-only input, which is
    what lets the removal/re-add scenario run without touching the tree the factory itself uses.
    """
    root = tmp / name
    target = root / "agents" / "sub-agents"
    target.mkdir(parents=True)
    for profile in sorted(REAL_PROFILES.glob("*.md")):
        (target / profile.name).write_bytes(profile.read_bytes())
    return root


def profiles_of(root: pathlib.Path) -> pathlib.Path:
    return root / "agents" / "sub-agents"


def profile_file(role: str) -> str:
    """The profile file name of a role — from the ONE roster, not a copy of it."""
    import model_matrix
    return model_matrix.ROLE_FILES.get(role, f"{role}.md")


# --------------------------------------------------------------------------------------------
# real-tree integrity + repeated refresh stability
# --------------------------------------------------------------------------------------------

def test_real_tree_integrity(tmp: pathlib.Path) -> None:
    """The repository's own catalog is complete and valid — identity and model side as shipped."""
    import model_matrix
    res = run("check")
    expect(res, 0, "probe on the real tree")
    found = report(res)
    check(set(found) == set(model_matrix.ROLES),
          f"the probe must report every role of model_matrix.ROLES: "
          f"missing={set(model_matrix.ROLES) - set(found)} "
          f"extra={set(found) - set(model_matrix.ROLES)}")
    check(len(model_matrix.ROLES) == 16,
          f"the factory ships 16 sub-agent profiles, the roster says {len(model_matrix.ROLES)}")
    for role, (status, _name, _pref) in found.items():
        check(status == "OK", f"real tree: {role} must be OK, got {status}")
    for role, identity in SCENARIO_IDENTITY.items():
        check(found.get(role, ("", "", ""))[1:] == identity,
              f"real tree: {role} must carry identity/model {identity}, got {found.get(role)}")
    check("catalog OK" in res.stdout, f"a clean catalog must say so: {res.stdout!r}")

    # The API (what a caller without a subprocess drives) agrees with the CLI.
    import agent_catalog_check as probe
    api = probe.check_catalog()
    check(api["errors"] == [], f"the API must see a clean catalog, got {api['errors']}")
    check(len(api["roles"]) == 16, f"the API must return 16 roles, got {len(api['roles'])}")
    names = [entry["name"] for entry in api["roles"]]
    check(len(set(names)) == len(names), f"profile identities must be unique, got {names}")
    for entry in api["roles"]:
        check(entry["model_preference"] in probe.PREFERENCES,
              f"{entry['role']}: model_preference must be one of {probe.PREFERENCES}, "
              f"got {entry['model_preference']!r}")


def test_repository_root_probe(tmp: pathlib.Path) -> None:
    """`--root <repository root>` probes the deployed `.agents/agents/sub-agents` catalog.

    This is the invocation that once reported every profile missing, so it is pinned against the
    real tree: the probe must resolve what the CLI reads instead of the project root it was given.
    """
    import agent_catalog_check as probe
    resolved = probe.profiles_dir(REPO_ROOT)
    check(resolved == REAL_PROFILES,
          f"--root {REPO_ROOT} must resolve the deployed catalog {REAL_PROFILES}, "
          f"got {resolved}")
    res = run("check", "--root", str(REPO_ROOT))
    expect(res, 0, "--root at the repository root")
    check(str(REAL_PROFILES) in res.stdout,
          f"the probe must report the deployed profiles directory: {res.stdout!r}")
    check(report(res) == report(run("check")),
          "--root at the repository root must yield the SAME role->name/model mapping as the "
          "default probe")
    api = probe.check_catalog(REPO_ROOT)
    check(api["errors"] == [],
          f"the API must see a clean catalog at the repository root, got {api['errors']}")


def test_deployed_layout_wins(tmp: pathlib.Path) -> None:
    """The deployed layout is preferred over a legacy `agents/sub-agents` copy beside it."""
    root = fixture(tmp, "deployed")            # a legacy `agents/sub-agents` copy of the catalog
    deployed = root / ".agents" / "agents" / "sub-agents"
    deployed.mkdir(parents=True)
    for profile in sorted(REAL_PROFILES.glob("*.md")):
        (deployed / profile.name).write_bytes(profile.read_bytes())
    # The legacy copy is broken (the substitution trap). Reading it would be a loud exit 1; the
    # deployed catalog is what the CLI reads, so a clean exit is the only correct answer.
    (profiles_of(root) / profile_file("coder")).write_text(
        "---\nname: factory-tester\n---\n", encoding="utf-8")

    res = run("check", "--root", str(root))
    expect(res, 0, "a root carrying both layouts")
    check(str(deployed) in res.stdout,
          f"the probe must report the deployed profiles directory: {res.stdout!r}")
    check(report(res).get("coder", ("", "", ""))[1:] == SCENARIO_IDENTITY["coder"],
          f"coder must keep its shipped identity/model {SCENARIO_IDENTITY['coder']}, "
          f"got {report(res).get('coder')}")


def test_repeated_refresh_is_stable(tmp: pathlib.Path) -> None:
    """Probing repeatedly yields the same mapping: a refresh cannot make the catalog drift."""
    baseline = None
    for attempt in range(3):
        res = run("check")
        expect(res, 0, f"probe, attempt {attempt + 1}")
        current = report(res)
        if baseline is None:
            baseline = current
        check(current == baseline,
              f"attempt {attempt + 1}: the catalog mapping changed between two probes "
              f"({baseline} -> {current}) — identity and model side must be stable")
    for role, (name, preference) in SCENARIO_IDENTITY.items():
        check(baseline[role][1:] == (name, preference),
              f"{role}: identity/model drifted under repeated probing: {baseline[role]}")


# --------------------------------------------------------------------------------------------
# hermetic remove/re-add (the business scenario)
# --------------------------------------------------------------------------------------------

def test_remove_and_readd(tmp: pathlib.Path) -> None:
    """Three cycles of removing/re-adding a profile: loud INVALID, then the SAME catalog back."""
    root = fixture(tmp, "refresh")
    profiles = profiles_of(root)
    clean = run("check", "--root", str(root))
    expect(clean, 0, "the copied catalog must start clean")
    baseline = report(clean)

    for cycle in range(3):
        for role in SCENARIO_ROLES:
            path = profiles / profile_file(role)
            original = path.read_bytes()
            path.unlink()
            try:
                missing = run("check", "--root", str(root))
                expect(missing, 1, f"cycle {cycle + 1}: {role} removed")
                said = output(missing)
                check("catalog INVALID" in said,
                      f"cycle {cycle + 1}: a missing {role} must make the catalog "
                      f"INVALID: {said!r}")
                check("catalog OK" not in said,
                      f"cycle {cycle + 1}: a missing {role} must never look clean: {said!r}")
                check(role in said, f"cycle {cycle + 1}: the line must name {role}: {said!r}")
                check(profile_file(role) in said,
                      f"cycle {cycle + 1}: the line must name the profile file "
                      f"{profile_file(role)}: {said!r}")
                check("restore" in said.lower(),
                      f"cycle {cycle + 1}: the line must carry the restore action: {said!r}")
                check(report(missing).get(role, ("",))[0] == "INVALID",
                      f"cycle {cycle + 1}: {role} must be reported INVALID")

                # `--role` asks about ONE role: the failed role fails, an intact role does not.
                scoped = run("check", "--root", str(root), "--role", role)
                expect(scoped, 1, f"cycle {cycle + 1}: --role {role} while it is missing")
                bystander = run("check", "--root", str(root), "--role", BYSTANDER_ROLE)
                expect(bystander, 0, f"cycle {cycle + 1}: --role {BYSTANDER_ROLE} must stay OK")
            finally:
                path.write_bytes(original)
            restored = run("check", "--root", str(root))
            expect(restored, 0, f"cycle {cycle + 1}: {role} re-added")
            check(report(restored) == baseline,
                  f"cycle {cycle + 1}: re-adding {role} must restore the SAME identity/model "
                  f"mapping ({baseline} -> {report(restored)}) — never a substitution")
            check(report(restored)[role][1:] == SCENARIO_IDENTITY[role],
                  f"cycle {cycle + 1}: {role} must come back as {SCENARIO_IDENTITY[role]}")


def test_invalid_profiles_are_reported(tmp: pathlib.Path) -> None:
    """Every way a present profile can be unusable is a loud exit 1, never a clean result."""
    root = fixture(tmp, "invalid")
    profiles = profiles_of(root)
    target = profiles / profile_file("coder")
    original = target.read_bytes()
    # The shipped profiles are CRLF: mutate LINES, so a line ending can never hide a variant.
    lines = original.decode("utf-8").splitlines(keepends=True)

    def mutated(drop=None, replace=None) -> str:
        """The profile with the lines matching `drop` removed / the first `replace` tuple used."""
        out = []
        for line in lines:
            if drop is not None and line.startswith(drop):
                continue
            if replace is not None and line.startswith(replace[0]):
                line = line.replace(*replace)
            out.append(line)
        return "".join(out)

    variants = {
        "no-name": mutated(drop="name:"),
        "wrong-name": mutated(replace=("name: factory-coder", "name: factory-tester")),
        "bad-preference": mutated(replace=("model_preference: secondary",
                                           "model_preference: whatever")),
        "no-frontmatter": mutated(drop="---"),
    }
    text = original.decode("utf-8")
    expected = {
        "no-name": "no `name:`",
        "wrong-name": "resolves to role",
        "bad-preference": "model_preference",
        "no-frontmatter": "frontmatter",
    }
    try:
        for label, broken in variants.items():
            check(broken != text, f"{label}: the variant did not change the profile")
            target.write_bytes(broken.encode("utf-8"))
            try:
                res = run("check", "--root", str(root))
                expect(res, 1, f"invalid profile: {label}")
                said = output(res)
                check("catalog INVALID" in said, f"{label}: must be INVALID: {said!r}")
                check(expected[label] in said,
                      f"{label}: the line must explain the problem "
                      f"({expected[label]!r}): {said!r}")
                check(report(res).get("coder", ("",))[0] == "INVALID",
                      f"{label}: coder must be reported INVALID")
            finally:
                target.write_bytes(original)
            expect(run("check", "--root", str(root)), 0, f"the catalog restored after {label}")

        # A stray profile re-declaring a claimed identity makes the CLI's catalog ambiguous.
        stray = profiles / "coder-copy.md"
        stray.write_bytes(original)
        try:
            res = run("check", "--root", str(root))
            expect(res, 1, "invalid profile: a stray duplicate identity")
            check("re-declares the identity" in res.stdout,
                  f"a duplicate identity must be named: {res.stdout!r}")
        finally:
            stray.unlink()
        expect(run("check", "--root", str(root)), 0, "the catalog after removing the stray profile")
    finally:
        target.write_bytes(original)


def mutated_profile(lines: list[str], *, replace: tuple[str, str] | None = None,
                    insert: str | None = None) -> str:
    """The profile with the first line starting with `replace[0]` replaced, or `insert` added.

    `insert` goes just BEFORE the closing `---` — inside the frontmatter block. The lines keep
    their own endings (the shipped profiles are CRLF), so a mutation never hides behind one.
    """
    out: list[str] = []
    fences = 0
    for line in lines:
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        if body.strip() == "---":
            fences += 1
            if fences == 2 and insert is not None:
                out.append(insert + ending)
        if replace is not None and body.startswith(replace[0]):
            out.append(replace[1] + ending)
            continue
        out.append(line)
    return "".join(out)


# YAML that the CLI cannot parse: each one must be reported, never silently read as a value. A
# lenient reader (strip the quotes and hope) turns `name: "factory-coder` into a VALID identity,
# which is exactly how a malformed profile reaches the CLI's registry and fails at launch time.
MALFORMED_FRONTMATTER: dict[str, tuple[tuple[str, str] | None, str | None]] = {
    "unterminated-double-quote": (("name:", 'name: "factory-coder'), None),
    "unterminated-single-quote": (("name:", "name: 'factory-coder"), None),
    "unterminated-flow-list": (("model_preference:", "model_preference: [secondary"), None),
    "unterminated-flow-map": (("tools:", "tools: {Read, Grep"), None),
    "stray-line": (None, "this is not yaml"),
}

# YAML the profiles legitimately use and the CLI parses: a trailing comment is a COMMENT (not part
# of the value), and a quoted scalar is a scalar. Rejecting these rejects a healthy profile.
VALID_FRONTMATTER: dict[str, tuple[tuple[str, str] | None, str | None]] = {
    "inline-comment": (("model_preference:",
                        "model_preference: secondary  # owner-selected side"), None),
    "quoted-name": (("name:", 'name: "factory-coder"'), None),
    "quoted-identity-with-comment": (("name:",
                                      "name: 'factory-coder'  # the identity the CLI addresses"),
                                     None),
    "flow-list": (None, "allowedTools: [Read, Grep]"),
}


def test_frontmatter_syntax_is_strict(tmp: pathlib.Path) -> None:
    """Malformed frontmatter is a loud INVALID; valid quoting and inline comments are read."""
    root = fixture(tmp, "syntax")
    profiles = profiles_of(root)
    target = profiles / profile_file("coder")
    original = target.read_bytes()
    lines = original.decode("utf-8").splitlines(keepends=True)
    try:
        for label, (replace, insert) in MALFORMED_FRONTMATTER.items():
            broken = mutated_profile(lines, replace=replace, insert=insert)
            check(broken != original.decode("utf-8"), f"{label}: the variant did not change the profile")
            target.write_bytes(broken.encode("utf-8"))
            try:
                res = run("check", "--root", str(root))
                expect(res, 1, f"malformed frontmatter: {label}")
                said = output(res)
                check("catalog INVALID" in said,
                      f"{label}: a malformed frontmatter must make the catalog INVALID: {said!r}")
                check("frontmatter" in said.lower(),
                      f"{label}: the line must say that the frontmatter is malformed: {said!r}")
                check(profile_file("coder") in said,
                      f"{label}: the line must name the profile file: {said!r}")
                check(report(res).get("coder", ("",))[0] == "INVALID",
                      f"{label}: coder must be reported INVALID: {said!r}")
            finally:
                target.write_bytes(original)
            expect(run("check", "--root", str(root)), 0, f"the catalog restored after {label}")

        for label, (replace, insert) in VALID_FRONTMATTER.items():
            valid = mutated_profile(lines, replace=replace, insert=insert)
            check(valid != original.decode("utf-8"), f"{label}: the variant did not change the profile")
            target.write_bytes(valid.encode("utf-8"))
            try:
                res = run("check", "--root", str(root))
                expect(res, 0, f"valid frontmatter: {label}")
                check(report(res).get("coder", ("", "", ""))[1:] == SCENARIO_IDENTITY["coder"],
                      f"{label}: the same identity/model must be read "
                      f"({SCENARIO_IDENTITY['coder']}), got {report(res).get('coder')}")
            finally:
                target.write_bytes(original)
    finally:
        target.write_bytes(original)


def test_profiles_dir_contract(tmp: pathlib.Path) -> None:
    """`--root` accepts the repository layout AND the profiles directory itself."""
    root = fixture(tmp, "layout")
    res = run("check", "--root", str(profiles_of(root)))
    expect(res, 0, "check with --root pointing straight at the profiles directory")
    check(str(profiles_of(root)) in res.stdout or "catalog OK" in res.stdout,
          f"the probe must report what it probed: {res.stdout!r}")


# --------------------------------------------------------------------------------------------
# the degradation route (AGENT_CATALOG)
# --------------------------------------------------------------------------------------------

def test_routing_pin(tmp: pathlib.Path) -> None:
    """`Unknown agent type` routes to AGENT_CATALOG/infrastructure — same role, same model."""
    import error_router as er

    document = er.load_document(er.DEFAULT_PATTERNS, require_full=True)
    entry, pattern = er.match_entry("Error: Unknown agent type: factory-coder",
                                    er.match_order(document))
    check(entry is not None, "an `Unknown agent type` line must match a routing row")
    check(entry["id"] == "A1" and entry["category"] == "AGENT_CATALOG",
          f"the catalog failure must be row A1/AGENT_CATALOG, got {entry['id']}/"
          f"{entry['category']}")
    check(entry["route"] == "infrastructure",
          f"AGENT_CATALOG must route to infrastructure (the SAME role/model retried), "
          f"got {entry['route']!r}")
    check(pattern == "Unknown agent type", f"the matched pattern must be the invariant phrase: "
                                           f"{pattern!r}")
    check(document[er.BUDGETS_KEY]["infrastructure"] == 3,
          f"the infrastructure budget must be 3, "
          f"got {document[er.BUDGETS_KEY].get('infrastructure')}")
    unmatched, _ = er.match_entry("everything is fine", er.match_order(document))
    check(unmatched is None, f"an unrelated line must not reach a routing row: {unmatched}")

    # End to end, the way the flow calls it.
    log = tmp / "unknown-agent.log"
    log.write_text("Error: Unknown agent type: factory-coder\n", encoding="utf-8")
    res = subprocess.run([sys.executable, str(ROUTER), "classify", "--log", str(log)],
                         capture_output=True, text=True, errors="replace")
    expect(res, 0, "error_router.py classify on an Unknown agent type log")
    for marker in ("category: AGENT_CATALOG", "route: infrastructure", "pattern_id: A1"):
        check(marker in res.stdout, f"classify must report {marker!r}: {res.stdout!r}")

    # The route's documentation and the probe's own verdict must agree on what follows.
    doc = DOC.read_text(encoding="utf-8")
    check("| A1 | AGENT_CATALOG |" in doc, "the routing tables must carry the A1 row")
    for marker in ("agent_catalog_check.py check --role", "SAME role with the SAME model",
                   "model-unavailable-stop", "FACTORY", "No substitution, ever"):
        check(marker in doc, f"the degradation route must document {marker!r}")
    verdict = run("check").stdout
    for marker in ("SAME role with the SAME model", "never a substitution"):
        check(marker in verdict, f"the clean-catalog verdict must state {marker!r}: {verdict!r}")


# --------------------------------------------------------------------------------------------
# boundary: every bad input is exit 2
# --------------------------------------------------------------------------------------------

def test_boundary_inputs(tmp: pathlib.Path) -> None:
    """A wrong `--root` must never look clean; a bad `--role` must never check nothing."""
    missing_root = tmp / "does-not-exist"
    expect(run("check", "--root", str(missing_root)), 2, "--root that does not exist")
    expect(run("check", "--root", str(ROUTER)), 2, "--root that is a file")

    empty = tmp / "empty-root"
    empty.mkdir()
    res = run("check", "--root", str(empty))
    expect(res, 1, "--root holding no profiles")
    check("no sub-agent profile" in res.stdout,
          f"an empty root must report the missing profiles, not a clean result: {res.stdout!r}")
    check("catalog OK" not in res.stdout,
          "a directory without profiles must never be reported as a clean catalog")

    bad_role = run("check", "--role", "not-a-role")
    expect(bad_role, 2, "--role outside model_matrix.ROLES")
    for role in ("diagnostician", "skill_manager"):
        check(role in output(bad_role),
              f"the --role error must list the valid roles ({role!r}): {output(bad_role)!r}")

    for args, label in (((("--help",)), "--help"),
                        ((("check", "--help")), "check --help")):
        expect(run(*args), 0, label)
        expect(run(*args, env=LEGACY_ENV), 0, f"{label} on a legacy console code page")
    expect(run(), 2, "no subcommand")


def test_one_roster_shared(tmp: pathlib.Path) -> None:
    """The probe reads the factory's roster instead of keeping a second copy of it."""
    import agent_catalog_check as probe
    import model_attribution
    import model_matrix
    check(probe.ROLES is model_matrix.ROLES,
          "agent_catalog_check must use model_matrix.ROLES, not a copy of the roster")
    check(probe.ROLE_FILES is model_matrix.ROLE_FILES,
          "agent_catalog_check must use model_matrix.ROLE_FILES, not a second file map")
    check(probe.role_from_profile is model_attribution.role_from_profile,
          "agent_catalog_check must resolve names through model_attribution.role_from_profile")


SECTIONS = (
    test_real_tree_integrity,
    test_repository_root_probe,
    test_deployed_layout_wins,
    test_repeated_refresh_is_stable,
    test_remove_and_readd,
    test_invalid_profiles_are_reported,
    test_frontmatter_syntax_is_strict,
    test_profiles_dir_contract,
    test_routing_pin,
    test_boundary_inputs,
    test_one_roster_shared,
)


def main() -> int:
    if not TOOL.is_file():
        print(f"FAIL - {TOOL.name} does not exist: nothing can tell a CLI-side catalog loss from "
              f"a really broken profile, so an 'Unknown agent type' error is still guesswork and "
              f"a role/model substitution the tempting answer. Expected the deterministic catalog "
              f"probe of .code-factory/state/plan.md T3, plus the AGENT_CATALOG route of T5.")
        return 1
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        failures = []
        for section in SECTIONS:
            try:
                section(tmp)
            except AssertionError as exc:
                failures.append(f"{section.__name__}: {exc}")

    for failure in failures:
        print(f"FAIL - {failure}")
    if failures:
        print(f"FAIL - {len(failures)} section(s) failed: the sub-agent catalog is not provably "
              f"stable, so a catalog reload can still stall the run or force a role/model swap")
        return 1
    print("PASS - the sub-agent catalog is stable and detectable: the real tree is complete and "
          "valid (16/16, unique identities, known model sides), repeated probing yields the same "
          "role->name/model mapping, hermetically removing and re-adding skill_manager / "
          "diagnostician / coder in three cycles is a loud INVALID (exit 1, role and file named) "
          "and then the SAME catalog again (exit 0, identity and model unchanged), every invalid "
          "profile and stray duplicate is reported instead of silently substituted, malformed YAML "
          "(unterminated quote/flow collection, a stray line) is INVALID while a quoted scalar and "
          "an inline comment after the value still read, `Unknown agent "
          "type` classifies as AGENT_CATALOG/infrastructure (budget 3) with the SAME role/model "
          "route documented and a FACTORY DEFECT stop on exit 1, every bad --root/--role is an "
          "exit-2 error without a traceback, and the roster is model_matrix's, not a copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
