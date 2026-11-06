#!/usr/bin/env python3
"""
Deterministic self-test for `model_attribution.py` (zero LLM tokens, stdlib only).

The contract under test: a model claim (`models_used` in pipeline.yaml) is only worth something
when an ARTIFACT outside the repository confirms it, and the only such artifact is the CLI's own
session wire. So each case builds a synthetic `~/.kimi-code` tree in a tempdir — the tests never
read the real one — and checks what the script concludes from it.

Cases:
  1. a fixture session (main + `deepseek-flash` analyzer + `kimi-k3` coder, wire name `k3`) resolves
     every role from `state.json`, counts the served models per role, sums the usage tokens and
     normalises the wire name `k3` to the alias `kimi-k3`; the matching `models_used` claim set
     yields `match` everywhere, exit 0 and the pipeline's `run_id` in the artifact;
  2. a `models_used` claiming `reviewer: deepseek-flash` while the reviewer wire served `k3` is a
     `mismatch`, exit 1;
  3. a role the pipeline marks `unused` that DOES have wire events is flagged (`mismatch` +
     `flags.unused_but_wired`), exit 1 — never silently accepted;
  4. no session at all (and a session with no wire) is DEGRADED: exit 3, the artifact is still
     written with `attribution_degraded: true` and a one-line reason on stderr;
  5. a nested tool-schema `"model"` key inside prompt / tools-snapshot events is NOT counted as a
     served model (the fixture embeds one), while the events themselves are still read;
  6. `subagent.failed` (and the other error events) are counted in the role's `errors`;
  7. `--session auto --repo <fixture cwd>` picks the right session among three candidates (one
     archived, one foreign, one matching) and `subagent.spawned.subagentName` supplies a role the
     `state.json` does not label;
  8. NEGATIVE/vaccination probe: the fixture of case 2 looks GREEN to the old self-reported
     behaviour (no cross-check -> nothing is compared, exit 0) and is RED under the cross-check —
     the difference is exactly the wire artifact this script adds;
  9. the aliases/roles helpers: `alias_of`, `canonical`, `role_from_profile`, `claim_model`, plus
     the hand `models_used` reader (quotes, prose values, trailing comments, an absent block);
 10. the CLI contract: `--help` exits 0, missing/invalid arguments exit 2 without a traceback, the
     final line is `PASS|FAIL|DEGRADED - <summary> (<out path>)`, `--quiet` prints only that line,
     and the module imports stdlib only;
 11. REGRESSION (review 20261026-1c588b16, major 2): a pipeline whose `models_used` block is empty
     or absent confirms NO role model, so it is DEGRADED (exit 3) — never PASS/exit 0. `verdict_of`
     of an empty comparison is DEGRADED by default; only the claim-free wire report (no
     `--pipeline` at all) exits 0.
 12. REGRESSION (run 20261026-a65b9a6e): a `models_used` key that is no role of the factory (e.g.
     the invented `orchestrator`) is a RUN ERROR — exit 1, the role and the registry named in the
     report, `flags.unknown_roles` listing it — never the DEGRADED "no wire for this role". The
     registry is `model_matrix.ROLES` (plus the non-matrix `main`), imported, not re-declared.
 13. REGRESSION (self-review 20261031-d2f6fea6, critical 9): a role the wire served with the claimed
     model AND a substituted/fallback model is a `mismatch` (exit 1) — the membership test that
     accepted it passed exactly the substitution the anti-substitution gate must reject. The served
     canonical set must EQUAL the singleton claimed set (`k3` and `kimi-k3` are one model).

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
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import model_attribution as ma  # noqa: E402  (after the sys.path guard, so the test runs from anywhere)

TOOL = SCRIPTS / "model_attribution.py"
# The messages carry non-ASCII characters (the em dash): pin UTF-8 on the child's stdout so the
# assertions are portable across console code pages.
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

# Fixed wire timestamps (epoch ms) so first/last event times are asserted, not guessed.
T0 = 1792940000000


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


# ---------------------------------------------------------------------------------------------
# Wire fixtures
# ---------------------------------------------------------------------------------------------

def llm(agent: str, model: str, alias: str | None = None, at: int = T0) -> dict:
    """An `llm.request`: `model` is the wire name, `modelAlias` the CLI alias."""
    return {"type": "llm.request", "agentId": agent, "provider": "openai", "model": model,
            "modelAlias": alias if alias is not None else model, "time": at}


def usage(agent: str, model: str, prompt: int = 100, answer: int = 20,
          cache: int = 5, at: int = T0 + 1) -> dict:
    """A `usage.record`: the token counts the artifact sums, plus a model spelling."""
    return {"type": "usage.record", "agentId": agent, "model": model, "usageScope": "turn",
            "usage": {"inputOther": prompt, "output": answer, "inputCacheRead": cache,
                      "inputCacheCreation": 0}, "time": at}


def spawned(subagent: str, name: str, model: str, at: int = T0) -> dict:
    """A `subagent.spawned`: lives in the PARENT wire and names the role profile."""
    return {"type": "subagent.spawned", "subagentId": subagent, "subagentName": name,
            "parentAgentId": "main", "callerAgentId": "main", "model": model, "time": at}


def failed(kind: str, subagent: str | None = None, agent: str | None = None,
           at: int = T0 + 2) -> dict:
    """An error event: `subagent.*` carries `subagentId`, the turn/prompt ones `agentId`."""
    event = {"type": kind, "time": at}
    if subagent is not None:
        event["subagentId"] = subagent
    if agent is not None:
        event["agentId"] = agent
    return event


def build_session(home: pathlib.Path, cwd: pathlib.Path, sid: str, wires: dict,
                  profiles: dict | None = None, archived: bool = False) -> pathlib.Path:
    """Write one fixture session: `state.json` + `agents/<id>/wire.jsonl` per agent.

    `wires` maps an agent id to its event list; `profiles` maps an agent id to the
    `labels.profileName` the CLI would record. An agent absent from `profiles` gets NO `labels`
    key at all — the shape of a session whose state file does not name the role (case 7).
    """
    session_dir = pathlib.Path(home) / "sessions" / f"wd_fixture_{sid}" / sid
    state = {"id": sid, "cwd": str(cwd).replace("\\", "/"), "archived": archived, "agents": {}}
    for agent_id in wires:
        entry = {"type": "main" if agent_id == "main" else "sub", "homedir": agent_id}
        if agent_id != "main":
            entry["parentAgentId"] = "main"
        profile = (profiles or {}).get(agent_id)
        if profile:
            entry["labels"] = {"parentAgentId": "main", "profileName": profile}
        state["agents"][agent_id] = entry
    write(session_dir, "state.json", json.dumps(state, indent=2) + "\n")
    for agent_id, events in wires.items():
        body = "\n".join(json.dumps(event) for event in events)
        write(session_dir / "agents" / agent_id, "wire.jsonl", body + ("\n" if body else ""))
    return session_dir


def write_index(home: pathlib.Path, entries: list[dict]) -> pathlib.Path:
    body = "\n".join(json.dumps(entry) for entry in entries)
    return write(pathlib.Path(home), "session_index.jsonl", body + ("\n" if body else ""))


def pipeline(*claims: tuple[str, str], run_id: str = "20261025-4e17a349") -> str:
    """A minimal pipeline.yaml carrying `models_used` (quoted where the prose needs it)."""
    lines = [f'run_id: {run_id}', 'phase: "implement"', "status: in_progress",
             'updated_at: "2026-10-25T21:05:00+03:00"', "models_used:"]
    for index, (role, claim) in enumerate(claims, 1):
        value = claim if re.fullmatch(r"[A-Za-z0-9_.\-/]+", claim) else f'"{claim}"'
        lines.append(f"  {role}: {value}")
    return "\n".join(lines) + "\n"


def contract_pipeline(claims: tuple[tuple[str, str], ...], task_type: str | None = None,
                      required_roles: tuple[str, ...] = (),
                      run_id: str = "20261025-4e17a349") -> str:
    """A pipeline.yaml carrying the strict-attribution contract: task_type + required_roles."""
    lines: list[str] = []
    if task_type is not None:
        lines.append(f"task_type: {task_type}")
    if required_roles:
        lines.append("required_roles:")
        lines.extend(f"  - {role}" for role in required_roles)
    lines.extend([f"run_id: {run_id}", 'phase: "implement"', "status: in_progress",
                  'updated_at: "2026-10-25T21:05:00+03:00"', "models_used:"])
    for role, claim in claims:
        value = claim if re.fullmatch(r"[A-Za-z0-9_.\-/]+", claim) else f'"{claim}"'
        lines.append(f"  {role}: {value}")
    return "\n".join(lines) + "\n"


def standard_session(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """The case-1 fixture: a home dir, and the repo whose session it holds."""
    home = root / "home"
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    build_session(home, repo, "session_11111111-1111-4111-8111-111111111111", {
        "main": [llm("main", "k3", "kimi-k3", at=T0),
                 spawned("agent-0", "factory-analyzer", "deepseek-flash", at=T0),
                 spawned("agent-1", "factory-coder", "kimi-k3", at=T0)],
        "agent-0": [llm("agent-0", "deepseek-flash", at=T0 + 10),
                    usage("agent-0", "deepseek-flash", at=T0 + 11),
                    llm("agent-0", "deepseek-flash", at=T0 + 20),
                    usage("agent-0", "deepseek-flash", at=T0 + 21),
                    llm("agent-0", "deepseek-flash", at=T0 + 30),
                    usage("agent-0", "deepseek-flash", at=T0 + 31)],
        "agent-1": [llm("agent-1", "k3", "kimi-k3", at=T0 + 40),
                    usage("agent-1", "kimi-k3", at=T0 + 41),
                    llm("agent-1", "k3", "kimi-k3", at=T0 + 50),
                    usage("agent-1", "kimi-k3", at=T0 + 51)],
    }, profiles={"agent-0": "factory-analyzer", "agent-1": "factory-coder"})
    write_index(home, [{"sessionId": "session_11111111-1111-4111-8111-111111111111",
                        "sessionDir": str(home / "sessions" / "wd_fixture" / "session_1"),
                        "workDir": str(repo).replace("\\", "/")}])
    return home, repo


def attr(root: pathlib.Path, home: pathlib.Path, repo: pathlib.Path, *extra: str,
         name: str = "attribution.json") -> tuple[subprocess.CompletedProcess[bytes], dict, str]:
    """Run the CLI against a fixture home and return (result, artifact, out path)."""
    target = root / name
    res = run("--session", "auto", "--repo", str(repo), "--out", str(target),
              "--home", str(home), *extra)
    artifact = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
    return res, artifact, out(res)


# ---------------------------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------------------------

def case_1_roles_and_counts(root: pathlib.Path) -> None:
    """Roles from state.json, models counted per role, k3 normalised to kimi-k3, exit 0."""
    home, repo = standard_session(root)
    spec = write(root, "pipeline-ok.yaml",
                 pipeline(("main", "kimi-k3"), ("analyzer", "deepseek-flash"), ("coder", "kimi-k3")))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec))
    expect(res.returncode == 0, f"a matching claim set must exit 0: {text!r} {err(res)!r}")
    expect(artifact["attribution_degraded"] is False,
           f"a resolved session is not degraded: {artifact.get('degraded_reason')!r}")
    expect(artifact["resolved_by"] == "auto", f"auto resolved the session: {artifact['resolved_by']!r}")
    expect(artifact["run_id"] == "20261025-4e17a349",
           f"the pipeline run_id must land in the artifact: {artifact['run_id']!r}")
    expect(artifact["session"]["id"] == "session_11111111-1111-4111-8111-111111111111",
           f"the resolved session id is wrong: {artifact['session']!r}")
    expect(artifact["session"]["candidates"] == 1 and artifact["session"]["index_agrees"],
           f"one candidate, corroborated by session_index: {artifact['session']!r}")

    roles = artifact["roles"]
    expect(sorted(roles) == ["analyzer", "coder", "main"],
           f"three roles expected from state.json labels: {sorted(roles)}")
    expect(roles["analyzer"]["models_served"] == {"deepseek-flash": 3},
           f"the analyzer served deepseek-flash three times: {roles['analyzer']!r}")
    expect(roles["coder"]["models_served"] == {"kimi-k3": 2},
           f"the wire name k3 must normalise to the alias kimi-k3: {roles['coder']!r}")
    expect(roles["main"]["models_served"] == {"kimi-k3": 1},
           f"main served kimi-k3 once: {roles['main']!r}")
    expect(roles["analyzer"]["tokens"]["total"] == 3 * (100 + 20 + 5),
           f"usage.record tokens must be summed per role: {roles['analyzer']['tokens']!r}")
    expect(roles["analyzer"]["tokens"]["output"] == 60,
           f"the per-field sums must survive: {roles['analyzer']['tokens']!r}")
    expect(roles["analyzer"]["spawn_model"] == "deepseek-flash",
           f"the model the parent asked for is recorded: {roles['analyzer']!r}")
    expect(roles["analyzer"]["first_event"].endswith("Z") and roles["analyzer"]["first_event"],
           f"event times are ISO-8601 UTC: {roles['analyzer']!r}")
    expect(roles["analyzer"]["agents"] == ["agent-0"], f"membership: {roles['analyzer']!r}")

    agents = artifact["agents"]
    expect(agents["main"]["role"] == "main" and agents["agent-1"]["role"] == "coder",
           f"every agent must carry its role: {agents!r}")
    expect(agents["agent-1"]["profile"] == "factory-coder",
           f"the raw profile is kept for provenance: {agents['agent-1']!r}")

    expect(artifact["comparison"] == {"main": "match", "analyzer": "match", "coder": "match"},
           f"every claim must match the wire: {artifact['comparison']!r}")
    expect("analyzer: match (claimed=deepseek-flash wire=[deepseek-flash:3])" in text,
           f"the printed line must carry the evidence: {text!r}")
    expect(text.strip().endswith(f"({root / 'attribution.json'})"),
           f"the final line must end with the artifact path: {text!r}")


def case_2_mismatch(root: pathlib.Path) -> None:
    """A claim the wire disproves is a mismatch and exit 1."""
    home = root / "home2"
    repo = root / "repo2"
    repo.mkdir(parents=True, exist_ok=True)
    build_session(home, repo, "session_22222222-2222-4222-8222-222222222222", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 spawned("agent-0", "factory-code-reviewer", "kimi-k3", at=T0)],
        "agent-0": [llm("agent-0", "k3", "kimi-k3", at=T0 + 10),
                    usage("agent-0", "kimi-k3", at=T0 + 11)],
    }, profiles={"agent-0": "factory-code-reviewer"})
    spec = write(root, "pipeline-mismatch.yaml",
                 pipeline(("main", "deepseek-flash"), ("reviewer", "deepseek-flash")))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="mismatch.json")
    expect(res.returncode == 1, f"a mismatch must exit 1: {text!r} {err(res)!r}")
    expect(artifact["comparison"] == {"main": "match", "reviewer": "mismatch"},
           f"only the reviewer mismatches: {artifact['comparison']!r}")
    expect(artifact["verdict"] == "FAIL", f"the verdict must be FAIL: {artifact['verdict']!r}")
    expect("reviewer: mismatch (claimed=deepseek-flash wire=[kimi-k3:1])" in text,
           f"the mismatch line must name claim and wire: {text!r}")
    expect("FAIL - 1 of 2 claimed role(s) do not match the wire" in text,
           f"the summary must count it: {text!r}")
    expect("reviewer claimed=deepseek-flash wire=[kimi-k3:1]" in text,
           f"the summary must name the substituted model: {text!r}")
    expect(artifact["roles"]["reviewer"]["models_served"] == {"kimi-k3": 1},
           f"the reviewer wire evidence: {artifact['roles']['reviewer']!r}")


def case_3_unused_role_with_events(root: pathlib.Path) -> None:
    """A role marked `unused` that the wire DID serve is flagged, not accepted."""
    home = root / "home3"
    repo = root / "repo3"
    repo.mkdir(parents=True, exist_ok=True)
    build_session(home, repo, "session_33333333-3333-4333-8333-333333333333", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 spawned("agent-0", "factory-tester", "kimi-k3", at=T0)],
        "agent-0": [llm("agent-0", "k3", "kimi-k3", at=T0 + 10)],
    }, profiles={"agent-0": "factory-tester"})
    spec = write(root, "pipeline-unused.yaml",
                 pipeline(("main", "deepseek-flash"), ("tester", "unused"),
                          ("reviewer", "unused")))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="unused.json")
    expect(res.returncode == 1, f"an unused claim with wire events must exit 1: {text!r}")
    expect(artifact["comparison"]["tester"] == "mismatch",
           f"the tester claim must be disproven: {artifact['comparison']!r}")
    expect(artifact["flags"]["unused_but_wired"] == ["tester"],
           f"the flag must name the role: {artifact['flags']!r}")
    expect(artifact["comparison"]["reviewer"] == "match",
           f"an unused claim with NO wire events matches: {artifact['comparison']!r}")
    expect(artifact["claims"]["unused"] == ["tester", "reviewer"],
           f"the unused sentinels must be listed: {artifact['claims']!r}")
    expect("tester: mismatch (claimed=unused wire=[kimi-k3:1])" in text,
           f"the flagged line must say what happened: {text!r}")
    expect("the pipeline marks the role unused, but the wire served it" in text,
           f"the reason must be explicit: {text!r}")


def case_4_degraded(root: pathlib.Path) -> None:
    """No session (and a session without wire) is DEGRADED: exit 3, artifact still written."""
    home = root / "home4"
    repo = root / "repo4"
    repo.mkdir(parents=True, exist_ok=True)
    spec = write(root, "pipeline-degraded.yaml", pipeline(("main", "deepseek-flash")))
    res, artifact, text = attr(root, home, repo, name="degraded.json")
    expect(res.returncode == 3, f"no session must exit 3: {res.returncode} {text!r} {err(res)!r}")
    expect(artifact.get("attribution_degraded") is True,
           f"the artifact must admit the degradation: {artifact.get('attribution_degraded')!r}")
    expect(artifact.get("verdict") == "DEGRADED", f"verdict: {artifact.get('verdict')!r}")
    expect("no session" in (artifact.get("degraded_reason") or ""),
           f"the reason must say why: {artifact.get('degraded_reason')!r}")
    expect(text.strip().startswith("DEGRADED - "), f"the final line: {text!r}")
    expect("attribution is not possible" in text, f"the summary must say it plainly: {text!r}")
    stderr_lines = [line for line in err(res).splitlines() if line.strip()]
    expect(len(stderr_lines) == 1 and "DEGRADED" in stderr_lines[0],
           f"exactly one reason line on stderr: {err(res)!r}")

    # The same run WITH a claim set: every claim is unverified, still exit 3.
    res2, artifact2, text2 = attr(root, home, repo, "--pipeline", str(spec), name="degraded2.json")
    expect(res2.returncode == 3, f"degraded with claims is still exit 3: {text2!r}")
    expect(artifact2["comparison"] == {"main": "unverified"},
           f"a claim without wire evidence is unverified: {artifact2['comparison']!r}")
    expect("main: unverified (claimed but no wire agent)" in text2,
           f"the unverified line: {text2!r}")

    # A session directory that exists but holds no wire at all is DEGRADED too (never 0).
    empty = root / "repo4-empty"
    empty.mkdir(parents=True, exist_ok=True)
    build_session(home, empty, "session_44444444-4444-4444-8444-444444444444", {})
    res3, artifact3, text3 = attr(root, home, empty, name="degraded3.json")
    expect(res3.returncode == 3, f"a session without a wire must exit 3: {text3!r}")
    expect("no agents/*/wire.jsonl" in (artifact3.get("degraded_reason") or ""),
           f"the reason must name the missing wire: {artifact3.get('degraded_reason')!r}")
    expect(artifact3["session"]["id"] == "session_44444444-4444-4444-8444-444444444444",
           f"the session that WAS found is still named: {artifact3['session']!r}")


def case_5_nested_model_keys_ignored(root: pathlib.Path) -> None:
    """A `"model"` key inside tool-schema/prompt JSON is not a served model."""
    home = root / "home5"
    repo = root / "repo5"
    repo.mkdir(parents=True, exist_ok=True)
    decoy_schema = json.dumps({"name": "spawn", "parameters": {"properties": {
        "model": {"type": "string", "default": "schema-decoy"}}}})
    build_session(home, repo, "session_55555555-5555-4555-8555-555555555555", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 {"type": "context.append_message", "agentId": "main", "time": T0 + 1,
                  "message": {"role": "user",
                              "content": [{"type": "text",
                                           "text": 'tools: [{"model": "schema-decoy"}]'}]}},
                 {"type": "llm.tools_snapshot", "agentId": "main", "time": T0 + 2,
                  "tools": [{"type": "function", "function": {"name": "spawn",
                                                              "parameters": json.loads(decoy_schema)}}]},
                 {"type": "turn.prompt", "agentId": "main", "time": T0 + 3,
                  "prompt": '{"model": "schema-decoy", "modelAlias": "schema-decoy"}'}],
    }, profiles={})
    res, artifact, text = attr(root, home, repo, name="decoy.json")
    expect(res.returncode == 0, f"reading an undecided session is not a failure: {text!r}")
    expect(artifact["roles"]["main"]["models_served"] == {"deepseek-flash": 1},
           f"the decoy models must NOT be counted: {artifact['roles']['main']!r}")
    expect("schema-decoy" not in json.dumps(artifact["roles"]),
           f"no role may mention the decoy: {artifact['roles']!r}")
    expect(artifact["agents"]["main"]["events"] == 4,
           f"the decoy events are still READ (proving the scan happened): "
           f"{artifact['agents']['main']!r}")
    expect(not artifact["comparison"], f"no claims, no comparison: {artifact['comparison']!r}")


def case_6_error_events(root: pathlib.Path) -> None:
    """`subagent.failed` and friends are counted per role's `errors`."""
    home = root / "home6"
    repo = root / "repo6"
    repo.mkdir(parents=True, exist_ok=True)
    build_session(home, repo, "session_66666666-6666-4666-8666-666666666666", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 spawned("agent-0", "factory-tester", "kimi-k3", at=T0),
                 spawned("agent-1", "factory-coder", "deepseek-flash", at=T0),
                 failed("subagent.failed", subagent="agent-0", at=T0 + 5),
                 failed("subagent.cancelled", subagent="agent-0", at=T0 + 6),
                 failed("subagent.failed", subagent="agent-1", at=T0 + 7)],
        "agent-1": [llm("agent-1", "deepseek-flash", at=T0 + 10),
                    failed("turn.step.retrying", agent="agent-1", at=T0 + 11),
                    failed("turn.cancel", agent="agent-1", at=T0 + 12),
                    failed("prompt.aborted", agent="agent-1", at=T0 + 13)],
    }, profiles={"agent-0": "factory-tester", "agent-1": "factory-coder"})
    res, artifact, text = attr(root, home, repo, name="errors.json")
    expect(res.returncode == 0, f"errors are not a failure of attribution: {text!r}")
    roles = artifact["roles"]
    expect(roles["tester"]["errors"] == {"subagent.failed": 1, "subagent.cancelled": 1},
           f"the failed/cancelled events belong to the TESTER: {roles['tester']!r}")
    expect(roles["coder"]["errors"] == {"subagent.failed": 1, "turn.step.retrying": 1,
                                        "turn.cancel": 1, "prompt.aborted": 1},
           f"the coder's own error events: {roles['coder']!r}")
    expect(roles["main"]["errors"] == {},
           f"the parent's wire must not be charged for a subagent's failure: {roles['main']!r}")
    expect(artifact["agents"]["agent-0"]["errors"] == {"subagent.failed": 1,
                                                       "subagent.cancelled": 1},
           f"the per-agent record carries them too: {artifact['agents']['agent-0']!r}")


def case_7_auto_resolution(root: pathlib.Path) -> None:
    """Auto picks the matching session among three; the spawn event can supply a missing role."""
    home = root / "home7"
    repo = root / "repo7"
    other = root / "someone-else"
    repo.mkdir(parents=True, exist_ok=True)
    other.mkdir(parents=True, exist_ok=True)
    # Candidate 1: the right cwd, but ARCHIVED.
    build_session(home, repo, "session_77777777-7777-4777-8777-777777777777", {
        "main": [llm("main", "deepseek-flash", at=T0)]}, archived=True)
    # Candidate 2: a foreign cwd.
    build_session(home, other, "session_88888888-8888-4888-8888-888888888888", {
        "main": [llm("main", "kimi-k3", at=T0)]})
    # Candidate 3: the one that matches — and its state carries NO profileName at all, so the
    # role has to come from `subagent.spawned.subagentName`.
    build_session(home, repo, "session_99999999-9999-4999-8999-999999999999", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 spawned("agent-0", "factory-analyzer", "deepseek-flash", at=T0)],
        "agent-0": [llm("agent-0", "deepseek-flash", at=T0 + 10)],
    })
    write_index(home, [
        {"sessionId": "session_77777777-7777-4777-8777-777777777777",
         "sessionDir": "archived", "workDir": str(repo).replace("\\", "/")},
        {"sessionId": "session_99999999-9999-4999-8999-999999999999",
         "sessionDir": "current", "workDir": str(repo).replace("\\", "/")},
    ])
    spec = write(root, "pipeline-auto.yaml", pipeline(("main", "deepseek-flash"),
                                                      ("analyzer", "deepseek-flash")))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="auto.json")
    expect(res.returncode == 0, f"the matching session must be picked: {text!r} {err(res)!r}")
    expect(artifact["session"]["id"] == "session_99999999-9999-4999-8999-999999999999",
           f"wrong session picked: {artifact['session']!r}")
    expect(artifact["session"]["candidates"] == 1,
           f"only the unarchived matching session is a candidate: {artifact['session']!r}")
    expect(artifact["session"]["index_agrees"] is True,
           f"session_index corroborates the pick: {artifact['session']!r}")
    expect(artifact["resolved_by"] == "auto", f"resolved_by: {artifact['resolved_by']!r}")
    expect(artifact["roles"].get("analyzer", {}).get("models_served") == {"deepseek-flash": 1},
           f"the role must come from subagent.spawned.subagentName: {artifact['roles']!r}")
    expect(artifact["agents"]["agent-0"]["profile"] == "factory-analyzer",
           f"the spawn name is the profile of record: {artifact['agents']['agent-0']!r}")

    # An explicit session directory is used as-is, even when its cwd is another repo.
    foreign = (home / "sessions" / "wd_fixture_session_88888888-8888-4888-8888-888888888888"
               / "session_88888888-8888-4888-8888-888888888888")
    explicit = run("--session", str(foreign), "--repo", str(repo),
                   "--out", str(root / "explicit.json"), "--home", str(home))
    expect(explicit.returncode == 0, f"an explicit session must be read: {out(explicit)!r}")
    explicit_artifact = json.loads((root / "explicit.json").read_text(encoding="utf-8"))
    expect(explicit_artifact["resolved_by"] == "arg",
           f"an explicit session is resolved_by arg: {explicit_artifact['resolved_by']!r}")
    expect(explicit_artifact["session"]["id"] == "session_88888888-8888-4888-8888-888888888888",
           f"the explicit session must win: {explicit_artifact['session']!r}")


def case_8_vaccination(root: pathlib.Path) -> None:
    """The old self-reported view is green on a fixture the wire proves wrong (negative probe)."""
    home = root / "home8"
    repo = root / "repo8"
    repo.mkdir(parents=True, exist_ok=True)
    build_session(home, repo, "session_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 spawned("agent-0", "factory-code-reviewer", "kimi-k3", at=T0)],
        "agent-0": [llm("agent-0", "k3", "kimi-k3", at=T0 + 10)],
    }, profiles={"agent-0": "factory-code-reviewer"})
    spec = write(root, "pipeline-claim.yaml",
                 pipeline(("main", "deepseek-flash"), ("reviewer", "deepseek-flash")))

    # The claim is what the factory would have written in report.md: reviewer = deepseek-flash.
    claimed = ma.read_models_used(spec)[1]
    expect(claimed["reviewer"] == "deepseek-flash", f"the fixture claim: {claimed!r}")

    # Old behaviour (no cross-check): nothing to compare -> PASS, exit 0 — the substitution hides.
    green, green_artifact, green_text = attr(root, home, repo, name="green.json")
    expect(green.returncode == 0, f"the self-reported view is GREEN: {green_text!r}")
    expect(green_artifact["comparison"] == {},
           f"without the cross-check nothing is compared: {green_artifact['comparison']!r}")
    expect(green_text.strip().splitlines()[-1].startswith("PASS - "),
           f"the old view looks green: {green_text!r}")

    # New behaviour: the same fixture is RED, and the reason is the wire, not the claim.
    red, red_artifact, red_text = attr(root, home, repo, "--pipeline", str(spec), name="red.json")
    expect(red.returncode == 1, f"the cross-check must turn it RED: {red_text!r}")
    expect(red_text.strip().splitlines()[-1].startswith("FAIL - "),
           f"the new view fails: {red_text!r}")
    expect(red_artifact["comparison"]["reviewer"] == "mismatch",
           f"the wire disproves the claim: {red_artifact['comparison']!r}")
    expect(red_artifact["roles"]["reviewer"]["models_served"] == {"kimi-k3": 1},
           f"the artifact proves the substitution: {red_artifact['roles']['reviewer']!r}")


def case_9_helpers(root: pathlib.Path) -> None:
    """The alias/role helpers, the API constants and the hand `models_used` reader."""
    # The event tables this script's whole honesty rests on: a model is read from THESE types only.
    expect(ma.MODEL_EVENTS == ("llm.request", "usage.record", "subagent.spawned"),
           f"MODEL_EVENTS changed: {ma.MODEL_EVENTS!r}")
    expect(ma.ERROR_EVENTS == ("subagent.failed", "subagent.cancelled", "turn.cancel",
                               "prompt.aborted", "turn.step.retrying"),
           f"ERROR_EVENTS changed: {ma.ERROR_EVENTS!r}")
    expect("context.append_message" not in ma.MODEL_EVENTS
           and "llm.tools_snapshot" not in ma.MODEL_EVENTS,
           "a prompt/tool-schema event must never be a model source")

    # alias_of: the alias wins over the wire name; a provider prefix is not part of the identity.
    expect(ma.alias_of({"model": "k3", "modelAlias": "kimi-k3"}) == "kimi-k3",
           "the CLI alias must win over the wire name")
    expect(ma.alias_of({"model": "k3"}) == "k3", "without an alias the wire name is all there is")
    expect(ma.alias_of({"model": "KIMI-CODE/K3"}) == "k3",
           "a provider-qualified name is reduced to its model part")
    expect(ma.alias_of({"model": None, "modelAlias": ""}) == "", "an empty event has no alias")

    # canonical: the comparison key is `<vendor>/<version>` — only documented spellings of the
    # SAME vendor normalize together, the vendor itself is never folded away.
    expect(ma.canonical("kimi-k3") == ma.canonical("k3") == ma.canonical("kimi-code/k3")
           == "kimi/k3",
           "the three spellings of the same model must compare equal")
    expect(ma.canonical("moonshot-k3") == "kimi/k3",
           "moonshot is a documented spelling of the Kimi vendor")
    expect(ma.canonical("kimi-k2") != ma.canonical("kimi-k3"),
           "two DIFFERENT versions must never compare equal")
    expect(ma.canonical("deepseek-flash") == "deepseek-flash", "a named model is not folded")
    expect(ma.canonical("deepseek-v4-pro") == "deepseek/v4-pro",
           "a version token keeps its vendor in the key")
    # (C28, review 20261104-b5b601f6, critical 28) a cross-vendor same-version pair must NEVER
    # compare equal: `kimi-k3` and `deepseek-k3` are different models, and a substitution of one
    # for the other is a mismatch, not a match.
    expect(ma.canonical("kimi-k3") != ma.canonical("deepseek-k3"),
           f"cross-vendor same-version aliases must differ: {ma.canonical('kimi-k3')!r} vs "
           f"{ma.canonical('deepseek-k3')!r}")
    cross = ma.compare_claims({"coder": "kimi-k3"},
                              {"coder": {"models_served": {"deepseek-k3": 2}}})
    expect(cross[0] == {"coder": "mismatch"},
           f"a cross-vendor same-version substitution must be a mismatch: {cross[1]!r}")
    expect(ma.verdict_of(cross[0]) == "FAIL",
           "a cross-vendor substitution must FAIL the run, never pass the gate")

    # role_from_profile
    expect(ma.role_from_profile("factory-analyzer") == "analyzer", "prefix stripped")
    expect(ma.role_from_profile("factory-code-reviewer") == "reviewer", "code-reviewer -> reviewer")
    expect(ma.role_from_profile("factory-gui-expert") == "gui_expert", "gui-expert -> gui_expert")
    expect(ma.role_from_profile("factory-farukon-expert") == "farukon_expert",
           "farukon-expert -> farukon_expert")
    expect(ma.role_from_profile("factory-security-auditor") == "security_auditor",
           "security-auditor -> security_auditor")
    expect(ma.role_from_profile("factory-skill-manager") == "skill_manager",
           "skill-manager -> skill_manager")
    expect(ma.role_from_profile("main") == "main", "main stays main")
    expect(ma.role_from_profile("") == "", "an unnamed profile is empty, not invented")

    # claim_model / is_unused
    expect(ma.claim_model("deepseek-flash (plan written by the main agent)") == "deepseek-flash",
           "the model token of a prose claim")
    expect(ma.claim_model('"kimi-k3"') == "kimi-k3", "quotes are not part of the claim")
    expect(ma.is_unused("unused") and ma.is_unused("unused (plan by main)"),
           "the unused sentinel is recognised")
    expect(not ma.is_unused("deepseek-flash"), "a model is not the unused sentinel")

    # read_models_used: quotes, a trailing comment, prose values, and an absent block.
    spec = write(root, "pipeline-shape.yaml", "\n".join([
        'run_id: "20261025-deadbeef"',
        "phase: implement",
        "models_used:",
        "  main: deepseek-flash   # primary",
        '  reviewer: "kimi-k3"',
        '  planner: "deepseek-flash (plan written by the main agent)"',
        "retry_counters:",
        "  coder: 0",
        "",
    ]))
    run_id, claims = ma.read_models_used(spec)
    expect(run_id == "20261025-deadbeef", f"run_id must be unquoted: {run_id!r}")
    expect(claims == {"main": "deepseek-flash", "reviewer": "kimi-k3",
                      "planner": "deepseek-flash (plan written by the main agent)"},
           f"the flat models_used block must survive: {claims!r}")
    expect("retry_counters" not in claims, f"the block must end at the next key: {claims!r}")
    no_block = write(root, "pipeline-empty.yaml", "run_id: 20261025-0badf00d\nstatus: ok\n")
    expect(ma.read_models_used(no_block) == ("20261025-0badf00d", {}),
           "an absent models_used block is an empty claim set")
    try:
        ma.read_models_used(root / "no-such-pipeline.yaml")
    except ma.AttributionError:
        pass
    else:
        raise AssertionError("an unreadable pipeline must raise AttributionError (exit 2)")

    # verdict_of: a mismatch is never hidden by a degradation.
    expect(ma.verdict_of({"a": "match"}) == "PASS", "all matching -> PASS")
    expect(ma.verdict_of({"a": "mismatch", "b": "degraded"}) == "FAIL",
           "a proven mismatch wins over a degradation")
    expect(ma.verdict_of({"a": "degraded"}) == "DEGRADED", "an unconfirmed role -> DEGRADED")
    expect(ma.verdict_of({}, "no session") == "DEGRADED", "a reason alone -> DEGRADED")


def case_10_cli(root: pathlib.Path) -> None:
    """The argparse contract, the exit codes and the final-line shape."""
    helped = run("--help")
    expect(helped.returncode == 0, f"--help must exit 0: {err(helped)!r}")
    expect(b"usage:" in helped.stdout, f"--help must print usage: {out(helped)!r}")

    missing = run("--repo", str(root))
    expect(missing.returncode == 2, f"a missing --out must exit 2: {missing.returncode}")
    expect(b"Traceback" not in missing.stderr, f"usage errors must not traceback: {err(missing)!r}")

    bad_session = run("--session", str(root / "no-such-session"), "--repo", str(root),
                      "--out", str(root / "x.json"))
    expect(bad_session.returncode == 2, f"a bad --session path must exit 2: {out(bad_session)!r}")
    expect("no-such-session" in err(bad_session), f"the message must name it: {err(bad_session)!r}")
    expect(b"Traceback" not in bad_session.stderr, f"no traceback: {err(bad_session)!r}")

    bad_pipeline = run("--repo", str(root), "--out", str(root / "y.json"),
                       "--pipeline", str(root / "no-such-pipeline.yaml"))
    expect(bad_pipeline.returncode == 2,
           f"an unreadable --pipeline must exit 2: {out(bad_pipeline)!r} {err(bad_pipeline)!r}")
    expect(b"Traceback" not in bad_pipeline.stderr, f"no traceback: {err(bad_pipeline)!r}")

    # A wire the script cannot open is an INPUT error (AttributionError -> exit 2), not a silent
    # zero: an unreadable wire must never be mistaken for "the model was never served".
    home = root / "home10"
    repo = root / "repo10"
    repo.mkdir(parents=True, exist_ok=True)
    session_dir = build_session(home, repo, "session_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", {
        "main": [llm("main", "deepseek-flash", at=T0)]})
    real_read_text = pathlib.Path.read_text

    def locked_read_text(self, *args, **kwargs):
        if self.name == "wire.jsonl":
            raise PermissionError("locked by another process")
        return real_read_text(self, *args, **kwargs)

    pathlib.Path.read_text = locked_read_text
    try:
        ma.analyse_session(session_dir)
    except ma.AttributionError as exc:
        expect("wire.jsonl" in str(exc), f"the error must name the wire: {exc}")
    else:
        raise AssertionError("an unreadable wire must raise AttributionError (exit 2)")
    finally:
        pathlib.Path.read_text = real_read_text

    # A session carrying no wire FILE at all is DEGRADED (exit 3), and still never 0.
    wire_dir = session_dir / "agents" / "main" / "wire.jsonl"
    wire_dir.unlink()
    wire_dir.mkdir()                     # a directory where the wire file should be
    empty_wire = run("--session", str(session_dir), "--repo", str(repo),
                     "--out", str(root / "no-wire.json"))
    expect(empty_wire.returncode == 3,
           f"a session with no wire must exit 3: {empty_wire.returncode} {out(empty_wire)!r}")
    expect(b"Traceback" not in empty_wire.stderr, f"no traceback: {err(empty_wire)!r}")

    # The final line of a real run, and --quiet printing only that line.
    home2, repo2 = standard_session(root / "cli")
    loud = run("--session", "auto", "--repo", str(repo2), "--out", str(root / "loud.json"),
               "--home", str(home2))
    expect(loud.returncode == 0, f"the clean fixture must exit 0: {out(loud)!r} {err(loud)!r}")
    final = out(loud).strip().splitlines()[-1]
    expect(re.match(r"^(PASS|FAIL|DEGRADED) - .+ \(.+\)$", final),
           f"the final line must be 'PASS|FAIL|DEGRADED - <summary> (<out path>)': {final!r}")
    quiet = run("--session", "auto", "--repo", str(repo2), "--out", str(root / "quiet.json"),
                "--home", str(home2), "--quiet")
    expect(quiet.returncode == 0, f"--quiet must not change the verdict: {err(quiet)!r}")
    expect(len(out(quiet).strip().splitlines()) == 1,
           f"--quiet prints only the summary line: {out(quiet)!r}")

    # stdlib-only contract (plus the one sibling registry module — a second copy of the role list
    # would be exactly the drift the registry import prevents).
    source = pathlib.Path(ma.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", source, flags=re.M))
    allowed = {"__future__", "argparse", "datetime", "hashlib", "json", "model_matrix", "pathlib",
               "re", "sys", "tempfile"}
    expect(imported <= allowed,
           f"model_attribution must be stdlib-only, imports={sorted(imported - allowed)}")


def case_11_no_claims_is_degraded(root: pathlib.Path) -> None:
    """Regression (review 20261026-1c588b16, major 2): no claim set is DEGRADED, never PASS.

    `verdict_of({})` used to answer PASS, so a run with a session but a pipeline that names no
    role in `models_used` exited 0 — "every claimed role matches the wire" is vacuously true, yet
    NOT ONE model was confirmed. The owner reads exit 0 as an artifact-backed confirmation, so an
    empty claim set must be DEGRADED (exit 3), exactly like the missing wire.
    """
    home, repo = standard_session(root / "noclaims")

    # 1) The `models_used:` block is present but names no role.
    empty_block = write(root, "pipeline-no-claims.yaml", "\n".join([
        "run_id: 20261026-2ea2eb55", "phase: implement", "status: ok", "models_used:", ""]))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(empty_block),
                               name="no-claims.json")
    expect(res.returncode == 3,
           f"an empty models_used set must be DEGRADED (exit 3), not {res.returncode}: {text!r}")
    expect(artifact["verdict"] == "DEGRADED", f"the verdict: {artifact.get('verdict')!r}")
    expect(artifact["attribution_degraded"] is True,
           f"the artifact must admit it: {artifact.get('attribution_degraded')!r}")
    expect(artifact["comparison"] == {}, f"nothing was compared: {artifact['comparison']!r}")
    expect("models_used" in (artifact.get("degraded_reason") or ""),
           f"the reason must name the empty claim set: {artifact.get('degraded_reason')!r}")
    expect(text.strip().splitlines()[-1].startswith("DEGRADED - "),
           f"the final line must not read PASS: {text!r}")
    stderr_lines = [line for line in err(res).splitlines() if line.strip()]
    expect(len(stderr_lines) == 1 and "DEGRADED" in stderr_lines[0],
           f"exactly one reason line on stderr: {err(res)!r}")

    # 2) The `models_used` block is absent altogether: the same degradation.
    absent = write(root, "pipeline-absent-claims.yaml", "run_id: 20261026-2ea2eb55\nstatus: ok\n")
    res2, artifact2, text2 = attr(root, home, repo, "--pipeline", str(absent),
                                  name="no-claims-absent.json")
    expect(res2.returncode == 3,
           f"a pipeline without models_used must be DEGRADED (exit 3): {text2!r}")
    expect(artifact2["verdict"] == "DEGRADED", f"verdict: {artifact2.get('verdict')!r}")
    expect(artifact2["claims"]["compared"] == 0, f"no claim was read: {artifact2['claims']!r}")

    # 3) The invariant itself (the quoted defect line): an empty comparison is never PASS.
    expect(ma.verdict_of({}) == "DEGRADED",
           f"verdict_of({{}}) must be DEGRADED, got {ma.verdict_of({})!r}")
    expect(ma.verdict_of({"a": "match"}) == "PASS",
           "a confirmed claim is still a PASS")

    # 4) Contrast: with NO --pipeline there is no claim side at all, so the run is a wire report
    # (documented exit 0) — the degradation above is about equal set, not about reading a wire.
    res3, artifact3, text3 = attr(root, home, repo, name="report-only.json")
    expect(res3.returncode == 0, f"a claim-free wire report still exits 0: {text3!r}")
    expect(artifact3["comparison"] == {}, f"nothing to compare: {artifact3['comparison']!r}")
    expect("no models_used claim to cross-check" in text3,
           f"the report must say why nothing was compared: {text3!r}")


def case_12_unknown_role_is_a_run_error(root: pathlib.Path) -> None:
    """A `models_used` role the factory does not have is exit 1, never the DEGRADED exit 3.

    Regression (run 20261026-a65b9a6e): the main agent invented the role `orchestrator` in
    `models_used` and performed the reviewer's work itself. `model_attribution.py` accepted ANY
    key, found no wire for it and reported DEGRADED ("no wire for this role") — a contract breach
    filed as a technical detail. The registry is `model_matrix.ROLES`, imported so it cannot drift.
    """
    home = root / "home12"
    repo = root / "repo12"
    repo.mkdir(parents=True, exist_ok=True)
    spec = write(root, "pipeline-bogus-role.yaml",
                 pipeline(("main", "deepseek-flash"), ("reviewer", "kimi-code/k3.1-pro"),
                          ("orchestrator", "kimi-k3")))

    # The helper itself (the contract, not only the CLI).
    expect(ma.unknown_roles({"main": "x", "reviewer": "y"}) == [],
           "the roles of the factory and `main` are known keys")
    expect(ma.unknown_roles({"orchestrator": "kimi-k3"}) == ["orchestrator"],
           "an invented role must be reported by name")
    expect(ma.verdict_of({"orchestrator": "unknown_role"}) == "FAIL",
           "an unknown role is a FAIL, never a DEGRADED")
    source = pathlib.Path(ma.__file__).read_text(encoding="utf-8")
    expect(re.search(r"^from\s+model_matrix\s+import\b", source, re.M) is not None,
           "the role registry must be IMPORTED from model_matrix.py, never re-declared")

    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="bogus-role.json")
    expect(res.returncode == 1,
           f"an unknown models_used role must exit 1 (NOT 3 = degraded): {res.returncode} {text!r}")
    expect(artifact["verdict"] == "FAIL", f"the verdict must be FAIL: {artifact.get('verdict')!r}")
    expect(artifact["comparison"]["orchestrator"] == "unknown_role",
           f"the comparison must name the breach: {artifact['comparison']!r}")
    expect(artifact["flags"]["unknown_roles"] == ["orchestrator"],
           f"the flag must list the invented role: {artifact['flags']!r}")
    said = text + err(res)
    expect("orchestrator" in said, f"the report must name the offending role: {said!r}")
    expect("model_matrix.ROLES" in said,
           f"the report must name the registry the role is missing from: {said!r}")
    expect(text.strip().splitlines()[-1].startswith("FAIL - "),
           f"the final line must not read DEGRADED: {text!r}")
    expect("not a role of the factory" in text,
           f"the per-role line must say it plainly: {text!r}")


def case_13_mixed_model_service_is_a_mismatch(root: pathlib.Path) -> None:
    """Regression (self-review 20261031-d2f6fea6, critical 9): a role served by BOTH the claimed
    model and a fallback one must FAIL, not match.

    The gate is the artifact-backed anti-substitution gate, and its question is "did this role run
    exactly the model the pipeline claims?", not "did it ever run it". A membership test accepted a
    mixed service (`deepseek-flash` + a substituted `kimi-k3`), so precisely the substitution the
    gate exists to catch passed. The served canonical set must EQUAL the singleton claimed set.
    """
    # The helper itself: the contract, independent of the CLI and the fixtures.
    comparison, lines, _flags = ma.compare_claims(
        {"analyzer": "deepseek-flash"},
        {"analyzer": {"models_served": {"deepseek-flash": 2, "kimi-k3": 1}}})
    expect(comparison == {"analyzer": "mismatch"},
           f"a mixed-model service must be a mismatch, got {comparison!r}: {lines!r}")
    expect(ma.verdict_of(comparison) == "FAIL",
           "a mixed-model service must FAIL the run, never pass the gate")
    # The wire name is normalised before the comparison: `k3` is the same model as `kimi-k3`, so a
    # claim of `kimi-k3` served under both spellings is still ONE model and still a match.
    same = ma.compare_claims({"coder": "kimi-k3"},
                             {"coder": {"models_served": {"kimi-k3": 1, "k3": 2}}})
    expect(same[0] == {"coder": "match"},
           f"two spellings of ONE model must match ({same[1]!r}), the set is canonical")

    # The CLI: a role the wire served with the claimed model AND a fallback model -> exit 1.
    home = root / "home13"
    repo = root / "repo13"
    repo.mkdir(parents=True, exist_ok=True)
    build_session(home, repo, "session_13131313-1313-4313-8313-131313131313", {
        "main": [llm("main", "deepseek-flash", at=T0),
                 spawned("agent-0", "factory-analyzer", "deepseek-flash", at=T0)],
        "agent-0": [llm("agent-0", "deepseek-flash", at=T0 + 10),
                    usage("agent-0", "deepseek-flash", at=T0 + 11),
                    llm("agent-0", "k3", "kimi-k3", at=T0 + 20),
                    usage("agent-0", "kimi-k3", at=T0 + 21)],
    }, profiles={"agent-0": "factory-analyzer"})
    spec = write(root, "pipeline-mixed.yaml",
                 pipeline(("main", "deepseek-flash"), ("analyzer", "deepseek-flash")))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="mixed.json")
    expect(res.returncode == 1,
           f"a role served by the claimed model AND a fallback must exit 1: "
           f"{res.returncode} {text!r} {err(res)!r}")
    expect(artifact["roles"]["analyzer"]["models_served"]
           == {"deepseek-flash": 1, "kimi-k3": 1},
           f"the wire evidence must be counted per model: {artifact['roles']['analyzer']!r}")
    expect(artifact["comparison"] == {"main": "match", "analyzer": "mismatch"},
           f"only the mixed role mismatches: {artifact['comparison']!r}")
    expect(artifact["verdict"] == "FAIL", f"the verdict must be FAIL: {artifact['verdict']!r}")
    expect("analyzer: mismatch (claimed=deepseek-flash wire=[deepseek-flash:1,kimi-k3:1])" in text,
           f"the mismatch line must show BOTH served models: {text!r}")
    expect(text.strip().splitlines()[-1].startswith("FAIL - "),
           f"the final line must not read PASS: {text!r}")


def case_14_strict_attribution(root: pathlib.Path) -> None:
    """Strict attribution (violation N-3, proposals P-1+P-3): a REQUIRED role's claim must be wired.

    The defect this pins: a role could be listed in `required_roles`, claimed in `models_used`, and
    leave NO session-wire trace — and the run still exited 3 (DEGRADED), i.e. "no wire for this
    role" was accepted as a technical detail for a role the run itself declared mandatory. Under
    strict attribution that is a run FAILURE (exit 1) naming the role.
    """
    home, repo = standard_session(root / "strict")
    # The wire has analyzer + coder. `reviewer` is required and claimed but never spawned.
    unbacked = contract_pipeline((("analyzer", "deepseek-flash"), ("reviewer", "kimi-k3")),
                                 task_type="implement", required_roles=("analyzer", "reviewer"))
    spec = write(root, "pipeline-strict.yaml", unbacked)

    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="strict.json")
    expect(res.returncode == 1,
           f"a required role with no wire trace must FAIL (exit 1), not degrade: "
           f"{res.returncode} {text!r} {err(res)!r}")
    expect(artifact["strict"] is True, f"strict must be ON for implement: {artifact['strict']!r}")
    expect("implement" in (artifact["strict_reason"] or ""),
           f"the artifact must say why: {artifact.get('strict_reason')!r}")
    expect(artifact["task_type"] == "implement" and artifact["required_roles"] == ["analyzer",
                                                                                  "reviewer"],
           f"the contract must be recorded: {artifact.get('task_type')!r} "
           f"{artifact.get('required_roles')!r}")
    expect(artifact["comparison"] == {"analyzer": "match", "reviewer": "unbacked"},
           f"the required unbacked role must be `unbacked`: {artifact['comparison']!r}")
    expect(artifact["verdict"] == "FAIL" and artifact["attribution_degraded"] is False,
           f"a strict failure is a FAIL, not a degradation: {artifact['verdict']!r} "
           f"{artifact['attribution_degraded']!r}")
    expect(artifact["flags"]["required_unbacked"] == ["reviewer"],
           f"the flag must name the role: {artifact['flags']!r}")
    expect("reviewer: unbacked (claimed=kimi-k3, no subagent.spawned trace)" in text,
           f"the per-role line must name the role and the missing trace: {text!r}")
    expect(text.strip().splitlines()[-1].startswith("FAIL - ")
           and "REQUIRED role" in text.strip().splitlines()[-1]
           and "reviewer" in text.strip().splitlines()[-1],
           f"the summary must name the required role: {text!r}")

    # refactor is strict by default too.
    refactor = write(root, "pipeline-refactor.yaml",
                     unbacked.replace("task_type: implement", "task_type: refactor"))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(refactor), name="refactor.json")
    expect(res.returncode == 1 and artifact["comparison"]["reviewer"] == "unbacked",
           f"refactor must be strict by default: {res.returncode} {artifact['comparison']!r}")

    # review / security_audit are NOT strict by default: the same fixture stays DEGRADED (exit 3).
    for kind in ("review", "security_audit"):
        relaxed = write(root, f"pipeline-{kind}.yaml",
                        unbacked.replace("task_type: implement", f"task_type: {kind}"))
        res, artifact, text = attr(root, home, repo, "--pipeline", str(relaxed),
                                   name=f"{kind}.json")
        expect(res.returncode == 3,
               f"task_type {kind} is not strict by default (DEGRADED, exit 3): {res.returncode} "
               f"{text!r}")
        expect(artifact["strict"] is False and artifact["verdict"] == "DEGRADED",
               f"the artifact must record the non-strict decision: {artifact['strict']!r} "
               f"{artifact['verdict']!r}")
        expect(artifact["comparison"]["reviewer"] == "degraded",
               f"without strict the status stays `degraded`: {artifact['comparison']!r}")

        # …and `--strict` FORCES it: the same run is a FAIL.
        res, artifact, text = attr(root, home, repo, "--pipeline", str(relaxed), "--strict",
                                   name=f"{kind}-strict.json")
        expect(res.returncode == 1,
               f"--strict must force strict attribution for {kind}: {res.returncode} {text!r}")
        expect(artifact["strict"] is True and "--strict" in (artifact["strict_reason"] or ""),
               f"the artifact must record the forced decision: {artifact.get('strict_reason')!r}")
        expect(artifact["comparison"]["reviewer"] == "unbacked",
               f"a forced strict run fails the required role: {artifact['comparison']!r}")

    # A required role WITH a wire trace passes, and an unused/conditional role never causes a
    # false failure: only a CLAIMED required role is checked.
    good = contract_pipeline((("analyzer", "deepseek-flash"), ("gui_expert", "unused")),
                             task_type="implement",
                             required_roles=("analyzer", "gui_expert", "security_auditor"))
    spec = write(root, "pipeline-strict-good.yaml", good)
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="strict-good.json")
    expect(res.returncode == 0,
           f"a wired required role + an unused conditional role must PASS: {res.returncode} "
           f"{text!r} {err(res)!r}")
    expect(artifact["comparison"] == {"analyzer": "match", "gui_expert": "match"},
           f"no false failure for a conditional role: {artifact['comparison']!r}")
    expect(artifact["flags"]["required_unbacked"] == [],
           f"nothing is unbacked here: {artifact['flags']!r}")

    # An unknown or empty task_type is an INPUT error naming the four types (never a silent
    # switch that disables the gate).
    for label, value in (("unknown", "task_type: deploy"), ("empty", "task_type:")):
        broken = write(root, f"pipeline-{label}-task-type.yaml",
                       unbacked.replace("task_type: implement", value))
        res, _artifact, _text = attr(root, home, repo, "--pipeline", str(broken),
                                     name=f"{label}-task-type.json")
        expect(res.returncode == 2,
               f"a {label} task_type must be an input error (exit 2): {res.returncode}")
        expect(b"Traceback" not in res.stderr, f"no traceback: {err(res)!r}")
        expect("task_type" in err(res) and "implement" in err(res),
               f"the error must name the key and the allowed values: {err(res)!r}")

    # A checkpoint without `task_type` keeps the historical behaviour (documented, not silent).
    legacy = write(root, "pipeline-legacy.yaml",
                   contract_pipeline((("reviewer", "kimi-k3"),), required_roles=("reviewer",)))
    res, artifact, text = attr(root, home, repo, "--pipeline", str(legacy), name="legacy.json")
    expect(res.returncode == 3,
           f"a checkpoint without task_type stays non-strict (DEGRADED): {res.returncode} {text!r}")
    expect(artifact["strict"] is False and "no task_type" in (artifact["strict_reason"] or ""),
           f"the artifact must say why strict is off: {artifact.get('strict_reason')!r}")


def case_15_contract_reader(root: pathlib.Path) -> None:
    """The checkpoint reader behind strict attribution: task_type, required_roles, one source."""
    plain = write(root, "contract-plain.yaml", pipeline(("reviewer", "kimi-k3")))
    contract = ma.read_pipeline_contract(plain)
    expect(contract["task_type"] == "" and contract["task_type_declared"] is False,
           f"an absent task_type is not declared: {contract!r}")
    expect(contract["required_roles"] == [], f"absent required_roles is an empty list: {contract!r}")
    expect(contract["claims"] == {"reviewer": "kimi-k3"},
           f"the claims still come from the same reader: {contract['claims']!r}")

    block = write(root, "contract-block.yaml", contract_pipeline(
        (("analyzer", "deepseek-flash"),), task_type="refactor",
        required_roles=("analyzer", "gui_expert")))
    contract = ma.read_pipeline_contract(block)
    expect(contract["task_type"] == "refactor" and contract["task_type_declared"] is True,
           f"the task_type must be read: {contract!r}")
    expect(contract["required_roles"] == ["analyzer", "gui_expert"],
           f"the block list must be read: {contract['required_roles']!r}")

    flow = write(root, "contract-flow.yaml",
                 "task_type: implement\nrequired_roles: [analyzer, gui_expert]\n"
                 "run_id: 20261025-4e17a349\nmodels_used:\n  analyzer: deepseek-flash\n")
    contract = ma.read_pipeline_contract(flow)
    expect(contract["required_roles"] == ["analyzer", "gui_expert"],
           f"a bracketed flow list must be read too: {contract['required_roles']!r}")

    # strict_decision: default ON for implement/refactor, OFF for the other two, forced by --strict.
    for kind, expected in (("implement", True), ("refactor", True), ("review", False),
                          ("security_audit", False)):
        strict, reason = ma.strict_decision(kind, True)
        expect(strict is expected and reason,
               f"task_type {kind} strict={expected}, got {strict} ({reason!r})")
    expect(ma.strict_decision("review", True, forced=True)[0] is True,
           "--strict forces strict attribution")
    expect(ma.strict_decision("", False)[0] is False,
           "an undeclared task_type stays non-strict")
    try:
        ma.strict_decision("deploy", True)
    except ma.AttributionError as exc:
        expect("implement" in str(exc), f"the error must list the task types: {exc}")
    else:
        raise AssertionError("an unknown task_type must raise AttributionError (exit 2)")


def case_16_malformed_wire_records_never_pass(root: pathlib.Path) -> None:
    """Regression (review 20261104-b5b601f6, critical 29; reworked for review R1): a skipped
    record is never a free PASS.

    Only ONE skip is explained: a genuinely TRUNCATED, not newline-terminated final JSON record of
    a wire being appended to right now. An unparsable record anywhere else, an unparsable final
    line that is newline-terminated or that does not even start like a JSON object, or a valid JSON
    value that is not an event object, is a malformed/foreign record whose content could hide
    another served model or a substitution — so any such record must make the attribution DEGRADED
    (exit 3), never PASS.
    """
    good = json.dumps(llm("main", "deepseek-flash", at=T0))
    sid = "session_16161616-1616-4161-8161-161616161616"

    def session_with(main_wire_body: str, name: str) -> tuple[pathlib.Path, pathlib.Path]:
        home = root / f"home16-{name}"
        repo = root / f"repo16-{name}"
        repo.mkdir(parents=True, exist_ok=True)
        session_dir = build_session(home, repo, sid, {"main": []})
        write(session_dir / "agents" / "main", "wire.jsonl", main_wire_body)
        return home, repo

    spec = write(root, "pipeline-16.yaml", pipeline(("main", "deepseek-flash")))

    # 1) The tolerated case: a half-written FINAL line — PASS, counted as skipped_lines.
    home, repo = session_with(good + '\n{"type": "llm.request", "model": "ki', "partial")
    analysis = ma.analyse_session(home / "sessions" / f"wd_fixture_{sid}" / sid)
    expect(analysis["skipped_lines"] == 1 and analysis["malformed_lines"] == 0,
           f"a partial final line is the tolerated skip: {analysis!r}")
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="16-partial.json")
    expect(res.returncode == 0,
           f"a partial final line must still PASS: {res.returncode} {text!r} {err(res)!r}")
    expect(artifact["session"]["malformed_lines"] == 0,
           f"no malformed record here: {artifact['session']!r}")

    # 2) A broken record MID-wire: DEGRADED, never PASS.
    home, repo = session_with(good + '\n{"type": "llm.request", "model":\n' + good + "\n",
                              "middle")
    analysis = ma.analyse_session(home / "sessions" / f"wd_fixture_{sid}" / sid)
    expect(analysis["malformed_lines"] == 1 and analysis["skipped_lines"] == 0,
           f"a broken mid-wire record is unexplained: {analysis!r}")
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="16-middle.json")
    expect(res.returncode == 3,
           f"a malformed mid-wire record must be DEGRADED (exit 3), never PASS: "
           f"{res.returncode} {text!r}")
    expect(artifact["verdict"] == "DEGRADED" and artifact["attribution_degraded"] is True,
           f"the artifact must admit it: {artifact.get('verdict')!r}")
    expect(artifact["session"]["malformed_lines"] == 1,
           f"the artifact must count it: {artifact['session']!r}")
    expect("malformed" in (artifact.get("degraded_reason") or ""),
           f"the reason must name the malformed record: {artifact.get('degraded_reason')!r}")
    expect(text.strip().splitlines()[-1].startswith("DEGRADED - "),
           f"the final line must not read PASS: {text!r}")

    # 3) Foreign content — valid JSON, not an event object — is malformed even as the LAST line.
    home, repo = session_with(good + '\n["not", "an", "event"]\n', "foreign")
    res, artifact, text = attr(root, home, repo, "--pipeline", str(spec), name="16-foreign.json")
    expect(res.returncode == 3,
           f"a foreign JSON record must be DEGRADED (exit 3), never PASS: "
           f"{res.returncode} {text!r}")
    expect(artifact["session"]["malformed_lines"] == 1,
           f"foreign content is unexplained even at the tail: {artifact['session']!r}")

    # 4) REGRESSION (review R1, critical 29): an unparsable FINAL line is tolerated ONLY when it is
    #    a genuinely truncated, not newline-terminated record. Arbitrary final garbage — with or
    #    without a trailing newline — is unparsed evidence and must be DEGRADED, never PASS.
    for label, tail in (("garbage-terminated", "\n<not json at all>\n"),
                        ("garbage-unterminated", "\n<not json at all>"),
                        ("closed-object-garbage", '\n{"type": "llm.request"} trailing'),
                        ("truncated-but-terminated", '\n{"type": "llm.request", "model": "ki\n')):
        home, repo = session_with(good + tail, label)
        analysis = ma.analyse_session(home / "sessions" / f"wd_fixture_{sid}" / sid)
        expect(analysis["malformed_lines"] == 1 and analysis["skipped_lines"] == 0,
               f"an unparsable final line ({label}) is malformed, never a tolerated partial: "
               f"{analysis!r}")
        res, artifact, text = attr(root, home, repo, "--pipeline", str(spec),
                                   name=f"16-{label}.json")
        expect(res.returncode == 3,
               f"an unparsable final line ({label}) must be DEGRADED (exit 3), never PASS: "
               f"{res.returncode} {text!r}")
        expect(artifact["verdict"] == "DEGRADED" and artifact["attribution_degraded"] is True,
               f"the artifact must admit it ({label}): {artifact.get('verdict')!r}")
        expect(text.strip().splitlines()[-1].startswith("DEGRADED - "),
               f"the final line must not read PASS ({label}): {text!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        case_1_roles_and_counts(root)
        case_2_mismatch(root)
        case_3_unused_role_with_events(root)
        case_4_degraded(root)
        case_5_nested_model_keys_ignored(root)
        case_6_error_events(root)
        case_7_auto_resolution(root)
        case_8_vaccination(root)
        case_9_helpers(root)
        case_10_cli(root)
        case_11_no_claims_is_degraded(root)
        case_12_unknown_role_is_a_run_error(root)
        case_13_mixed_model_service_is_a_mismatch(root)
        case_14_strict_attribution(root)
        case_15_contract_reader(root)
        case_16_malformed_wire_records_never_pass(root)

    print("PASS - model_attribution.py confirms every models_used claim against the CLI's own "
          "session wire: roles come from state.json (or subagent.spawned), the wire name is "
          "normalised to its alias, only top-level typed events are counted, a disproven claim is "
          "a mismatch (exit 1), a missing session is DEGRADED with an artifact (exit 3), a role "
          "the factory does not have is a run error (exit 1), a role served by the claimed model AND "
          "a fallback model is a mismatch (exit 1, the served set must EQUAL the claimed one), and "
          "the self-reported view that would look green without the cross-check is proven red.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
