#!/usr/bin/env python3
"""
Deterministic self-test for `model_matrix.py` (zero LLM tokens, stdlib only).

The owner's ruling is the contract under test:

  (a) a role NAMED by the task's `models:` matrix keeps that exact model — a generator/judge
      family collision is a WARNING and never a substitution;
  (b) a role the task does not name comes from the factory DEFAULT MATRIX, where the
      generator != judge rule is enforced (a same-family pair with a default-matrix side is an
      ERROR naming the fix);
  (c) no third path — `resolve()` never sets `override`; the only override is the plan
      committee's second planner, which always contrasts the first planner.

Cases (fixtures live in a tempdir; nothing is written into the repository):

  1. task value wins on a collision: reviewer stays the task's deepseek-flash, source "task",
     override False, and the family check yields exactly one warning and zero errors;
  2. an unnamed role falls back to the default matrix (source "default");
  3. an empty task matrix over a colliding default matrix yields an ERROR, not a warning;
  4. no role outside the committee gets override=True; the committee's second planner contrasts;
  5. `family()`: kimi-k3 / kimi-code/k3 / k3 -> kimi, deepseek-flash -> deepseek,
     qwen-max -> qwen, an unknown alias raises;
  6. a task naming an unknown alias resolves to the task value and the family check warns about
     the unclassifiable alias instead of crashing;
  7. `load_default_matrix()`: a missing config file returns {} without raising, a fixture config
     gives the expected primary/secondary split, and a config without [secondary_model] leaves
     the secondary roles absent;
  8. NEGATIVE/vaccination probe: a fixture task file whose reviewer duplicates the coder model
     resolves to the TASK value — the old "substitute on collision" behaviour fails this case;
  9. `precedence()` names all three rules and the committee exception in one paragraph;
 10. the CLI contract: --help exits 0, the unknown-alias and unreadable-task errors exit 2 with a
     message and no traceback, a default-matrix collision in `resolve` exits 1, `default` on a
     missing config exits 0, and the module imports stdlib only.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
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

import model_matrix as mm  # noqa: E402  (after the sys.path guard, so the test runs from anywhere)

TOOL = SCRIPTS / "model_matrix.py"
# The messages carry non-ASCII characters (the em dash): pin UTF-8 on the child's stdout so the
# assertions are portable across console code pages.
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

FIXTURE_CONFIG = """\
default_model = "kimi-code/k3"
default_permission_mode = "manual"

[secondary_model]
default_model = "deepseek-flash"

[secondary_model.models]
"kimi-code/k3" = "the thinking model"
deepseek-flash = "the fast execution model"
"""

FIXTURE_CONFIG_PRIMARY_ONLY = """\
default_model = "kimi-code/k3"
"""

# A task naming every side of the collision with the SAME model — the vaccination case (8).
FIXTURE_TASK = """\
title: collision fixture
repo_path: .
models:
  coder: deepseek-flash
  reviewer: deepseek-flash
  tester: kimi-k3
acceptance_criteria:
  - criterion: "the fixture is not a real task"
"""

# The same fixture without a models matrix — the default matrix decides everything.
FIXTURE_TASK_NO_MODELS = """\
title: no matrix fixture
repo_path: .
acceptance_criteria:
  - criterion: "the fixture is not a real task"
"""

# A matrix that satisfies the generator != judge rule: every role pinned, the two sides apart.
FIXTURE_TASK_DIVERSE = """\
title: diverse fixture
repo_path: .
models:
  analyzer: deepseek-flash
  planner: deepseek-flash
  coder: deepseek-flash
  tester: deepseek-flash
  gui_expert: deepseek-flash
  refactorer: deepseek-flash
  reviewer: kimi-code/k3
  diagnostician: kimi-code/k3
  advisor: kimi-code/k3
  documenter: deepseek-flash
  security_auditor: kimi-code/k3
  skill_manager: deepseek-flash
acceptance_criteria:
  - criterion: "the fixture is not a real task"
"""

SUBAGENT_CODER = "---\nname: factory-coder\nmodel_preference: secondary\n---\n\nbody\n"
SUBAGENT_TESTER = "---\nname: factory-tester\nmodel_preference: secondary\n---\n\nbody\n"
SUBAGENT_REVIEWER = "---\nname: factory-code-reviewer\nmodel_preference: primary\n---\n\nbody\n"
# No model_preference at all: the CLI runs such a role on its default model, i.e. primary.
SUBAGENT_ANALYZER = "---\nname: factory-analyzer\n---\n\nbody\n"


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def write(root: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, env=ENV)


def out(res: subprocess.CompletedProcess[bytes]) -> str:
    """stdout as text, CRLF-normalized (Windows text-mode stdout may translate newlines)."""
    return res.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def err(res: subprocess.CompletedProcess[bytes]) -> str:
    return res.stderr.decode("utf-8", "replace")


def case_1_task_value_wins() -> None:
    """(a) The task names the role -> exactly that model, and only a WARNING on a collision."""
    task = {"coder": "deepseek-flash", "reviewer": "deepseek-flash"}
    default = {"reviewer": "kimi-code/k3"}
    resolved = mm.resolve(task, default, "reviewer")
    expect(resolved["model"] == "deepseek-flash",
           f"the task's reviewer must be used verbatim: {resolved!r}")
    expect(resolved["source"] == "task", f"the source must be 'task': {resolved!r}")
    expect(resolved["override"] is False, f"resolve() must never override: {resolved!r}")

    check = mm.check_families(mm.resolve_all(task, default))
    expect(check["errors"] == [], f"a task-side collision must not be an error: {check!r}")
    expect(len(check["warnings"]) == 1,
           f"exactly one warning expected for coder vs reviewer: {check['warnings']!r}")
    warning = check["warnings"][0]
    for needle in ("coder", "reviewer", "deepseek-flash", "task", "authoritative"):
        expect(needle in warning, f"the warning must carry {needle!r}: {warning!r}")
    expect("error" not in warning.lower(), f"a task-side collision is not an error: {warning!r}")


def case_2_unnamed_role_falls_back() -> None:
    """(b) A role the task does not name comes from the default matrix."""
    resolved = mm.resolve({"coder": "kimi-k3"}, {"reviewer": "deepseek-flash"}, "reviewer")
    expect(resolved["source"] == "default", f"the source must be 'default': {resolved!r}")
    expect(resolved["model"] == "deepseek-flash",
           f"the default model must be used: {resolved!r}")
    coder = mm.resolve({"coder": "kimi-k3"}, {"reviewer": "deepseek-flash"}, "coder")
    expect((coder["model"], coder["source"]) == ("kimi-k3", "task"),
           f"the named role keeps its task value: {coder!r}")


def case_3_colliding_default_is_an_error() -> None:
    """(b) The default matrix breaking its own rule is an ERROR, not a warning."""
    default = {"coder": "deepseek-flash", "reviewer": "deepseek-flash"}
    check = mm.check_families(mm.resolve_all({}, default))
    expect(len(check["errors"]) == 1,
           f"one error expected for coder vs reviewer: {check['errors']!r}")
    expect(check["warnings"] == [], f"no warning expected here: {check['warnings']!r}")
    message = check["errors"][0]
    for needle in ("coder", "reviewer", "deepseek", "[secondary_model]", "pin", "models."):
        expect(needle in message, f"the error must name the fix via {needle!r}: {message!r}")
    # one side from the default matrix is enough — even when the other side is a task value.
    mixed = mm.check_families(mm.resolve_all({"coder": "deepseek-flash"}, default))
    expect(len(mixed["errors"]) == 1,
           f"a default-matrix judge against a task coder is still an error: {mixed!r}")


def case_4_no_override_outside_the_committee() -> None:
    """(c) `override` exists for the committee only; `resolve` never raises it."""
    for machine in ({"coder": "deepseek-flash", "reviewer": "deepseek-flash"},
                    {"coder": "kimi-k3"},
                    {}):
        for role, entry in mm.resolve_all(machine, {"reviewer": "kimi-code/k3"}).items():
            expect(entry["override"] is False,
                   f"role {role} must not be overridden: {entry!r}")
            expect(entry["role"] == role, f"the entry must name its role: {entry!r}")

    second = mm.committee_second_planner("kimi-k3")
    expect(second == "deepseek-flash", f"a kimi first planner needs a contrasting one: {second!r}")
    expect(mm.family(second) != "kimi", f"the second planner must contrast: {second!r}")
    expect(mm.committee_second_planner("deepseek-flash") == "kimi-k3",
           "a deepseek first planner must get a kimi second planner")
    expect(mm.committee_second_planner("qwen-max") == "kimi-k3",
           "the first contrasting alias in the pool wins")
    try:
        mm.committee_second_planner("kimi-k3", available=("kimi-k3", "kimi-code/k3"))
    except ValueError:
        pass
    else:
        raise AssertionError("a pool with no contrasting family must raise")


def case_5_family_table() -> None:
    """The family table: three known families, and an unknown alias fails loud."""
    for alias in ("kimi-k3", "kimi-code/k3", "k3", "KIMI-K3", "k3.1-pro", "moonshot-v1"):
        expect(mm.family(alias) == "kimi", f"{alias!r} must be kimi: {mm.family(alias)!r}")
    expect(mm.family("deepseek-flash") == "deepseek", "deepseek-flash must be deepseek")
    expect(mm.family("deepseek-chat") == "deepseek", "deepseek-chat must be deepseek")
    expect(mm.family("qwen-max") == "qwen", "qwen-max must be qwen")
    expect(mm.family("qwq-32b") == "qwen", "qwq-32b must be qwen")
    for unknown in ("gpt-4o", "llama-3-70b", "", "   ", None):
        try:
            mm.family(unknown)
        except ValueError:
            continue
        raise AssertionError(f"an unclassifiable alias must raise: {unknown!r}")


def case_6_unknown_alias_in_the_task() -> None:
    """An unclassifiable task alias is reported, never silently dropped or crashed on."""
    task = {"coder": "llama-3-70b", "reviewer": "deepseek-flash"}
    resolved = mm.resolve(task, {}, "coder")
    expect((resolved["model"], resolved["source"]) == ("llama-3-70b", "task"),
           f"the task value must be used as it is: {resolved!r}")
    check = mm.check_families(mm.resolve_all(task, {}))
    expect(check["errors"] == [], f"an unclassifiable alias is not an error: {check!r}")
    expect(len(check["warnings"]) == 1,
           f"one warning about the unclassifiable alias expected: {check['warnings']!r}")
    warning = check["warnings"][0]
    for needle in ("coder", "llama-3-70b", "cannot"):
        expect(needle in warning, f"the warning must name {needle!r}: {warning!r}")


def case_7_default_matrix(root: pathlib.Path) -> None:
    """`load_default_matrix`: graceful when absent, and the primary/secondary split when present."""
    missing = root / "no-such-config.toml"
    expect(mm.load_default_matrix(missing) == {},
           "a missing config file must yield an empty matrix, not an exception")

    # the same degradation for a config that declares no default_model at all.
    expect(mm.load_default_matrix(write(root, "empty.toml", "# nothing here\n")) == {},
           "a config without default_model must yield an empty matrix")

    fixtures = root / "sub-agents"
    write(fixtures, "coder.md", SUBAGENT_CODER)
    write(fixtures, "tester.md", SUBAGENT_TESTER)
    write(fixtures, "code-reviewer.md", SUBAGENT_REVIEWER)
    write(fixtures, "analyzer.md", SUBAGENT_ANALYZER)

    real_dir = mm.SUBAGENTS_DIR
    try:
        mm.SUBAGENTS_DIR = fixtures
        config = write(root, "config.toml", FIXTURE_CONFIG)
        matrix = mm.load_default_matrix(config)
        expect(matrix.get("coder") == "deepseek-flash",
               f"a secondary role must take [secondary_model] default_model: {matrix!r}")
        expect(matrix.get("tester") == "deepseek-flash",
               f"tester is secondary too: {matrix!r}")
        expect(matrix.get("reviewer") == "kimi-code/k3",
               f"a primary role must take default_model: {matrix!r}")
        expect(matrix.get("analyzer") == "kimi-code/k3",
               f"a file without model_preference runs on primary: {matrix!r}")
        expect("planner" not in matrix,
               f"a role with no sub-agent file must be absent: {matrix!r}")
        expect(mm.family(matrix["coder"]) != mm.family(matrix["reviewer"]),
               f"the default matrix must keep the two sides apart: {matrix!r}")

        primary_only = mm.load_default_matrix(write(root, "primary-only.toml",
                                                    FIXTURE_CONFIG_PRIMARY_ONLY))
        expect(primary_only.get("reviewer") == "kimi-code/k3",
               f"the primary side still resolves: {primary_only!r}")
        expect("coder" not in primary_only,
               f"a secondary role without [secondary_model] must be absent: {primary_only!r}")

        # the REAL sub-agent frontmatter of this repository drives the same split.
        mm.SUBAGENTS_DIR = real_dir
        real = mm.load_default_matrix(config)
        expect(real.get("coder") == "deepseek-flash",
               f"the coder sub-agent is secondary in this repository: {real!r}")
        expect(real.get("reviewer") == "kimi-code/k3",
               f"the code-reviewer sub-agent is primary in this repository: {real!r}")
    finally:
        mm.SUBAGENTS_DIR = real_dir

    # a directory instead of a config file degrades exactly like a missing one.
    expect(mm.load_default_matrix(fixtures) == {},
           "a directory as the config path must not raise")


def case_8_vaccination_probe(root: pathlib.Path) -> None:
    """NEGATIVE probe: the old "substitute the colliding reviewer" behaviour must fail here."""
    task_file = write(root, "task-collision.yaml", FIXTURE_TASK)
    config = write(root, "config-collision.toml", FIXTURE_CONFIG)
    task_matrix = mm.task_models(task_file)
    expect(task_matrix.get("reviewer") == "deepseek-flash",
           f"the fixture task must name the reviewer: {task_matrix!r}")
    default = mm.load_default_matrix(config)
    expect(default.get("reviewer") == "kimi-code/k3",
           f"the default matrix must disagree with the task: {default!r}")

    resolved = mm.resolve_all(task_matrix, default)
    reviewer = resolved["reviewer"]
    expect(reviewer["model"] == "deepseek-flash",
           f"the task's reviewer must NOT be replaced by the default one: {reviewer!r}")
    expect(reviewer["model"] != default["reviewer"],
           f"a substitution would show here: {reviewer!r}")
    expect((reviewer["source"], reviewer["override"]) == ("task", False),
           f"a substituted model would change the source and the override: {reviewer!r}")
    # the coder is the same model on purpose: the collision is real and still not "fixed".
    expect(resolved["coder"]["model"] == reviewer["model"],
           "the fixture is a genuine collision")
    # The family check over the TASK-side models only: exactly the collision warnings, no error.
    # (The fixture default matrix has collisions of its own on roles the task leaves unnamed —
    # that is case 3, not this probe.)
    check = mm.check_families(mm.resolve_all(task_matrix, {}))
    expect(check["errors"] == [], f"a task-side collision must stay a warning: {check!r}")
    expect(any("coder" in warning and "reviewer" in warning for warning in check["warnings"]),
           f"the coder/reviewer collision must be reported: {check['warnings']!r}")


def case_9_precedence_text() -> None:
    """`precedence()` carries (a), (b), (c) and the committee exception in one paragraph."""
    text = mm.precedence()
    lowered = text.lower()
    expect("\n\n" not in text, f"the precedence must be one paragraph: {text!r}")
    for marker in ("(a)", "(b)", "(c)"):
        expect(marker in text, f"the precedence must carry {marker}: {text!r}")
    for needle in ("models:", "task", "default matrix", "no third path", "warning",
                   "override", "committee", "contrast"):
        expect(needle in lowered, f"the precedence must state {needle!r}: {text!r}")
    expect("never substituted" in lowered,
           f"the precedence must forbid substitution on a task collision: {text!r}")
    expect("error" in lowered, f"the default-matrix collision must be an error: {text!r}")
    # the API constants the other packages import.
    expect(mm.GENERATOR_SIDE == ("coder", "tester", "gui_expert"),
           f"GENERATOR_SIDE changed: {mm.GENERATOR_SIDE!r}")
    expect(mm.JUDGE_SIDE == ("reviewer", "diagnostician", "advisor"),
           f"JUDGE_SIDE changed: {mm.JUDGE_SIDE!r}")
    for role in set(mm.GENERATOR_SIDE) | set(mm.JUDGE_SIDE):
        expect(role in mm.ROLES, f"{role} must be a known role: {mm.ROLES!r}")


def case_10_cli(root: pathlib.Path) -> None:
    """The argparse contract and the exit codes of the CLI."""
    helped = run("--help")
    expect(helped.returncode == 0, f"--help must exit 0: {err(helped)!r}")
    expect(b"usage:" in helped.stdout, f"--help must print usage: {out(helped)!r}")

    known = run("family", "--model", "deepseek-flash")
    expect(known.returncode == 0 and out(known).strip() == "deepseek",
           f"family must print deepseek: {out(known)!r}")
    unknown = run("family", "--model", "gpt-4o")
    expect(unknown.returncode == 2, f"an unknown alias must exit 2: {unknown.returncode}")
    expect(b"Traceback" not in unknown.stderr, f"no traceback: {err(unknown)!r}")
    expect("gpt-4o" in err(unknown), f"the message must name the alias: {err(unknown)!r}")

    task_file = write(root, "task-cli.yaml", FIXTURE_TASK)
    config = write(root, "config-cli.toml", FIXTURE_CONFIG)
    # No default_model at all: the task's own matrix decides, so only the collision is left.
    no_defaults = write(root, "config-no-defaults.toml", "# no models configured here\n")
    diverse = write(root, "task-diverse.yaml", FIXTURE_TASK_DIVERSE)
    clean = run("resolve", "--task", str(diverse), "--config", str(no_defaults))
    expect(clean.returncode == 0, f"a clean matrix must exit 0: {out(clean)!r} {err(clean)!r}")
    expect("ERROR:" not in out(clean) and "WARNING:" not in out(clean),
           f"a clean matrix has neither errors nor warnings: {out(clean)!r}")

    ok = run("resolve", "--task", str(task_file), "--config", str(no_defaults))
    expect(ok.returncode == 0, f"a task-side collision must exit 0: {out(ok)!r}")
    body = out(ok)
    expect("reviewer: deepseek-flash [task]" in body,
           f"the reviewer must stay the task's model: {body!r}")
    expect("WARNING:" in body, f"the collision must be reported: {body!r}")
    expect("ERROR:" not in body, f"no error expected here: {body!r}")

    no_models = write(root, "task-empty.yaml", FIXTURE_TASK_NO_MODELS)
    broken = run("resolve", "--task", str(no_models), "--config", str(no_defaults))
    expect(broken.returncode == 0,
           f"no default matrix means no default-matrix error: {out(broken)!r}")

    colliding = write(root, "config-colliding.toml",
                      "default_model = \"deepseek-flash\"\n\n[secondary_model]\n"
                      "default_model = \"deepseek-flash\"\n")
    failing = run("resolve", "--task", str(no_models), "--config", str(colliding))
    expect(failing.returncode == 1,
           f"a default-matrix collision must exit 1: {failing.returncode} {out(failing)!r}")
    expect("ERROR:" in out(failing), f"the error must be printed: {out(failing)!r}")
    expect(b"Traceback" not in failing.stderr, f"no traceback: {err(failing)!r}")

    as_json = run("resolve", "--task", str(task_file), "--config", str(no_defaults), "--json")
    expect(as_json.returncode == 0 and '"resolved"' in out(as_json),
           f"--json must carry the resolution: {out(as_json)!r}")
    expect('"deepseek-flash"' in out(as_json), f"--json must carry the model: {out(as_json)!r}")

    defaulted = run("default", "--config", str(config))
    expect(defaulted.returncode == 0 and "reviewer:" in out(defaulted),
           f"default must print the matrix: {out(defaulted)!r}")
    absent = run("default", "--config", str(root / "no-such-config.toml"))
    expect(absent.returncode == 0, f"a missing config must not fail the CLI: {err(absent)!r}")

    unreadable = run("resolve", "--task", str(root / "no-such-task.yaml"))
    expect(unreadable.returncode == 2, f"an unreadable task must exit 2: {unreadable.returncode}")
    expect("no-such-task.yaml" in err(unreadable),
           f"the message must name the file: {err(unreadable)!r}")
    expect(b"Traceback" not in unreadable.stderr, f"no traceback: {err(unreadable)!r}")

    missing_arg = run("resolve")
    expect(missing_arg.returncode == 2, "a missing --task must exit 2")
    expect(b"Traceback" not in missing_arg.stderr, f"usage errors must not traceback: "
                                                  f"{err(missing_arg)!r}")

    # stdlib-only contract.
    source = pathlib.Path(mm.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", source, flags=re.M))
    allowed = {"__future__", "argparse", "json", "pathlib", "re", "sys"}
    expect(imported <= allowed, f"model_matrix must be stdlib-only, imports={imported}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        case_1_task_value_wins()
        case_2_unnamed_role_falls_back()
        case_3_colliding_default_is_an_error()
        case_4_no_override_outside_the_committee()
        case_5_family_table()
        case_6_unknown_alias_in_the_task()
        case_7_default_matrix(root)
        case_8_vaccination_probe(root)
        case_9_precedence_text()
        case_10_cli(root)

    print("PASS - model_matrix.py keeps the task's model verbatim on a collision (warning only), "
          "falls back to the default matrix for an unnamed role (error when the default matrix "
          "collides), refuses a third path outside the committee's contrasting second planner, "
          "and reports an unclassifiable alias instead of crashing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
