#!/usr/bin/env python3
"""
Deterministic contract test for `roblox_mcp.py` (zero LLM tokens, no network, no Studio start).

The module pins the helper the factory's conditional Roblox path depends on. Every fixture lives in
a tempfile directory, every subprocess runs with an EXPLICIT environment, and every state root the
helper resolves by default is redirected into that temp directory — the operator's real global
`mcp.json` is never read for a decision and never written:

  1. `decide` — the BOTH-conditions matrix: Roblox repository markers AND Roblox task scope are
     required, so repository identity alone, task text alone, a `models.roblox_expert` model pin
     alone and an empty task text all keep the role OFF; a standalone "Studio" (the Roblox IDE) is a
     Roblox subject when an action is bound to it ("Add a coin pickup script and playtest it in
     Studio"), while a `studio` naming another product or place (Visual Studio, a recording studio, a
     studio apartment) is not; an action bound to documentation/media ("update the Roblox README",
     "update the Studio changelog") is not Roblox work, and that binding is per CLAUSE, so a
     documentation clause never discards the real game action of the next clause and adjacent
     wording can never smuggle a documentation action past its own doc object, while an action
     counts only inside the clause that ALSO names the Roblox subject (a subject in one clause and a
     generic verb in another never combine); `--repo` that is not
     a directory and a missing `--task-file` are usage errors (exit 2). The non-Roblox case is pinned
     on the FACTORY repository itself, this run's own task file included.
  2. `merge-config` DEFAULT target — the USER-SCOPE GLOBAL CLI config: `KIMI_CODE_HOME` is honoured
     (temp dir only), the home directory is the fallback, an undeterminable or nonexistent data root
     is exit 2 and writes nothing.
  3. `merge-config --target` — the explicit override: symlink-resolved (a directory link is followed
     to its real path), a missing parent directory is exit 2, and the RESOLVED path is echoed.
  4. the ONE write contract of both targets — idempotent (a second run is byte-identical), unrelated
     servers and settings preserved byte-for-byte, a conflicting `Roblox_Studio` entry reported with
     exit 3 while the target keeps every byte and no stored value is echoed, `--dry-run` writes
     nothing.
  5. `validate-config` — a missing file is exit 2, malformed JSON is exit 1, an absent managed entry
     is valid, every managed-entry invariant is enforced (exactly `command`/`args`, the `/c` switch,
     the absolute `…/Roblox/mcp.bat` launcher), and no diagnostic echoes a value the entry supplies.
  6. the scenario runner against an INJECTED fake stdio Studio server (`--executable`/`--arg`) — a
     structured PASS with its captured console output (`console.log` + `verdict.json` + the console
     sha256), a run that logged an error is FAIL (exit 1), a PRESENT non-boolean `isError` (a string,
     a number, null, a container) is refused before its `content` can read as success, a screenshot is
     never the verdict, a
     zero-step scenario and every timeout outside (0, 3600] are exit 2, a missing `--executable` and
     an empty `--arg` are exit 2. The bounded stop is pinned on the shape a real launcher has: a
     launcher that EXITS while the child it started survives must leave nothing running, on both the
     scenario and the handshake cleanup path — and a host that REFUSES the Windows job assignment
     must therefore refuse the session (a FAIL verdict naming the cause, a missing handshake
     capability) and leave no child behind instead of falling back to cleanup that dies with its
     leader. The console capture is taken BEFORE that stop, so the noise a peer's own death prints
     never flips a perfect scenario to FAIL while an error logged during the run still does.
  7. `scenario verify` — exit 0 ONLY for an honest PASS: a tampered verdict, a sha-mismatched
     console, a FAIL record and a verdict claiming the screenshot as its verdict are all refused.
  8. `probe` — fail-soft (exit 0) on missing capabilities and on an undeterminable data root, and the
     opt-in `--check-mcp-start` handshake driven through library seams (`studio_batch_path`,
     `_handshake`) so it can never start a real Studio session.
  9. the CLI contract — `--help` exit 0 for every subcommand, usage errors exit 2 without a
     traceback, and non-ASCII output surviving a legacy console code page.
 10. the SKILL-GUIDANCE regression — the shipped `game-development` skill must scope the
     `LocalScript` prohibition to the containers that really do not run one and must keep naming
     every supported client location (`StarterPlayerScripts`, `StarterCharacterScripts`,
     `StarterGui`/`PlayerGui`, `StarterPack`/`Backpack`, and the script parented directly at
     runtime under `PlayerScripts`/`PlayerGui`) with no exhaustive "one of those three" list, so the
     text can never again tell an agent that a perfectly valid client script will not run, nor
     delete the valid ones while "fixing" that sentence.

Exit code 0 = all assertions pass, 1 = a command did not behave as expected.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

SCRIPTS = pathlib.Path(__file__).resolve().parent
TOOL = SCRIPTS / "roblox_mcp.py"
# `.agents/skills/code-factory/scripts` -> the repository root (the non-Roblox fixture of case 1).
REPO_ROOT = SCRIPTS.parents[3]
# The shipped guidance the Roblox path hands to a specialist (DATA only: this test never runs it).
GAME_SKILL = REPO_ROOT / "skill-base" / "skills" / "game-development" / "SKILL.md"
# The containers a `LocalScript` really runs in — the skill must never stop naming them.
CLIENT_CONTAINERS = ("StarterPlayerScripts", "StarterCharacterScripts", "StarterGui", "PlayerGui")
# Containers where a `LocalScript` really does not run — the scoped prohibition names these.
UNSUPPORTED_CONTAINERS = ("ServerScriptService", "ServerStorage", "Workspace")
# The supported client LOCATIONS beyond the three `Starter*` containers: `StarterPack` is cloned into
# the player's `Backpack`, and a client script also runs parented directly at runtime under
# `PlayerScripts`, `PlayerGui`, the `Backpack` or the character. Guidance that listed only three
# containers told an agent to move a valid tool or runtime script where it does not belong.
CLIENT_DESTINATIONS = ("StarterPack", "Backpack", "PlayerScripts", "PlayerGui")
# The false EXHAUSTIVE claim this regression exists for: "one of those three" reads as a closed list,
# so every other supported location (a `StarterPack` tool, a runtime-parented script) looks invalid.
EXHAUSTIVE_CLAIMS = ("one of those three", "one of these three", "one of the three",
                     "one of those 3", "only three", "the only three")
# The false blanket this regression exists for: it calls EVERY LocalScript outside the character
# dead, contradicting the StarterPlayerScripts/StarterGui rows of the very same table.
BLANKET_CLAIMS = ("outside the player's character", "outside the character")

sys.path.insert(0, str(SCRIPTS))
import roblox_mcp as rm  # noqa: E402  (the importable API under test)

COUNTER = {"checks": 0}

APPLICABLE_TEXT = "Add a coin pickup to the Roblox game and playtest it."
# The adversarial wording of business scenario 1: NO "Roblox" keyword at all — standalone "Studio"
# (the Roblox IDE) is the only subject, and it must be recognized when an action is bound to it.
STANDALONE_STUDIO_TEXT = "Add a coin pickup script and playtest it in Studio"
# Repository identity alone: a Roblox source tree with a task about ordinary Python work.
REPO_ONLY_TEXT = "Refactor the logging module used by the report generator and update its docstring."
# An action on DOCUMENTATION: naming the engine does not make the edit Roblox work.
DOC_BOUND_TEXT = "Update the Roblox README documentation to describe the coin system."
DOC_BOUND_TEXTS = (
    DOC_BOUND_TEXT,
    "Edit the Rojo markdown guide and regenerate the docs site.",
    "Update the Roblox changelog to describe the new pickup.",
    # …and a bare "Studio" bound to a documentation action is discarded the same way.
    "Update the Studio changelog to describe the new pickup.",
)
# 1.13 — action/object binding is CLAUSE-level: an action is documentation work only when the CLAUSE
# it governs (see CLAUSE_BOUNDARY in the module) names a documentation/media object. These are the two
# wordings a ±3-word proximity window got WRONG, kept as regressions in their corrected shape:
#   OVER-FIRE (was: applicable) — "Update the Roblox changelog with the coin system changes.": the
#     doc object `changelog` governs the whole clause, so the trailing "changes" cannot escape it and
#     a pure documentation edit no longer activates the Roblox role.
#   UNDER-FIRE (was: not applicable) — "Fix the Roblox README typo and playtest the coin pickup in
#     Studio.": only the documentation clause is discarded, so the real game action of the next
#     clause decides — no filler words are needed any more.
CLAUSE_DOC_ONLY = "Update the Roblox changelog with the coin system changes."
CLAUSE_MIXED_UNDER_FIRE = "Fix the Roblox README typo and playtest the coin pickup in Studio."
# Cross-clause CONTROLS: the documentation clause and the game clause are judged separately, in
# either ORDER and across every boundary kind (conjunction, comma + adverb, plain conjunction).
CLAUSE_CROSS_CONTROLS = (
    "Update the Roblox README typo first and then playtest the coin pickup in Studio.",
    "Update the Roblox changelog, then playtest the coin pickup in Studio.",
    "Playtest the coin pickup in Studio and update the Roblox README.",
    "Fix the coin pickup in Studio; update the Roblox changelog afterwards.",
)
# …while a documentation object in the action's OWN clause still discards that action.
CLAUSE_SAME_CLAUSE_DOC = "Review the Roblox README examples in Studio."
# The subject and the action must sit in the SAME clause (review-1 finding 3): a Roblox subject in a
# documentation clause plus a generic verb in an unrelated one used to combine GLOBALLY and activate
# the role, although the verb drives somebody else's task.
CLAUSE_SPLIT_SUBJECT_ACTION = "Update the Roblox README, then fix the Python CI."
# `studio` in a Roblox repository but naming ANOTHER product or place: never the Roblox IDE.
OTHER_STUDIO_TEXTS = (
    "Add a Visual Studio extension for the build log.",
    "Fix the build in Visual Studio Code.",
    "Rent a studio apartment and playtest the layout there.",
    "Design a logo in the recording studio.",
    "Rework the dance studio website.",
)
# The metadata key pins the specialist's MODEL; it says nothing about what the task operates.
MODEL_PIN_TASK = """\
title: refactor the logging module
description: |
  Replace the hand-rolled logging helper with the project logger and update its docstring.
models:
  roblox_expert: deepseek-flash
mode: auto
"""
EXCLUDED_TEXT = "Fix the parser test. Do not touch Roblox here: Roblox work stays out of scope."
SECRET = "s3cr3t-token-DO-NOT-ECHO"

STUDIO_TOOLS = ("execute_luau", "start_stop_play", "get_console_output")
# The captured console output of an honest play-test (two Luau print lines, no error).
GOOD_CONSOLE = ("Coin collected: 1", "play-test finished")
# The console line of a run that DID log an error: never a PASS, whatever else the run produced.
ERROR_CONSOLE = ("Coin collected: 1",
                 "ServerScriptService.Coin:3: attempt to index nil (Infinite yield possible)")

# The noise a PEER'S OWN DEATH prints (verbatim shape of the live acceptance re-run): a tear-down
# message that carries the word "error", so a capture taken AFTER the stop turns a perfect scenario
# into a false FAIL.
TEARDOWN_NOISE = ("WARN rbx-studio-proxy: WebSocket error from proxy (127.0.0.1:34873): "
                  "Connection reset without closing handshake")

# The fake Studio stdio server: a well-formed MCP peer over stdin/stdout, answering `tools/call`
# with the cached console lines as `text` content blocks. It is a REAL child process, so the
# bounded session, the console capture and the process-tree termination are exercised for real.
# Two optional stderr lines pin the two phases of a session apart: `LIVE_NOISE` is logged while the
# scenario RUNS (real console evidence, must FAIL the verdict), `DEATH_NOISE` only once stdin closes
# — i.e. during the teardown (the peer's death rattle, never part of the verdict).
FAKE_STUDIO_SERVER = '''\
import json, sys

TOOLS = %s
CONSOLE = %s
LIVE_NOISE = %s
DEATH_NOISE = %s
# The `isError` MEMBER the result carries: a Python fragment (see `studio_server`), `None` when the
# member is ABSENT from the result — so a case can pin every present non-boolean shape.
IS_ERROR_MEMBER = %s


def answer(request_id, result):
    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)


if LIVE_NOISE:
    print(LIVE_NOISE, file=sys.stderr, flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    if message.get("id") is None:
        continue
    method = message.get("method")
    if method == "initialize":
        answer(message["id"], {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                               "serverInfo": {"name": %s, "version": "0"}})
    elif method == "tools/list":
        answer(message["id"], {"tools": [{"name": tool, "inputSchema": {"type": "object"}}
                                        for tool in TOOLS]})
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": text} for text in CONSOLE]}
        if IS_ERROR_MEMBER is not None:
            result.update(IS_ERROR_MEMBER)
        answer(message["id"], result)

# The session is over: stdin closed, so the peer is being torn down and whatever it logs from here
# on is the SHUTDOWN talking, not the scenario.
if DEATH_NOISE:
    print(DEATH_NOISE, file=sys.stderr, flush=True)
'''

# The launcher shape that leaks if cleanup is tied to the DIRECT child's liveness: it starts a
# long-lived child (the "Studio server" it launches), records that child's pid and exits at once, so
# the child OUTLIVES its parent while still holding the session's inherited stdin/stdout.
ORPHANING_LAUNCHER = '''\
import subprocess, sys

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))
'''

# The same orphaning shape, but the launcher LINGERS for `sys.argv[2]` seconds after recording the
# child: a refused-job session must terminate that still-live tree, and a session that instead keeps
# the leader-dependent `taskkill` leaks the child the moment the launcher exits.
HOLDING_LAUNCHER = '''\
import subprocess, sys, time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))
time.sleep(float(sys.argv[2]))
'''

# The cause a `_adopt_tree` double reports when the host REFUSES job assignment. Its wording follows
# the module's own refusal shape, so a case can name the missing guarantee it must see.
REFUSED_JOB_CAUSE = ("the host refused to assign the session child to a job object (forced by the "
                     "test seam)")


def check(cond: bool, msg: str) -> None:
    COUNTER["checks"] += 1
    if not cond:
        raise AssertionError(msg)


def written(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def base_env(**overrides: str) -> dict:
    """The environment of ONE hermetic case: every global-config input is EXPLICIT.

    `KIMI_CODE_HOME`, `USERPROFILE` and `HOME` are removed from the inherited environment, so a case
    that wants a default registration target has to name one — a temp directory. The operator's real
    global `mcp.json` therefore cannot be resolved by any case of this module.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ("KIMI_CODE_HOME", "USERPROFILE", "HOME")}
    env.update(overrides)
    return env


def run(*args: str, env: dict, cwd: str | pathlib.Path | None = None
        ) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                          errors="replace", env=env, cwd=None if cwd is None else str(cwd))


def expect_clean_cli(res: subprocess.CompletedProcess[str], code: int, label: str) -> None:
    check(res.returncode == code, f"{label}: expected exit {code}, got {res.returncode} "
                                  f"(stdout={res.stdout!r} stderr={res.stderr!r})")
    check("Traceback" not in res.stderr, f"{label}: stderr must not carry a traceback: {res.stderr!r}")


@contextlib.contextmanager
def seams(**patches):
    """Temporarily replace module-level seams (`studio_batch_path`, `_handshake`) with doubles."""
    originals = {name: getattr(rm, name) for name in patches}
    for name, value in patches.items():
        setattr(rm, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(rm, name, value)


def make_directory_link(link: pathlib.Path, target: pathlib.Path) -> bool:
    """Create a directory link; `False` when this host cannot.

    A symlink needs a privilege Windows does not grant by default while a directory JUNCTION does not,
    so the symlink-resolution case still runs on a stock Windows box. Both resolve through
    `realpath`, which is exactly what the helper's resolved-path contract relies on.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True, errors="replace")
    return res.returncode == 0 and link.is_dir()


# --------------------------------------------------------------------- fixtures

def roblox_repo(root: pathlib.Path, style: str = "rojo") -> pathlib.Path:
    """A repository carrying Roblox markers in the requested shape (`rojo`, `place`, `luau`)."""
    root.mkdir(parents=True, exist_ok=True)
    if style == "rojo":
        written(root / "default.project.json",
                json.dumps({"name": "coin-game", "tree": {"$className": "DataModel"}},
                           indent=2) + "\n")
    if style == "place":
        written(root / "places" / "coin-game.rbxlx", "<roblox version=\"4\"></roblox>\n")
    if style == "luau":
        written(root / "src" / "main.server.luau",
                'local Players = game:GetService("Players")\n'
                'Players.PlayerAdded:Connect(function(player)\n'
                '    print("joined: " .. player.Name)\n'
                'end)\n')
    return root


def bare_repo(root: pathlib.Path) -> pathlib.Path:
    """A repository with NO Roblox marker — the "text condition alone" half of the matrix."""
    root.mkdir(parents=True, exist_ok=True)
    written(root / "README.md", "# an ordinary project\n")
    written(root / "tool.py", "print('hello')\n")
    return root


def fake_launcher(tmp: pathlib.Path) -> pathlib.Path:
    """A stand-in `%LOCALAPPDATA%\\Roblox\\mcp.bat` so the managed entry never depends on this host."""
    return written(tmp / "host" / "AppData" / "Local" / "Roblox" / "mcp.bat", "@echo off\n")


# The sentinel that keeps `isError` OUT of the fake result entirely (a present member is what the
# module must judge, an absent one is the legal "no tool-level failure reported" shape).
ABSENT_IS_ERROR = "<absent>"


def studio_server(tmp: pathlib.Path, name: str, console: tuple[str, ...] = GOOD_CONSOLE,
                  live_noise: str = "", death_noise: str = "",
                  is_error: object = False) -> list[str]:
    """Write the fake Studio server and return the argv that starts it.

    `live_noise` / `death_noise` are stderr lines logged while the scenario RUNS / while the session
    is being torn down, so a case can tell the two apart. `is_error` is the VALUE of the result's
    `isError` member — any JSON-encodable shape, `ABSENT_IS_ERROR` to leave the member out.
    """
    member = None if is_error is ABSENT_IS_ERROR else repr({"isError": is_error})
    source = FAKE_STUDIO_SERVER % (json.dumps(list(STUDIO_TOOLS)), json.dumps(list(console)),
                                   json.dumps(live_noise), json.dumps(death_noise),
                                   member if member is not None else "None",
                                   json.dumps(f"fake-studio-{name}"))
    return [sys.executable, str(written(tmp / "servers" / f"{name}.py", source))]


def write_scenario(tmp: pathlib.Path, name: str, steps: list[dict],
                   screenshot: str | None = None) -> pathlib.Path:
    document: dict = {"name": name, "steps": steps}
    if screenshot is not None:
        document["screenshot"] = screenshot
    return written(tmp / "scenarios" / f"{name}.json", json.dumps(document, indent=2) + "\n")


ONE_STEP = [{"tool": "execute_luau", "arguments": {"code": "print('Coin collected: 1')"}}]


def inserted_member(name: str, entry: dict, indent: str = "    ", newline: str = "\n") -> str:
    """Independently computed expectation of the text `merge_config` must insert."""
    block = json.dumps({name: entry}, indent=2).replace("\n", newline)
    relative = [line[2:] for line in block.splitlines()[1:-1]]
    return "," + newline + indent + (newline + indent).join(relative)


def data_root(tmp: pathlib.Path, name: str = "data-root") -> pathlib.Path:
    """A hermetic CLI data root (the `KIMI_CODE_HOME` a case points at) — never the real one."""
    root = tmp / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def pid_alive(pid: int) -> bool:
    """Is the process `pid` still running?

    `os.kill(pid, 0)` is NOT a liveness probe on Windows — there it calls TerminateProcess and would
    kill the very process under test — so the Windows branch asks the kernel via
    `GetExitCodeProcess` (`STILL_ACTIVE` = 259).
    """
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenProcess(0x1000, 0, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False                                   # gone, or not ours: either way not running
    try:
        code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def wait_gone(pid: int, timeout: float = 15.0) -> bool:
    """`True` once `pid` is gone (polled, so a stop that is not instantaneous still counts)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return not pid_alive(pid)


def kill_pid(pid: int) -> None:
    """Fixture hygiene only: a leaked probe child must never outlive a failing case."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def refused_job(pid_file: pathlib.Path):
    """A `_adopt_tree` double: the host REFUSES job assignment once the launcher's child exists.

    Waiting for the recorded pid makes the case deterministic — the refusal is delivered while the
    launcher and the child it spawned are both alive, which is the state the fail-closed path has to
    clean up (the real refusal comes from an API call that answers in milliseconds). The double
    reports the cause the module's own refusal carries, so the caller sees the same message shape.
    """
    def adopt(proc) -> tuple[int | None, str]:
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            text = pid_file.read_text(encoding="utf-8").strip() if pid_file.is_file() else ""
            if text.isdigit():
                break
            time.sleep(0.02)
        return None, REFUSED_JOB_CAUSE
    return adopt


def recorded_pid(path: pathlib.Path, timeout: float = 15.0) -> int | None:
    """The pid the launcher fixture recorded, or `None` when the fixture never got that far."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        if text.isdigit():
            return int(text)
        time.sleep(0.05)
    return None


# --------------------------------------------------------------------- 1. decide

def test_decide(tmp: pathlib.Path) -> None:
    repo = roblox_repo(tmp / "decision" / "coin-game")
    bare = bare_repo(tmp / "decision" / "bare")
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "decision-root")))

    # 1.1 POSITIVE: BOTH conditions — Roblox markers AND Roblox task scope.
    decision = rm.decide_applicability(APPLICABLE_TEXT, repo=repo)
    check(decision["applicable"] is True,
          f"a Roblox task in a Roblox repository must be applicable: {decision}")
    check("BOTH conditions hold" in decision["reasons"][0],
          f"the decision must say WHICH conditions decided it: {decision['reasons']}")
    check(decision["evidence"]["repository"]["roblox"] is True,
          f"the repository markers must be recorded as evidence: {decision['evidence']}")
    res = run("decide", "--repo", str(repo), "--text", APPLICABLE_TEXT, env=env)
    expect_clean_cli(res, 0, "decide applicable")
    check(res.stdout.splitlines()[0] == "applicable",
          f"the human output must open with the decision: {res.stdout!r}")
    payload = json.loads(run("decide", "--repo", str(repo), "--text", APPLICABLE_TEXT, "--json",
                             env=env).stdout)
    check(payload["applicable"] is True and payload["reasons"], f"decide --json: {payload}")

    # 1.2 NEGATIVE: repository identity ALONE (a Roblox tree, an ordinary task).
    decision = rm.decide_applicability(REPO_ONLY_TEXT, repo=repo)
    check(decision["applicable"] is False,
          f"repository identity alone must keep the role off: {decision}")
    check(decision["evidence"]["repository"]["roblox"] is True,
          f"the markers must still be recorded as evidence: {decision['evidence']}")
    check(any("names no Roblox subject" in reason for reason in decision["reasons"]),
          f"the reason must name the missing task scope: {decision['reasons']}")
    expect_clean_cli(run("decide", "--repo", str(repo), "--text", REPO_ONLY_TEXT, env=env), 0,
                     "decide repository-only")

    # 1.3 NEGATIVE: task text ALONE (Roblox scope, no Roblox marker in the tree).
    decision = rm.decide_applicability(APPLICABLE_TEXT, repo=bare)
    check(decision["applicable"] is False,
          f"Roblox task scope alone must keep the role off: {decision}")
    check(any("is not a Roblox project" in reason for reason in decision["reasons"]),
          f"the reason must name the missing repository markers: {decision['reasons']}")
    payload = json.loads(run("decide", "--repo", str(bare), "--text", APPLICABLE_TEXT, "--json",
                             env=env).stdout)
    check(payload["applicable"] is False, f"decide --json (text only): {payload}")

    # 1.4 NEGATIVE: the `models.roblox_expert` MODEL PIN alone — metadata is wiring, not scope.
    pin_task = written(tmp / "decision" / "model-pin-task.yaml", MODEL_PIN_TASK)
    payload = json.loads(run("decide", "--repo", str(repo), "--task-file", str(pin_task), "--json",
                             env=env).stdout)
    check(payload["applicable"] is False,
          f"a models.roblox_expert pin alone must not activate the role: {payload}")
    check(rm.decide_applicability(MODEL_PIN_TASK, repo=repo)["applicable"] is False,
          "the model pin must never classify as task scope, whatever the input route")

    # 1.5 NEGATIVE (zero-legitimacy): an EMPTY task text means "no Roblox work is asked for".
    empty = rm.decide_applicability("", repo=repo)
    check(empty["applicable"] is False,
          f"an empty task text is a legitimate 'off', never an error: {empty}")
    res = run("decide", "--repo", str(repo), "--text", "", env=env)
    expect_clean_cli(res, 0, "decide with an empty --text")
    check(res.stdout.splitlines()[0] == "not applicable",
          f"an empty --text must decide 'not applicable': {res.stdout!r}")

    # 1.6 NEGATIVE: an action bound to DOCUMENTATION/media is not Roblox work.
    for text in DOC_BOUND_TEXTS:
        decision = rm.decide_applicability(text, repo=repo)
        check(decision["applicable"] is False,
              f"a documentation-bound action must stay not applicable: {text!r} -> {decision}")
        check(any("documentation/media" in reason for reason in decision["reasons"]),
              f"the reason must name the discarded documentation action: {decision['reasons']}")
    # …while a task that really operates the game stays applicable next to a docs edit.
    mixed = rm.decide_applicability(
        "Update the Roblox README typo first and then playtest the coin pickup in Studio.",
        repo=repo)
    check(mixed["applicable"] is True,
          f"a real Roblox operation must stay applicable in a mixed task: {mixed}")

    # 1.7 the other marker shapes (place file, Roblox-API Luau source) are repository identity too.
    for style in ("place", "luau"):
        shaped = roblox_repo(tmp / "decision" / f"coin-game-{style}", style=style)
        decision = rm.decide_applicability(APPLICABLE_TEXT, repo=shaped)
        check(decision["applicable"] is True,
              f"the {style} marker must make the repository Roblox: {decision}")

    # 1.8 NEGATIVE: an explicit exclusion wins over every Roblox keyword.
    decision = rm.decide_applicability(EXCLUDED_TEXT, repo=repo)
    check(decision["applicable"] is False,
          f"an explicit exclusion must win: {decision}")

    # 1.10 the ADVERSARIAL wording (business scenario 1): standalone "Studio" is the Roblox subject.
    decision = rm.decide_applicability(STANDALONE_STUDIO_TEXT, repo=repo)
    check(decision["applicable"] is True,
          f"a task that names only 'Studio' must still be Roblox work: {decision}")
    check("studio" in decision["evidence"]["scope_terms"],
          f"the standalone Studio subject must be recorded as evidence: {decision['evidence']}")
    payload = json.loads(run("decide", "--repo", str(repo), "--text", STANDALONE_STUDIO_TEXT,
                             "--json", env=env).stdout)
    check(payload["applicable"] is True, f"decide --json must agree: {payload}")
    for wording in ("playtest the coin pickup in Studio",
                    "Open the place in Roblox Studio and playtest it",
                    "play-test it in studio"):
        check(rm.decide_applicability(wording, repo=repo)["applicable"] is True,
              f"an action bound to Studio must be applicable: {wording!r}")
    # …and a Studio-bound DOCUMENTATION action is still discarded (preserved contract).
    check(rm.decide_applicability("Update the Studio changelog", repo=repo)["applicable"] is False,
          "a documentation-bound Studio action must stay not applicable")

    # 1.11 "Studio" is still only ONE condition: without a Roblox marker in the tree it stays off.
    decision = rm.decide_applicability("playtest in Studio", repo=bare)
    check(decision["applicable"] is False,
          f"Studio task text alone must keep the role off: {decision}")
    check(any("is not a Roblox project" in reason for reason in decision["reasons"]),
          f"the reason must name the missing repository markers: {decision['reasons']}")
    payload = json.loads(run("decide", "--repo", str(bare), "--text", "playtest in Studio", "--json",
                             env=env).stdout)
    check(payload["applicable"] is False, f"the CLI must decide the same: {payload}")

    # 1.12 a `studio` naming ANOTHER product or place is not the Roblox IDE — even in a Roblox repo.
    for text in OTHER_STUDIO_TEXTS:
        decision = rm.decide_applicability(text, repo=repo)
        check(decision["applicable"] is False,
              f"a non-Roblox studio must never count as the subject: {text!r} -> {decision}")
        check("studio" not in decision["evidence"]["scope_terms"],
              f"the excluded studio must not be recorded as a subject: {text!r} -> "
              f"{decision['evidence']['scope_terms']}")

    # 1.13 CLAUSE-level action/object binding (the fixed D1): a documentation action no longer
    #      activates the role, a documentation word no longer discards the real game action of a
    #      NEIGHBOURING clause, and both directions stay pinned plus cross-clause controls.
    over = rm.decide_applicability(CLAUSE_DOC_ONLY, repo=repo)
    check(over["applicable"] is False,
          "a documentation action must stay not applicable when its own clause governs the object, "
          f"whatever clause follows it: {CLAUSE_DOC_ONLY!r} -> {over}")
    check(any("documentation/media" in reason for reason in over["reasons"]),
          f"the discarded documentation action must be explained: {over['reasons']}")
    under = rm.decide_applicability(CLAUSE_MIXED_UNDER_FIRE, repo=repo)
    check(under["applicable"] is True,
          "a real game action in its own clause must be applicable next to a documentation clause: "
          f"{CLAUSE_MIXED_UNDER_FIRE!r} -> {under}")
    check("playtest" in under["evidence"]["scope_terms"],
          f"the surviving game action must be recorded as evidence: {under['evidence']}")
    # …judged separately whichever ORDER the clauses come in and whichever boundary separates them.
    for text in CLAUSE_CROSS_CONTROLS:
        decision = rm.decide_applicability(text, repo=repo)
        check(decision["applicable"] is True,
              f"a docs clause and a game clause must be judged separately: {text!r} -> {decision}")
    same_clause = rm.decide_applicability(CLAUSE_SAME_CLAUSE_DOC, repo=repo)
    check(same_clause["applicable"] is False,
          "a documentation object inside the action's OWN clause must still discard that action: "
          f"{CLAUSE_SAME_CLAUSE_DOC!r} -> {same_clause}")
    # …and the two must meet in one clause: a Roblox subject in one clause plus a generic verb in
    # another are two statements, so no action is bound to the subject (review-1 finding 3).
    split = rm.decide_applicability(CLAUSE_SPLIT_SUBJECT_ACTION, repo=repo)
    check(split["applicable"] is False,
          "a Roblox subject and an action in DIFFERENT clauses must never combine globally: "
          f"{CLAUSE_SPLIT_SUBJECT_ACTION!r} -> {split}")
    check(any("binds no action" in reason for reason in split["reasons"]),
          f"the unbound subject must be explained: {split['reasons']}")

    # 1.9 INPUT BOUNDARIES (exit 2): --repo that is not a directory, a missing --task-file, and
    #     decide with neither input. Nothing is decided against a tree that does not exist.
    not_a_file = written(tmp / "decision" / "not-a-directory.txt", "x\n")
    for label, repo_arg in (("missing", str(tmp / "decision" / "no-such-repo")),
                            ("a file", str(not_a_file))):
        res = run("decide", "--repo", repo_arg, "--text", APPLICABLE_TEXT, env=env)
        expect_clean_cli(res, 2, f"decide --repo {label}")
        check("not an existing directory" in res.stderr,
              f"--repo {label} must be a usage error naming the boundary: {res.stderr!r}")
    res = run("decide", "--repo", str(repo), "--task-file", str(tmp / "decision" / "nope.yaml"),
              env=env)
    expect_clean_cli(res, 2, "decide with a missing --task-file")
    check("not an existing file" in res.stderr,
          f"a missing task file must be loud: {res.stderr!r}")
    res = run("decide", "--repo", str(repo), env=env)
    expect_clean_cli(res, 2, "decide without --text/--task-file")
    check("--text or --task-file" in res.stderr,
          f"decide without an input must be a usage error: {res.stderr!r}")


def test_non_roblox_repository(tmp: pathlib.Path) -> None:
    """The factory repository itself: no Roblox marker, so the role never activates here.

    This is the non-Roblox business scenario pinned as a regression: the repository that runs the
    factory is not a game project, so even Roblox task scope must decide `not_applicable` — and the
    run's OWN task file (`.code-factory/state/task.yaml`, per-run state) is pinned too whenever it
    exists, because the run that adds the role parses exactly that document.
    """
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "factory-root")))
    signals = rm.roblox_repository_signals(REPO_ROOT)
    check(signals["roblox"] is False,
          f"the factory repository must carry no Roblox marker: {signals['details']}")

    decision = rm.decide_applicability(APPLICABLE_TEXT, repo=REPO_ROOT)
    check(decision["applicable"] is False,
          f"Roblox task scope in the factory repository must stay not applicable: {decision}")
    check(any("is not a Roblox project" in reason for reason in decision["reasons"]),
          f"the decision must name the absent repository markers: {decision['reasons']}")

    res = run("decide", "--repo", str(REPO_ROOT), "--text", APPLICABLE_TEXT, "--json", env=env)
    expect_clean_cli(res, 0, "decide on the factory repository")
    check(json.loads(res.stdout)["applicable"] is False,
          f"the CLI must decide the same on this repository: {res.stdout!r}")

    own_task = REPO_ROOT / ".code-factory" / "state" / "task.yaml"
    if not own_task.is_file():
        print("note: skipping this run's own task file — `.code-factory/` is per-run state and is "
              "not present in a fresh checkout")
        return
    res = run("decide", "--repo", str(REPO_ROOT), "--task-file", str(own_task), "--json", env=env)
    expect_clean_cli(res, 0, "decide on the factory repository with this run's task file")
    check(json.loads(res.stdout)["applicable"] is False,
          f"this run's own task must not activate the Roblox path on a non-Roblox repository: "
          f"{res.stdout!r}")


# --------------------------------------------------------------------- 2. default target

def test_merge_config_default_target(tmp: pathlib.Path) -> None:
    """The DEFAULT registration target: the resolved user-scope GLOBAL CLI config, never typed."""
    # 2.1 KIMI_CODE_HOME is honoured (a TEMP directory of this case only) and the resolved path is
    #     echoed, so the operator sees exactly which file was written.
    root = data_root(tmp, "home-honoured")
    env = base_env(KIMI_CODE_HOME=str(root))
    res = run("merge-config", "--json", env=env)
    expect_clean_cli(res, 0, "merge-config --json (default target via KIMI_CODE_HOME)")
    payload = json.loads(res.stdout)
    target = root / "mcp.json"
    check(payload["path"] == str(target),
          f"the resolved default path must be echoed: {payload['path']!r} != {str(target)!r}")
    check(payload["status"] == "created" and payload["written"] is True and target.is_file(),
          f"a missing default target must be created: {payload}")
    created = target.read_text(encoding="utf-8", newline="")
    entry = json.loads(created)["mcpServers"][rm.SERVER_NAME]
    check(entry == rm.managed_entry(),
          f"the created entry must be the deterministic managed definition: {entry}")
    check(os.path.isabs(entry["args"][1]) and "%LOCALAPPDATA%" not in entry["args"][1],
          f"the launcher path must be expanded and absolute: {entry['args']}")

    # 2.2 Idempotent: the second run changes no byte and says so.
    res = run("merge-config", "--json", env=env)
    expect_clean_cli(res, 0, "merge-config --json (idempotent default target)")
    payload = json.loads(res.stdout)
    check(payload["status"] == "unchanged" and payload["written"] is False,
          f"the second default merge must be a no-op: {payload}")
    check(target.read_text(encoding="utf-8", newline="") == created,
          "the second default merge must not change a single byte")

    # 2.3 An undeterminable data root is a USAGE error (exit 2) and writes NOTHING: a typo'd
    #     environment must never make the helper create a stray data-root tree.
    missing = tmp / "data-root-that-does-not-exist"
    res = run("merge-config", env=base_env(KIMI_CODE_HOME=str(missing)))
    expect_clean_cli(res, 2, "merge-config with a nonexistent KIMI_CODE_HOME")
    check("does not exist" in res.stderr and "KIMI_CODE_HOME" in res.stderr,
          f"a nonexistent data root must be explained: {res.stderr!r}")
    check(not missing.exists(), "a refused default target must never be created")

    # 2.4 No data root can be determined at all (no KIMI_CODE_HOME, no home): exit 2, nothing written.
    res = run("merge-config", env=base_env())
    expect_clean_cli(res, 2, "merge-config with no determinable data root")
    check("USERPROFILE" in res.stderr or "HOME" in res.stderr,
          f"the refusal must name what is missing: {res.stderr!r}")

    # 2.5 HOME FALLBACK: without KIMI_CODE_HOME the data root is `<home>/.kimi-code`.
    home = tmp / "home-directory"
    data_root(home, ".kimi-code")
    env = base_env(USERPROFILE=str(home), HOME=str(home))
    res = run("merge-config", "--json", env=env)
    expect_clean_cli(res, 0, "merge-config --json (home fallback)")
    payload = json.loads(res.stdout)
    fallback = home / ".kimi-code" / "mcp.json"
    check(payload["path"] == str(fallback),
          f"the home fallback must resolve to <home>/.kimi-code/mcp.json: {payload['path']!r}")
    check(fallback.is_file() and payload["status"] == "created",
          f"the home fallback must create the config: {payload}")

    # 2.6 A nonexistent `<home>/.kimi-code` is the same refusal: the helper creates no data root.
    barren_home = tmp / "home-without-data-root"
    barren_home.mkdir()
    res = run("merge-config", env=base_env(USERPROFILE=str(barren_home), HOME=str(barren_home)))
    expect_clean_cli(res, 2, "merge-config with a home that has no data root")
    check(not (barren_home / ".kimi-code").exists(),
          "a refused home fallback must never create the data-root directory")


# --------------------------------------------------------------------- 3. --target override

def test_merge_config_target_override(tmp: pathlib.Path) -> None:
    """`--target` is the explicit override: resolved, parent-checked, echoed — one contract."""
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "override-root")))

    # 3.1 A missing PARENT directory is exit 2: a mistyped fixture path fails loudly instead of
    #     creating directories the operator never named.
    missing_parent = tmp / "override" / "no-such-parent" / "mcp.json"
    res = run("merge-config", "--target", str(missing_parent), env=env)
    expect_clean_cli(res, 2, "merge-config --target with a missing parent")
    check("does not exist" in res.stderr and "parent directory" in res.stderr,
          f"the missing parent must be named: {res.stderr!r}")
    check(not missing_parent.parent.exists(), "a refused --target must not create directories")

    # 3.2 The override is SYMLINK-RESOLVED: a link is followed to its real directory before the
    #     write, and the RESOLVED path is what the result echoes.
    real = tmp / "override" / "real-directory"
    real.mkdir(parents=True)
    link = tmp / "override" / "linked-directory"
    if make_directory_link(link, real):
        res = run("merge-config", "--target", str(link / "mcp.json"), "--json", env=env)
        expect_clean_cli(res, 0, "merge-config --target through a directory link")
        payload = json.loads(res.stdout)
        check(os.path.normcase(payload["path"]) == os.path.normcase(str(real / "mcp.json")),
              f"a linked --target must resolve to its real path: {payload['path']!r}")
        check((real / "mcp.json").is_file(),
              "the write must land in the real directory, not beside the link")
    else:
        print("note: skipping the symlinked --target case — this host cannot create a link")

    target = tmp / "override" / "config" / "mcp.json"
    target.parent.mkdir(parents=True)

    # 3.3 Create, and the resolved path is echoed in the JSON result.
    res = run("merge-config", "--target", str(target), "--json", env=env)
    expect_clean_cli(res, 0, "merge-config --target create")
    payload = json.loads(res.stdout)
    check(payload["path"] == str(target) and payload["status"] == "created",
          f"the override path must be echoed and created: {payload}")
    created = target.read_text(encoding="utf-8", newline="")
    check(json.loads(created)["mcpServers"][rm.SERVER_NAME] == rm.managed_entry(),
          "the override must write the same managed definition as the default target")

    # 3.4 Idempotent second run (byte-identical), as for the default target.
    res = run("merge-config", "--target", str(target), env=env)
    expect_clean_cli(res, 0, "merge-config --target idempotent")
    check(res.stdout.startswith("unchanged"), f"the second override run must be a no-op: {res.stdout!r}")
    check(target.read_text(encoding="utf-8", newline="") == created,
          "the second override run must not change a single byte")


# --------------------------------------------------------------------- 4. one write contract

ORIGINAL_CONFIG = (
    '{\n'
    '  "mcpServers": {\n'
    '    "unrelated-server": {\n'
    '      "command": "python",\n'
    '      "args": ["-m", "unrelated.server"]\n'
    '    }\n'
    '  },\n'
    '  "userSetting": {\n'
    '    "keep": true\n'
    '  }\n'
    '}\n'
)


def test_merge_preserves_unrelated_entries(tmp: pathlib.Path) -> None:
    """Every byte the merge does not have to change survives — for BOTH target kinds."""
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "preserve-root")))

    def expect_preserved(target: pathlib.Path, label: str) -> None:
        head, sep, rest = ORIGINAL_CONFIG.partition("\n    }")
        check(sep == "\n    }", f"{label}: the fixture must contain the expected closing brace")
        expected = head + sep + inserted_member(rm.SERVER_NAME, rm.managed_entry()) + rest
        merged = target.read_text(encoding="utf-8", newline="")
        check(merged == expected,
              f"{label}: unrelated servers, settings and line endings must survive byte-for-byte:\n"
              f"{merged!r}\n!=\n{expected!r}")

    # 4.1 the EXPLICIT override.
    override_target = written(tmp / "preserve" / "override-mcp.json", ORIGINAL_CONFIG)
    res = run("merge-config", "--target", str(override_target), env=env)
    expect_clean_cli(res, 0, "merge-config --target preserve")
    check(res.stdout.startswith("updated"), f"the merge must be reported as updated: {res.stdout!r}")
    expect_preserved(override_target, "--target")

    # 4.2 the hermetic DEFAULT global target — the same contract, not a weaker one.
    root = data_root(tmp, "preserve-default-root")
    written(root / "mcp.json", ORIGINAL_CONFIG)
    res = run("merge-config", env=base_env(KIMI_CODE_HOME=str(root)))
    expect_clean_cli(res, 0, "merge-config default target preserve")
    expect_preserved(root / "mcp.json", "default target")

    # 4.3 CRLF: line endings and unrelated bytes are preserved too.
    crlf_root = data_root(tmp, "crlf-root")
    crlf_text = ORIGINAL_CONFIG.replace("\n", "\r\n")
    written(crlf_root / "mcp.json", crlf_text)
    res = run("merge-config", env=base_env(KIMI_CODE_HOME=str(crlf_root)))
    expect_clean_cli(res, 0, "merge-config CRLF default target")
    crlf_merged = (crlf_root / "mcp.json").read_text(encoding="utf-8", newline="")
    head, sep, rest = crlf_text.partition("\r\n    }")
    expected_crlf = head + sep + inserted_member(rm.SERVER_NAME, rm.managed_entry(),
                                                 newline="\r\n") + rest
    check(crlf_merged == expected_crlf,
          f"a CRLF target must keep its line endings and its unrelated bytes:\n{crlf_merged!r}")

    # 4.4 An empty `mcpServers` map gains the entry, indented like its siblings.
    empty_root = data_root(tmp, "empty-root")
    written(empty_root / "mcp.json", '{\n  "mcpServers": {}\n}\n')
    res = run("merge-config", env=base_env(KIMI_CODE_HOME=str(empty_root)))
    expect_clean_cli(res, 0, "merge-config empty mcpServers")
    emptied = (empty_root / "mcp.json").read_text(encoding="utf-8", newline="")
    check(emptied.startswith('{\n  "mcpServers": {\n    "Roblox_Studio": {\n'),
          f"the entry must be indented like a sibling: {emptied!r}")
    check(list(json.loads(emptied)["mcpServers"]) == [rm.SERVER_NAME],
          f"exactly one server must be added: {emptied!r}")


CONFLICT_CONFIG = (
    '{\n'
    '  "mcpServers": {\n'
    '    "Roblox_Studio": {\n'
    '      "command": "node",\n'
    '      "args": ["--token", "%s"]\n'
    '    },\n'
    '    "unrelated-server": {\n'
    '      "command": "python"\n'
    '    }\n'
    '  }\n'
    '}\n'
) % SECRET


def test_merge_conflict_never_overwrites(tmp: pathlib.Path) -> None:
    """A DIFFERENT `Roblox_Studio` entry is reported (exit 3) and preserved — values withheld."""
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "conflict-root")))

    def expect_conflict(target: pathlib.Path, label: str) -> None:
        before = target.read_bytes()
        res = run("merge-config", "--target", str(target), env=env)
        expect_clean_cli(res, rm.EXIT_CONFLICT, f"{label}: merge-config conflict")
        check("CONFLICT" in res.stderr and "command" in res.stderr,
              f"{label}: the conflict must name the diverging key: {res.stderr!r}")
        check(SECRET not in res.stdout + res.stderr,
              f"{label}: the conflict diagnostic must never echo a stored value: "
              f"{res.stdout!r} {res.stderr!r}")
        check(target.read_bytes() == before,
              f"{label}: a conflicting entry must be preserved byte-for-byte, never overwritten")

    override_target = written(tmp / "conflict" / "override-mcp.json", CONFLICT_CONFIG)
    expect_conflict(override_target, "--target")
    res = run("merge-config", "--target", str(override_target), "--json", env=env)
    payload = json.loads(res.stdout)
    check(res.returncode == rm.EXIT_CONFLICT and payload["status"] == "conflict",
          f"--json must expose the conflict with exit 3: {payload}")
    check(payload["conflict"]["differences"] and "existing" not in payload["conflict"],
          f"the payload must carry the differing KEY names, never the stored values: "
          f"{payload['conflict']}")
    check(SECRET not in res.stdout, f"the --json conflict payload must not echo the entry: {res.stdout!r}")

    # the SAME conflict on the hermetic default global target, and on a non-object entry.
    default_root = data_root(tmp, "conflict-default-root")
    written(default_root / "mcp.json", CONFLICT_CONFIG)
    expect_conflict(default_root / "mcp.json", "default target")

    scalar_root = data_root(tmp, "conflict-scalar-root")
    written(scalar_root / "mcp.json", '{\n  "mcpServers": {\n    "Roblox_Studio": "cmd.exe /c x"\n'
                                      '  }\n}\n')
    res = run("merge-config", env=base_env(KIMI_CODE_HOME=str(scalar_root)))
    expect_clean_cli(res, rm.EXIT_CONFLICT, "merge-config conflict on a non-object entry")
    check("not a JSON object" in res.stderr,
          f"a non-object entry must be explained: {res.stderr!r}")
    check(json.loads((scalar_root / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
          [rm.SERVER_NAME] == "cmd.exe /c x",
          "a non-object entry must be preserved as it was")


def test_merge_invalid_and_dry_run(tmp: pathlib.Path) -> None:
    """An invalid target is refused untouched; `--dry-run` reports without writing."""
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "invalid-root")))

    # 4.5 an invalid JSON target is exit 1 and keeps every byte (it is NEVER overwritten).
    broken_root = data_root(tmp, "invalid-json-root")
    broken_text = '{"mcpServers": {"other": {}}}\nnot json at all\n'
    broken = written(broken_root / "mcp.json", broken_text)
    res = run("merge-config", env=base_env(KIMI_CODE_HOME=str(broken_root)))
    expect_clean_cli(res, 1, "merge-config with an invalid default target")
    check("not valid JSON" in res.stderr, f"the invalid target must be explained: {res.stderr!r}")
    check(broken.read_text(encoding="utf-8", newline="") == broken_text,
          "an invalid target must be left untouched")

    # 4.6 `--dry-run` writes nothing and says so — for a missing and for an existing target.
    dry_root = data_root(tmp, "dry-run-root")
    res = run("merge-config", "--dry-run", env=base_env(KIMI_CODE_HOME=str(dry_root)))
    expect_clean_cli(res, 0, "merge-config --dry-run on a missing target")
    check(not (dry_root / "mcp.json").exists(), "a dry run must not create the target")
    check("[dry-run]" in res.stdout, f"a dry run must say so: {res.stdout!r}")

    existing = written(dry_root / "mcp.json", ORIGINAL_CONFIG)
    before = existing.read_bytes()
    res = run("merge-config", "--dry-run", env=base_env(KIMI_CODE_HOME=str(dry_root)))
    expect_clean_cli(res, 0, "merge-config --dry-run on an existing target")
    check("[dry-run]" in res.stdout and "would update" in res.stdout,
          f"a dry run on an existing target must say what it would do: {res.stdout!r}")
    check(existing.read_bytes() == before, "a dry run must not change a single byte")

    # 4.7 an unchanged dry run is still a no-op report, never a write.
    run("merge-config", env=base_env(KIMI_CODE_HOME=str(dry_root)))
    merged = existing.read_bytes()
    res = run("merge-config", "--dry-run", env=base_env(KIMI_CODE_HOME=str(dry_root)))
    expect_clean_cli(res, 0, "merge-config --dry-run after a real merge")
    check(res.stdout.startswith("unchanged"), f"an equal entry must read as unchanged: {res.stdout!r}")
    check(existing.read_bytes() == merged, "the dry run must not change the merged bytes")


# --------------------------------------------------------------------- 5. validate-config

def test_validate_config(tmp: pathlib.Path) -> None:
    launcher = fake_launcher(tmp)
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "validate-root")))

    # 5.1 a config merged by the CLI for THIS host satisfies the invariants, in the library API and
    #     through the CLI (the host's own launcher path is what both compare against).
    root = data_root(tmp, "validate-merged-root")
    expect_clean_cli(run("merge-config", env=base_env(KIMI_CODE_HOME=str(root))), 0,
                     "merge-config for the validate-config fixture")
    merged = root / "mcp.json"
    check(rm.validate_config(merged) == (True, []),
          f"a merged config must satisfy the invariants: {rm.validate_config(merged)}")
    res = run("validate-config", "--path", str(merged), "--json", env=env)
    expect_clean_cli(res, 0, "validate-config ok")
    payload = json.loads(res.stdout)
    check(payload["ok"] is True and payload["problems"] == [] and payload["path"],
          f"--json must expose path/ok/problems: {payload}")

    with seams(studio_batch_path=lambda: launcher):
        managed = rm.managed_entry()
        check(managed == {"command": "cmd.exe", "args": ["/c", str(launcher)]},
              f"the managed entry must be the reviewed Studio launch shape: {managed}")

        # 5.2 a config WITHOUT the managed entry is valid: the path is simply unused.
        absent = written(tmp / "validate" / "absent.json",
                         json.dumps({"mcpServers": {"other": {"command": "x"}}}, indent=2) + "\n")
        check(rm.validate_config(absent) == (True, []),
              f"an absent managed entry must be valid: {rm.validate_config(absent)}")
        expect_clean_cli(run("validate-config", "--path", str(absent), env=env), 0,
                         "validate-config without a managed entry")

        # 5.3 a missing --path file is exit 2; malformed JSON is exit 1 (no config vs. bad config).
        res = run("validate-config", "--path", str(tmp / "validate" / "nope.json"), env=env)
        expect_clean_cli(res, 2, "validate-config with a missing file")
        check("not an existing file" in res.stderr,
              f"a missing config must be a usage error: {res.stderr!r}")
        ok, problems = rm.validate_config(tmp / "validate" / "nope.json")
        check(not ok and "not found" in problems[0],
              f"a missing config must be DATA in the library API, never a crash: {problems}")

        invalid = written(tmp / "validate" / "invalid.json", '{\n  "mcpServers": {\n')
        res = run("validate-config", "--path", str(invalid), env=env)
        expect_clean_cli(res, 1, "validate-config with malformed JSON")
        check("FAIL" in res.stdout and "not valid JSON" in res.stdout,
              f"malformed JSON must fail loudly: {res.stdout!r}")

        # 5.4 every managed-entry invariant is enforced.
        def variant(label: str, mutate) -> tuple[bool, list[str]]:
            entry = json.loads(json.dumps(managed))
            mutate(entry)
            path = written(tmp / "validate" / f"variant-{label.replace(' ', '-')}.json",
                           json.dumps({"mcpServers": {rm.SERVER_NAME: entry}}, indent=2) + "\n")
            return rm.validate_config(path)

        cases = (
            ("foreign command", lambda e: e.update({"command": "node"}), "command must be 'cmd.exe'"),
            ("missing args", lambda e: e.pop("args"), "args must be exactly"),
            ("extra argument", lambda e: e["args"].append("--verbose"), "args must be exactly"),
            ("missing switch", lambda e: e["args"].pop(0), "args must be exactly"),
            ("wrong switch", lambda e: e["args"].__setitem__(0, "/k"), "shell switch"),
            ("relative launcher", lambda e: e["args"].__setitem__(1, "Roblox/mcp.bat"), "ABSOLUTE"),
            ("wrong directory", lambda e: e["args"].__setitem__(
                1, str(launcher.parent / "other" / "mcp.bat")), "not `…"),
            ("extra key", lambda e: e.update({"env": {"ROBLOX_TOKEN": SECRET}}),
             "exactly the managed keys"),
        )
        for label, mutate, needle in cases:
            ok, problems = variant(label, mutate)
            check(not ok, f"the {label} variant must be rejected: {problems}")
            check(any(needle in problem for problem in problems),
                  f"the {label} variant must explain {needle!r}: {problems}")
            check(all(SECRET not in problem for problem in problems),
                  f"the {label} diagnostic must never echo a stored value: {problems}")

        # 5.5 no diagnostic echoes a value the entry supplies — human output AND --json.
        secret_config = written(tmp / "validate" / "secret.json", json.dumps(
            {"mcpServers": {rm.SERVER_NAME: {"command": f"cmd.exe {SECRET}",
                                             "args": ["--token", SECRET],
                                             "env": {"TOKEN": SECRET}}}}, indent=2) + "\n")
        res = run("validate-config", "--path", str(secret_config), env=env)
        expect_clean_cli(res, 1, "validate-config of an entry carrying a credential")
        check("command must be 'cmd.exe'" in res.stdout,
              f"the diagnostics must still name the violated invariant: {res.stdout!r}")
        check(SECRET not in res.stdout + res.stderr,
              f"validate-config must not echo the entry: {res.stdout!r} {res.stderr!r}")
        res = run("validate-config", "--path", str(secret_config), "--json", env=env)
        expect_clean_cli(res, 1, "validate-config --json of an entry carrying a credential")
        check(SECRET not in res.stdout + res.stderr,
              f"the --json diagnostics must not echo the entry: {res.stdout!r}")

        # 5.6 a non-object `Roblox_Studio` entry and a non-object `mcpServers` are refused as data.
        scalar = written(tmp / "validate" / "scalar-entry.json",
                         json.dumps({"mcpServers": {rm.SERVER_NAME: "cmd.exe /c x"}}) + "\n")
        ok, problems = rm.validate_config(scalar)
        check(not ok and any("must be a JSON object" in problem for problem in problems),
              f"a non-object entry must be rejected: {problems}")
        servers = written(tmp / "validate" / "scalar-servers.json",
                          json.dumps({"mcpServers": ["nope"]}) + "\n")
        ok, problems = rm.validate_config(servers)
        check(not ok and any("mcpServers must be a JSON object" in problem for problem in problems),
              f"a non-object mcpServers must be rejected: {problems}")


# --------------------------------------------------------------------- 6. scenario runner

def scenario_evidence(tmp: pathlib.Path, name: str) -> pathlib.Path:
    return tmp / "evidence" / name


def test_scenario_runner(tmp: pathlib.Path) -> None:
    """A structured verdict DERIVED from the captured console output of a real (fake) MCP session."""
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "scenario-root")))
    good = studio_server(tmp, "honest")
    erroring = studio_server(tmp, "erroring", console=ERROR_CONSOLE)

    # 6.0 the MANAGED launch (no `--executable`): the scenario argv is the managed Studio entry,
    #     whose `command` is ONE argv element — the executable `cmd.exe`, never its characters. The
    #     launcher seam keeps this hermetic: the operator's real `%LOCALAPPDATA%` is never resolved
    #     and no process is started.
    launcher = fake_launcher(tmp)
    with seams(studio_batch_path=lambda: launcher):
        argv = rm.scenario_argv(None)
        check(argv[0] == "cmd.exe",
              f"the managed scenario must launch cmd.exe as ONE argv element, not its characters: "
              f"{argv}")
        check(argv == ["cmd.exe", "/c", str(launcher)],
              f"the managed scenario argv must be the reviewed `cmd.exe /c <launcher>` shape, with "
              f"the launcher as an ABSOLUTE argument: {argv}")
        check(pathlib.Path(argv[2]).is_absolute(),
              f"the managed launcher argument must be absolute: {argv}")
        check(rm.scenario_argv(None, ["--probe"]) == ["cmd.exe", "/c", str(launcher), "--probe"],
              f"the extra scenario args must follow the managed ones: "
              f"{rm.scenario_argv(None, ['--probe'])}")

    # 6.1 PASS: the scenario completes, its console output is captured, its sha256 recorded, and a
    #     screenshot is an ARTIFACT — never the verdict.
    scenario = write_scenario(tmp, "honest-pickup", ONE_STEP, screenshot="screenshot.png")
    evidence = scenario_evidence(tmp, "honest")
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence", str(evidence),
              "--timeout-seconds", "120", "--executable", good[0], "--arg", good[1], "--json", env=env)
    expect_clean_cli(res, 0, "scenario run (honest PASS)")
    payload = json.loads(res.stdout)
    record = payload["record"]
    check(payload["verdict"] == "PASS" and record["completed"] is True,
          f"an error-free completed scenario must be a PASS: {record['reasons']}")
    check(record["error_lines"] == [], f"no error line may be recorded: {record['error_lines']}")
    console_path = pathlib.Path(record["console"]["path"])
    check(console_path.name == rm.CONSOLE_FILE and console_path.is_file(),
          f"the console capture must be written as {rm.CONSOLE_FILE}: {console_path}")
    console_text = console_path.read_text(encoding="utf-8", newline="")
    check(console_text.splitlines() == list(GOOD_CONSOLE),
          f"the captured console output must be the server's own lines: {console_text!r}")
    check(record["console"]["sha256"] == hashlib.sha256(console_text.encode("utf-8")).hexdigest(),
          f"the recorded console sha256 must match the written file: {record['console']}")
    verdict_path = pathlib.Path(payload["verdict_path"])
    check(verdict_path.name == rm.VERDICT_FILE and verdict_path.is_file(),
          f"the structured verdict must be stored as {rm.VERDICT_FILE}: {verdict_path}")
    stored = json.loads(verdict_path.read_text(encoding="utf-8"))
    check(stored == record, "the stored verdict must be the returned record")
    check(stored["screenshot_is_verdict"] is False,
          f"a screenshot is never the verdict: {stored['screenshot_is_verdict']}")
    check([shot["path"] for shot in stored["screenshots"]],
          f"the declared screenshot must be recorded as an artifact: {stored['screenshots']}")
    check(stored["steps"] and all(step["ok"] for step in stored["steps"]),
          f"every scenario step must be ok: {stored['steps']}")
    check(stored["tools"] == list(STUDIO_TOOLS),
          f"the server's tool listing must be recorded: {stored['tools']}")

    # 6.2 FAIL: a run that logged an error is NEVER a pass — exit 1, the error line named.
    broken_scenario = write_scenario(tmp, "broken-pickup", ONE_STEP, screenshot="screenshot.png")
    broken_evidence = scenario_evidence(tmp, "broken")
    res = run("scenario", "run", "--scenario", str(broken_scenario), "--evidence",
              str(broken_evidence), "--timeout-seconds", "120", "--executable", erroring[0],
              "--arg", erroring[1], "--json", env=env)
    expect_clean_cli(res, 1, "scenario run (error in the console)")
    payload = json.loads(res.stdout)
    record = payload["record"]
    check(payload["verdict"] == "FAIL" and record["verdict"] == "FAIL",
          f"a run that logged an error must be FAIL: {record['reasons']}")
    check(record["completed"] is True,
          f"the FAIL must come from the console, not from an incomplete run: {record['steps']}")
    check(record["error_lines"] and "Infinite yield possible" in record["error_lines"][0],
          f"the offending console line must be recorded: {record['error_lines']}")
    check(any("NEVER a pass" in reason for reason in record["reasons"]),
          f"the verdict must state why it failed: {record['reasons']}")
    check(record["screenshot_is_verdict"] is False and record["screenshots"],
          "a FAIL carries its screenshot as an artifact and still never as a verdict")
    res = run("scenario", "verdict", "--evidence", str(broken_evidence), env=env)
    expect_clean_cli(res, 1, "scenario verdict of a FAIL record")
    check(res.stdout.startswith("FAIL"), f"the stored FAIL must be reported: {res.stdout!r}")

    # 6.2b `isError` is a BOOLEAN by contract, so every PRESENT value that is not one leaves the
    #      tool-level outcome UNKNOWN and is refused BEFORE any `content` can be read as a success.
    #      A string ("true"/"false") and a number (1/0) are NOT coerced: a server that says "false"
    #      in prose, or `1`, may still be reporting a failure.
    well_formed = {"content": [{"type": "text", "text": GOOD_CONSOLE[0]}]}
    check(rm._mcp_result_problem(well_formed) is None,
          "a result WITHOUT an isError member and with content is a well-formed answer")
    check(rm._mcp_result_problem({**well_formed, "isError": False}) is None,
          "isError: false is the legal success shape")
    check("isError: true" in (rm._mcp_result_problem({**well_formed, "isError": True}) or ""),
          "isError: true must stay the tool-level FAILURE it is")
    for shape in ("true", "false", "", 1, 0, 1.0, None, [], {}):
        problem = rm._mcp_result_problem({**well_formed, "isError": shape})
        check(problem is not None and "non-boolean" in problem,
              f"a present isError={shape!r} must be refused as non-boolean: {problem}")
    for label, value in (("string-true", "true"), ("number-one", 1), ("number-zero", 0)):
        lying = studio_server(tmp, f"is-error-{label}", is_error=value)
        lying_scenario = write_scenario(tmp, f"is-error-{label}", ONE_STEP)
        lying_evidence = scenario_evidence(tmp, f"is-error-{label}")
        res = run("scenario", "run", "--scenario", str(lying_scenario), "--evidence",
                  str(lying_evidence), "--timeout-seconds", "120", "--executable", lying[0],
                  "--arg", lying[1], "--json", env=env)
        expect_clean_cli(res, 1, f"scenario run (isError={value!r})")
        payload = json.loads(res.stdout)
        record = payload["record"]
        check(payload["verdict"] == "FAIL" and record["completed"] is False,
              f"a server answering isError={value!r} must never complete the scenario: "
              f"{record['steps']}")
        check(record["steps"] and record["steps"][0]["ok"] is False
              and "non-boolean" in record["steps"][0]["message"],
              f"the refused step must name the non-boolean isError: {record['steps']}")
    # …and the ABSENT member is the legal shape: no tool-level failure was reported, so it still
    # completes, exactly like `isError: false`.
    silent = studio_server(tmp, "is-error-absent", is_error=ABSENT_IS_ERROR)
    silent_scenario = write_scenario(tmp, "is-error-absent", ONE_STEP)
    res = run("scenario", "run", "--scenario", str(silent_scenario), "--evidence",
              str(scenario_evidence(tmp, "is-error-absent")), "--timeout-seconds", "120",
              "--executable", silent[0], "--arg", silent[1], "--json", env=env)
    expect_clean_cli(res, 0, "scenario run (no isError member)")
    check(json.loads(res.stdout)["verdict"] == "PASS",
          "a result without an isError member and an error-free console is still a PASS")

    # 6.3 INPUT BOUNDARIES (exit 2), each writing NOTHING.
    zero_step = write_scenario(tmp, "zero-step", [])
    calls = {
        "zero-step scenario": ["scenario", "run", "--scenario", str(zero_step), "--evidence",
                               str(scenario_evidence(tmp, "b0"))],
        "timeout 0": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                      str(scenario_evidence(tmp, "b1")), "--timeout-seconds", "0"],
        "timeout negative": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                             str(scenario_evidence(tmp, "b2")), "--timeout-seconds", "-5"],
        "timeout inf": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                        str(scenario_evidence(tmp, "b3")), "--timeout-seconds", "inf"],
        "timeout nan": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                        str(scenario_evidence(tmp, "b4")), "--timeout-seconds", "nan"],
        "timeout 3601": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                         str(scenario_evidence(tmp, "b5")), "--timeout-seconds", "3601"],
        "missing executable": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                               str(scenario_evidence(tmp, "b6")), "--executable",
                               str(tmp / "no-such-executable")],
        "empty --arg": ["scenario", "run", "--scenario", str(scenario), "--evidence",
                        str(scenario_evidence(tmp, "b7")), "--executable", sys.executable,
                        "--arg", ""],
        "missing scenario file": ["scenario", "run", "--scenario",
                                  str(tmp / "scenarios" / "no-such-scenario.json"), "--evidence",
                                  str(scenario_evidence(tmp, "b8"))],
    }
    for label, argv in calls.items():
        expect_clean_cli(run(*argv, env=env), 2, f"scenario run with {label}")
    for index in range(9):
        check(not scenario_evidence(tmp, f"b{index}").exists(),
              f"a refused scenario run must not create the evidence directory (b{index})")

    # 6.4 the timeout contract itself: (0, 3600] with a real, finite number — no bools, no strings.
    for accepted in (0.5, 1, 60.0, 3600, 3600.0, 3599.5):
        check(rm._timeout_problem("--timeout-seconds", accepted) is None,
              f"a timeout of {accepted!r} must be accepted")
    for rejected in (0, 0.0, -1, -0.5, 3601, 3600.001, float("inf"), float("-inf"), float("nan"),
                     True, False, "60", None, 10 ** 400):
        problem = rm._timeout_problem("--timeout-seconds", rejected)
        check(problem is not None, f"a timeout of {rejected!r} must be refused")
        check("--timeout-seconds" in problem, f"the refusal must name the argument: {problem!r}")

    # 6.5 an accepted upper-bound budget really runs (the bound is accepted, not clamped to zero).
    upper = scenario_evidence(tmp, "upper-bound")
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence", str(upper),
              "--timeout-seconds", "3600", "--executable", good[0], "--arg", good[1], env=env)
    expect_clean_cli(res, 0, "scenario run at the maximum timeout")
    check(res.stdout.startswith("PASS"), f"the accepted budget must run the scenario: {res.stdout!r}")

    # 6.6 `--probe-tool` asserts the tool is present; an absent one degrades the run to FAIL.
    evidence = scenario_evidence(tmp, "probe-tool")
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence", str(evidence),
              "--timeout-seconds", "120", "--executable", good[0], "--arg", good[1],
              "--probe-tool", "start_stop_play", env=env)
    expect_clean_cli(res, 0, "scenario run --probe-tool (present)")
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence",
              str(scenario_evidence(tmp, "probe-tool-missing")), "--timeout-seconds", "120",
              "--executable", good[0], "--arg", good[1], "--probe-tool", "no_such_tool", env=env)
    expect_clean_cli(res, 1, "scenario run --probe-tool (absent)")
    check("no_such_tool" in res.stdout,
          f"the missing probe tool must be named: {res.stdout!r}")

    # 6.7 a transport failure stops the run and the SKIPPED steps are numbered 1-based, like every
    #     other step reference a human reads (a 0-based "step 0" reads as a missing step).
    steps = [{"tool": "execute_luau"}, {"tool": "start_stop_play"}, {"tool": "get_console_output"}]
    attempted: list[int] = []

    def breaking_call(server, index, step):
        attempted.append(index)
        return ({"tool": step["tool"], "ok": False, "error_code": None,
                 "message": "the server closed stdin before the tools/call execute_luau request"},
                [], 0, True)

    with seams(_call_step=breaking_call):
        outcomes, console, images = rm._run_steps(object(), steps)
    check(attempted == [0], f"a transport failure must end the session at once: {attempted}")
    check(len(outcomes) == len(steps) and console == [] and images == 0,
          f"every step must be accounted for: {outcomes}")
    check(outcomes[0]["ok"] is False, f"the broken step is not ok: {outcomes[0]}")
    check("before step 2" in outcomes[1]["message"] and
          "before step 3" in outcomes[2]["message"],
          f"the skipped steps must be numbered 1-based: {[o['message'] for o in outcomes[1:]]}")
    check("step 0" not in outcomes[1]["message"],
          f"no zero-based step number may be printed: {outcomes[1]['message']!r}")


def test_stop_kills_descendants_after_launcher_exit(tmp: pathlib.Path) -> None:
    """The bounded stop kills what the session spawned even when the DIRECT child already exited.

    Regression for review r1: cleanup used to return as soon as `proc.poll()` reported an exit, so a
    launcher that starts the Studio server and exits (exactly what `mcp.bat` may do) leaked the
    surviving server. Both cleanup paths are pinned: the `scenario run` CLI path and the
    library-level handshake (`probe --check-mcp-start`).
    """
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "cleanup-root")))
    launcher = written(tmp / "cleanup" / "orphaning_launcher.py", ORPHANING_LAUNCHER)
    scenario = write_scenario(tmp, "orphaning-launcher", ONE_STEP)

    # 6.8 the SCENARIO path: the launcher exits, its child survives, the stop must reach the child.
    scenario_pid_file = tmp / "cleanup" / "scenario-child.pid"
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence",
              str(scenario_evidence(tmp, "orphan")), "--timeout-seconds", "5",
              "--executable", sys.executable, "--arg", str(launcher),
              "--arg", str(scenario_pid_file), env=env)
    check(res.returncode in (0, 1),
          f"a launcher that dies must still produce a verdict, not a crash: {res.returncode} "
          f"{res.stderr!r}")
    check("Traceback" not in res.stderr, f"cleanup must never crash: {res.stderr!r}")
    scenario_child = recorded_pid(scenario_pid_file)
    check(scenario_child is not None,
          f"the fixture launcher must record the pid of the child it started: {scenario_pid_file}")
    if scenario_child is not None:
        alive = True
        try:
            alive = not wait_gone(scenario_child)
        finally:
            if alive:                                   # never leak the probe child
                kill_pid(scenario_child)
        check(not alive,
              "the scenario stop must terminate the child of an ALREADY EXITED launcher: the "
              f"surviving descendant {scenario_child} was still running after `scenario run` "
              "returned, so the bounded-stop guarantee is broken")

    # 6.9 the HANDSHAKE path (`probe --check-mcp-start`) uses the same bounded stop.
    handshake_pid_file = tmp / "cleanup" / "handshake-child.pid"
    result = rm._handshake([sys.executable, str(launcher), str(handshake_pid_file)],
                           str(tmp / "cleanup"), 5.0)
    check(result["ok"] is False,
          f"a launcher that never answers initialize must not be a green handshake: {result}")
    handshake_child = recorded_pid(handshake_pid_file)
    check(handshake_child is not None,
          f"the fixture launcher must record the handshake child's pid: {handshake_pid_file}")
    if handshake_child is not None:
        alive = True
        try:
            alive = not wait_gone(handshake_child)
        finally:
            if alive:
                kill_pid(handshake_child)
        check(not alive,
              f"the handshake stop must terminate the surviving descendant {handshake_child} of an "
              "already exited launcher")


def expect_no_survivor(pid_file: pathlib.Path, label: str) -> None:
    """The launcher's recorded child must be GONE (a survivor is killed for fixture hygiene)."""
    child = recorded_pid(pid_file)
    check(child is not None,
          f"{label}: the fixture launcher must record the pid of the child it started: {pid_file}")
    if child is None:
        return
    alive = True
    try:
        alive = not wait_gone(child)
    finally:
        if alive:                                       # never leak the probe child
            kill_pid(child)
    check(not alive,
          f"{label}: the child {child} of the launcher was still running, so the refused session "
          "leaked exactly what its refusal is meant to prevent")


def test_job_refusal_fails_closed(tmp: pathlib.Path) -> None:
    """A host that REFUSES job assignment must refuse the SESSION instead of leaking its child.

    Regression for review r2: the assignment-refusal branch used to fall back to the
    leader-dependent `taskkill`, so a launcher that started the Studio server and exited left it
    running — the r1 descendant leak, restored on the one branch the docstring called "fail-soft".
    The session now terminates the still-live tree and reports the missing guarantee on BOTH paths
    that share `_StdioServer`: the scenario runner (a FAIL verdict naming the cause) and the
    `probe --check-mcp-start` handshake (a missing capability with the same reason).
    """
    launcher = written(tmp / "refusal" / "holding_launcher.py", HOLDING_LAUNCHER)
    scenario = write_scenario(tmp, "refused-job", ONE_STEP)
    original = rm._adopt_tree

    # 6.13 the SCENARIO path: the verdict is FAIL and names the refused assignment, the run never
    #      serves a step, and no child of the launcher survives the refusal.
    scenario_pid_file = tmp / "refusal" / "scenario-child.pid"
    rm._adopt_tree = refused_job(scenario_pid_file)
    try:
        result = rm.run_scenario(scenario, str(scenario_evidence(tmp, "refused-job")), 2.0,
                                 executable=sys.executable,
                                 extra_args=[str(launcher), str(scenario_pid_file), "2"])
    finally:
        rm._adopt_tree = original
    record = result["record"]
    expect_no_survivor(scenario_pid_file, "the scenario runner refused the job assignment")
    check(record["verdict"] == "FAIL" and result["verdict"] == "FAIL",
          "a session whose cleanup cannot be guaranteed must FAIL, never run: "
          f"{record['reasons']}")
    check(record["completed"] is False and all(step["ok"] is False for step in record["steps"]),
          f"no scenario step may be attempted without a start: {record['steps']}")
    check(all("not attempted" in step["message"] for step in record["steps"]),
          f"every step must be reported as never reached: {record['steps']}")
    check(any("job object" in reason and "refused" in reason for reason in record["reasons"]),
          f"the verdict must name the refused job assignment: {record['reasons']}")

    # 6.14 the HANDSHAKE path (`probe --check-mcp-start`) shares the same bounded start, so it must
    #      report the missing capability with the same reason and leave nothing running.
    handshake_pid_file = tmp / "refusal" / "handshake-child.pid"
    rm._adopt_tree = refused_job(handshake_pid_file)
    try:
        result = rm._handshake([sys.executable, str(launcher), str(handshake_pid_file), "2"],
                               str(tmp / "refusal"), 2.0)
    finally:
        rm._adopt_tree = original
    check(result["ok"] is False,
          f"a refused job assignment is never a green handshake: {result}")
    expect_no_survivor(handshake_pid_file, "the handshake refused the job assignment")
    check("job object" in result["message"] and "refused" in result["message"],
          f"the handshake must report the missing guarantee, not a generic failure: {result}")
    check(result["tools"] == [] and result["protocol_version"] is None,
          f"a refused session must report no session data at all: {result}")


# --------------------------------------------------------------------- 6b. capture ORDER

def test_console_capture_precedes_teardown(tmp: pathlib.Path) -> None:
    """The console is CAPTURED before the session is stopped — teardown noise is never a verdict.

    Regression for the false FAIL of the live acceptance re-run: `run_scenario` read
    `stderr_lines()` AFTER `stop()` (a real process-tree kill), so the noise the peer's own death
    printed — "WARN … WebSocket error from proxy …: Connection reset without closing handshake" —
    landed in the captured console and flipped a perfect scenario (every step ok, no error logged
    while it ran) to FAIL. The root cause is the capture ORDER, not the error rule: the verdict
    judges the SCENARIO, never the shutdown that follows it.
    """
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "teardown-root")))
    scenario = write_scenario(tmp, "noisy-teardown", ONE_STEP)

    # 6.10 the DETERMINISTIC shape of the defect: the drain thread lands the dying peer's line while
    #      the tree is being killed. The stop seam is the REAL teardown plus exactly that one line, so
    #      the case is not a race — with the capture taken first the SAME scenario must be a PASS.
    dying = studio_server(tmp, "dying-peer", death_noise=TEARDOWN_NOISE)
    original_stop = rm._StdioServer.stop

    def noisy_stop(self) -> None:
        try:
            original_stop(self)
        finally:
            self.stderr_tail.append(TEARDOWN_NOISE)

    rm._StdioServer.stop = noisy_stop
    try:
        result = rm.run_scenario(scenario, str(scenario_evidence(tmp, "seam")), 120.0,
                                 executable=dying[0], extra_args=[dying[1]])
    finally:
        rm._StdioServer.stop = original_stop
    record = result["record"]
    check(record["verdict"] == "PASS",
          "teardown noise must never flip a completed, error-free scenario to FAIL: "
          f"{record['reasons']}")
    check(record["completed"] is True and all(step["ok"] for step in record["steps"]),
          f"every step answered, so the verdict must be derived from that: {record['steps']}")
    check(record["error_lines"] == [],
          f"a death rattle is not a console error line: {record['error_lines']}")
    seam_console = pathlib.Path(result["console_path"]).read_text(encoding="utf-8", newline="")
    check(seam_console.splitlines() == list(GOOD_CONSOLE),
          f"the console capture must hold the scenario's own lines only: {seam_console!r}")

    # 6.11 the SAME defect with a REAL dying peer: the fake server writes its noise only once stdin
    #      closes — i.e. during the stop — so `run_scenario` must still answer PASS through the CLI.
    noisy = studio_server(tmp, "eof-noisy", death_noise=TEARDOWN_NOISE)
    evidence = scenario_evidence(tmp, "eof-noisy")
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence", str(evidence),
              "--timeout-seconds", "120", "--executable", noisy[0], "--arg", noisy[1], "--json",
              env=env)
    expect_clean_cli(res, 0, "scenario run (peer logs its death noise on shutdown)")
    payload = json.loads(res.stdout)
    check(payload["verdict"] == "PASS",
          f"a peer's shutdown noise must not fail the scenario: {payload['record']['reasons']}")
    eof_console = pathlib.Path(payload["console_path"]).read_text(encoding="utf-8", newline="")
    check(eof_console.splitlines() == list(GOOD_CONSOLE) and
          TEARDOWN_NOISE not in eof_console,
          f"console.log must carry no teardown line: {eof_console!r}")
    check(all(TEARDOWN_NOISE not in line for line in payload["record"]["error_lines"]),
          f"the teardown line must never be recorded as a console error: "
          f"{payload['record']['error_lines']}")

    # 6.12 …while a line the peer logged DURING the scenario stays console evidence: capturing
    #      BEFORE the stop keeps every line written while it was serving, so that run still FAILs.
    loud = studio_server(tmp, "live-noisy", live_noise=ERROR_CONSOLE[1])
    res = run("scenario", "run", "--scenario", str(scenario), "--evidence",
              str(scenario_evidence(tmp, "live-noisy")), "--timeout-seconds", "120",
              "--executable", loud[0], "--arg", loud[1], "--json", env=env)
    expect_clean_cli(res, 1, "scenario run (peer logs an error while serving)")
    record = json.loads(res.stdout)["record"]
    check(record["verdict"] == "FAIL",
          f"an error logged DURING the scenario is still a FAIL: {record['reasons']}")
    check(record["error_lines"] and "Infinite yield possible" in record["error_lines"][0],
          f"a live stderr error must be CAPTURED, never dropped with the teardown: "
          f"{record['error_lines']}")


# --------------------------------------------------------------------- 7. scenario verify

def test_scenario_verify(tmp: pathlib.Path) -> None:
    """`scenario verify` exits 0 ONLY for an honest PASS — the stored field is never trusted."""
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "verify-root")))
    good = studio_server(tmp, "verify-honest")
    erroring = studio_server(tmp, "verify-erroring", console=ERROR_CONSOLE)
    scenario = write_scenario(tmp, "verify-pickup", ONE_STEP, screenshot="screenshot.png")

    def run_scenario(evidence: pathlib.Path, server: list[str]) -> dict:
        res = run("scenario", "run", "--scenario", str(scenario), "--evidence", str(evidence),
                  "--timeout-seconds", "120", "--executable", server[0], "--arg", server[1],
                  "--json", env=env)
        check(res.returncode in (0, 1),
              f"the fixture scenario must produce a verdict: {res.returncode} {res.stderr!r}")
        return json.loads(res.stdout)["record"]

    # 7.1 an honest PASS: exit 0, and the gate re-derived the answer from the artifacts.
    honest = scenario_evidence(tmp, "honest")
    run_scenario(honest, good)
    res = run("scenario", "verify", "--evidence", str(honest), "--json", env=env)
    expect_clean_cli(res, 0, "scenario verify (honest PASS)")
    payload = json.loads(res.stdout)
    check(payload["ok"] is True and payload["problems"] == [],
          f"an honest PASS must be the only green: {payload}")

    def stored(evidence: pathlib.Path) -> dict:
        return json.loads((evidence / rm.VERDICT_FILE).read_text(encoding="utf-8"))

    def rewrite(evidence: pathlib.Path, mutate) -> None:
        record = stored(evidence)
        mutate(record)
        written(evidence / rm.VERDICT_FILE, json.dumps(record, indent=2) + "\n")

    def expect_refused(evidence: pathlib.Path, needle: str, label: str) -> None:
        res = run("scenario", "verify", "--evidence", str(evidence), "--json", env=env)
        expect_clean_cli(res, 1, f"scenario verify ({label})")
        problems = json.loads(res.stdout)["problems"]
        check(any(needle in problem for problem in problems),
              f"{label}: the refusal must explain {needle!r}: {problems}")

    # 7.2 a TAMPERED verdict: a FAIL record rewritten to claim PASS.
    tampered = scenario_evidence(tmp, "tampered-verdict")
    run_scenario(tampered, erroring)
    rewrite(tampered, lambda record: record.update({"verdict": "PASS"}))
    expect_refused(tampered, "error line", "verdict flipped to PASS")

    # 7.3 a SHA-MISMATCHED console: the log was edited after the verdict was derived from it.
    stale = scenario_evidence(tmp, "stale-console")
    run_scenario(stale, good)
    console = stale / rm.CONSOLE_FILE
    console.write_text(console.read_text(encoding="utf-8") + "later line\n", encoding="utf-8")
    expect_refused(stale, "sha256 mismatch", "console edited after the verdict")

    # 7.4 a FAIL record is refused (the stored verdict alone is not the gate).
    failed = scenario_evidence(tmp, "failed-record")
    run_scenario(failed, erroring)
    expect_refused(failed, "not 'PASS'", "stored FAIL record")

    # 7.5 a verdict claiming the SCREENSHOT as its verdict can never pass, however green the rest is.
    screenshot_verdict = scenario_evidence(tmp, "screenshot-verdict")
    run_scenario(screenshot_verdict, good)
    rewrite(screenshot_verdict, lambda record: record.update({"screenshot_is_verdict": True}))
    expect_refused(screenshot_verdict, "screenshot is never the verdict", "screenshot_is_verdict")

    # 7.6 an incomplete record (a step not ok / no completed proof) is refused too.
    incomplete = scenario_evidence(tmp, "incomplete")
    run_scenario(incomplete, good)
    rewrite(incomplete, lambda record: record.update({"completed": False}))
    expect_refused(incomplete, "COMPLETED", "record without a completed proof")

    # 7.7 a missing evidence directory or a missing verdict record is an error (exit 1), never a pass.
    res = run("scenario", "verify", "--evidence", str(scenario_evidence(tmp, "nothing-here")), env=env)
    expect_clean_cli(res, 1, "scenario verify of a missing evidence directory")
    check("evidence directory not found" in res.stderr,
          f"a missing evidence directory must be named: {res.stderr!r}")
    empty_dir = scenario_evidence(tmp, "empty")
    empty_dir.mkdir(parents=True)
    res = run("scenario", "verify", "--evidence", str(empty_dir), env=env)
    expect_clean_cli(res, 1, "scenario verify of an empty evidence directory")
    check("no verdict record" in res.stderr, f"a missing verdict must be named: {res.stderr!r}")


# --------------------------------------------------------------------- 8. probe

def test_probe(tmp: pathlib.Path) -> None:
    """Fail-soft: a missing capability is DATA (exit 0); the Studio start is strictly opt-in."""
    repo = roblox_repo(tmp / "probe" / "coin-game")

    # 8.1 missing capabilities are data: exit 0, each capability reports presence AND a reason.
    root = data_root(tmp, "probe-root")
    env = base_env(KIMI_CODE_HOME=str(root))
    res = run("probe", "--repo", str(repo), "--json", env=env)
    expect_clean_cli(res, 0, "probe (no managed config yet)")
    payload = json.loads(res.stdout)
    for name in rm.CAPABILITY_NAMES:
        cap = payload["capabilities"][name]
        check(isinstance(cap["present"], bool) and cap["reason"].strip(),
              f"capability {name} must report presence + reason: {cap}")
    check(payload["capabilities"]["mcp_config"]["present"] is False,
          f"a missing managed config must be reported: {payload['capabilities']}")
    check("mcp_config" in payload["missing"] and payload["roblox_usable"] is False,
          f"an unregistered Studio server must be unusable: {payload['missing']}")
    check(payload["roblox_repository"] is True,
          f"the repository markers must be reported: {payload['host_signals']['details']}")
    check(payload["handshake"] is None,
          "the Studio handshake must never run unless it is asked for explicitly")

    # 8.2 an UNDETERMINABLE data root is a missing capability, not an abort: exit 0.
    bare_env = {key: value for key, value in base_env().items()
                if key not in ("LOCALAPPDATA",)}
    res = run("probe", "--repo", str(repo), "--json", env=bare_env)
    expect_clean_cli(res, 0, "probe with no determinable data root or launcher")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["mcp_config"]["present"] is False,
          f"an undeterminable data root must be a missing capability: {payload['capabilities']}")
    check("cannot be located" in payload["capabilities"]["mcp_config"]["reason"],
          f"the capability must carry its reason: {payload['capabilities']['mcp_config']}")
    check(payload["capabilities"]["mcp_config"]["reason"].count("cannot be located") == 1,
          "the reason must state the missing location ONCE, without repeating the lead: "
          f"{payload['capabilities']['mcp_config']['reason']!r}")
    check(payload["config"] is None and payload["roblox_usable"] is False,
          f"no config may be reported when none could be located: {payload}")

    # 8.3 a TYPO'd data root is fail-soft DATA here (the merge refuses it, the probe reports it).
    res = run("probe", "--repo", str(repo), "--json",
              env=base_env(KIMI_CODE_HOME=str(tmp / "probe" / "typo-root")))
    expect_clean_cli(res, 0, "probe with a nonexistent data root")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["mcp_config"]["present"] is False
          and "does not exist" in payload["capabilities"]["mcp_config"]["reason"],
          f"a nonexistent data root must be reported as a missing capability: {payload}")
    check(payload["capabilities"]["mcp_config"]["reason"].count("cannot be located") == 1,
          "the location lead must appear ONCE in front of the cause: "
          f"{payload['capabilities']['mcp_config']['reason']!r}")

    # 8.4 a merged default config makes the config capability green (hermetic data root).
    run("merge-config", env=env)
    res = run("probe", "--repo", str(repo), "--json", env=env)
    expect_clean_cli(res, 0, "probe of a merged default config")
    payload = json.loads(res.stdout)
    check(payload["capabilities"]["mcp_config"]["present"] is True and payload["config_valid"] is True,
          f"a merged config must be a present, valid capability: {payload['config_problems']}")
    check(payload["config"] == str(root / "mcp.json") and payload["config_entry_present"] is True,
          f"the probe must report WHICH config it inspected: {payload['config']}")

    # 8.5 `--out`: the resolved artifact path is echoed and written; a missing parent is exit 2.
    out_dir = root / "state"
    out_dir.mkdir()
    res = run("probe", "--repo", str(repo), "--out", str(out_dir), "--json", env=env)
    expect_clean_cli(res, 0, "probe --out <dir>")
    payload = json.loads(res.stdout)
    check(payload["out"] == str(out_dir / rm.PROBE_FILE_NAME)
          and (out_dir / rm.PROBE_FILE_NAME).is_file(),
          f"--out must echo and write the resolved path: {payload.get('out')!r}")
    res = run("probe", "--repo", str(repo), "--out", str(tmp / "probe" / "no-parent" / "p.json"),
              env=env)
    expect_clean_cli(res, 2, "probe --out with a missing parent")
    check("does not exist" in res.stderr, f"a missing --out parent must be explained: {res.stderr!r}")

    # 8.6 a repository that is not a Roblox project is degraded data (exit 0), not an error.
    res = run("probe", "--repo", str(bare_repo(tmp / "probe" / "bare")), "--json", env=env)
    expect_clean_cli(res, 0, "probe of a non-Roblox repository")
    check(json.loads(res.stdout)["roblox_repository"] is False,
          f"a non-Roblox repository must be reported as such: {res.stdout[:400]!r}")


def test_probe_check_mcp_start(tmp: pathlib.Path) -> None:
    """The Studio handshake is opt-in and driven through seams — NO real Studio ever starts."""
    repo = roblox_repo(tmp / "probe-start" / "coin-game")
    launcher = fake_launcher(tmp)
    started: list[dict] = []

    def recording_handshake(argv, cwd, budget):
        started.append({"argv": list(argv), "cwd": cwd, "budget": budget})
        return {"ok": True, "stage": "tools/list", "message": "the Studio server answered",
                "tools": list(STUDIO_TOOLS), "cwd": cwd, "command": list(argv),
                "protocol_version": "2024-11-05", "server": "fake-studio", "exit_code": None,
                "stderr_tail": []}

    with seams(studio_batch_path=lambda: launcher):
        target = launcher.parent.parent.parent / "fake-data-root" / "mcp.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        merged = rm.merge_config(target=str(target))
        check(merged["status"] == "created", f"the hermetic fixture must merge: {merged}")

        # 8.7 with the handshake seam the capability is green — and the seam, not a real process,
        #     answered. The argv is exactly the reviewed `cmd.exe /c <launcher>` shape.
        with seams(_handshake=recording_handshake):
            result = rm.probe_capabilities(repo, target=str(target), check_mcp_start=True)
        check(result["capabilities"][rm.HANDSHAKE_CAPABILITY]["present"] is True,
              f"a satisfied handshake must be a present capability: {result['capabilities']}")
        check(len(started) == 1 and started[0]["argv"] == ["cmd.exe", "/c", str(launcher)],
              f"the handshake must be asked for the REVIEWED Studio launch shape: {started}")
        check(started[0]["cwd"] == str(repo), f"the handshake must run in the repository: {started}")
        check(result["handshake"]["ok"] is True and result["roblox_usable"] is True,
              f"launcher + config + handshake must be usable: {result}")
        check(rm.HANDSHAKE_CAPABILITY not in result["missing"],
              f"nothing may be missing in the green fixture: {result['missing']}")

        # 8.8 WITHOUT `check_mcp_start` no handshake capability exists, and nothing is started.
        started.clear()
        with seams(_handshake=recording_handshake):
            quiet = rm.probe_capabilities(repo, target=str(target))
        check(started == [] and rm.HANDSHAKE_CAPABILITY not in quiet["capabilities"],
              f"the Studio start must stay strictly opt-in: {quiet['capabilities']}")
        check(quiet["check_mcp_start"] is False and quiet["handshake"] is None,
              f"an opt-out probe must report no handshake: {quiet}")

    # 8.9 an undeterminable launcher means the handshake cannot even be attempted.
    def refuse_launcher():
        raise rm.UsageError("%LOCALAPPDATA% is not set on this host")

    started.clear()
    with seams(studio_batch_path=refuse_launcher, _handshake=recording_handshake):
        result = rm.probe_capabilities(repo, target=str(target), check_mcp_start=True)
    check(result["capabilities"][rm.HANDSHAKE_CAPABILITY]["present"] is False,
          f"no launcher, no handshake: {result['capabilities']}")
    check("%LOCALAPPDATA%" in result["capabilities"][rm.HANDSHAKE_CAPABILITY]["reason"],
          f"the capability must carry the reason: {result['capabilities']}")
    check(started == [], "no process may be started when the launcher is undeterminable")
    check(result["roblox_usable"] is False, f"an unusable host must never be reported usable: {result}")

    # 8.10 a launcher that is not installed means the handshake is skipped with a reason.
    absent = tmp / "probe-start" / "absent" / "Roblox" / "mcp.bat"
    absent.parent.mkdir(parents=True)
    started.clear()
    with seams(studio_batch_path=lambda: absent, _handshake=recording_handshake):
        result = rm.probe_capabilities(repo, target=str(target), check_mcp_start=True)
    check(result["capabilities"][rm.HANDSHAKE_CAPABILITY]["present"] is False
          and "cannot start" in result["capabilities"][rm.HANDSHAKE_CAPABILITY]["reason"],
          f"an absent launcher must keep the handshake off: {result['capabilities']}")
    check(started == [], "no process may be started when the launcher is absent")

    # 8.11 a handshake that FAILS is reported as such (and still never leaves the exit-0 probe).
    with seams(studio_batch_path=lambda: launcher,
               _handshake=lambda argv, cwd, budget: {"ok": False, "stage": "initialize",
                                                     "message": "no initialize response",
                                                     "tools": [], "cwd": cwd,
                                                     "command": list(argv),
                                                     "protocol_version": None, "server": None,
                                                     "exit_code": None, "stderr_tail": []}):
        failed = rm.probe_capabilities(repo, target=str(target), check_mcp_start=True)
    check(failed["capabilities"][rm.HANDSHAKE_CAPABILITY]["present"] is False,
          f"a failed handshake must be a missing capability: {failed['capabilities']}")
    check(failed["roblox_usable"] is False,
          f"a failed handshake must make the Studio path unusable: {failed['roblox_usable']}")


# --------------------------------------------------------------------- 9. CLI contract

def test_cli_contract(tmp: pathlib.Path) -> None:
    env = base_env(KIMI_CODE_HOME=str(data_root(tmp, "cli-root")))

    # 9.1 `--help` exits 0 for the program and for EVERY subcommand.
    res = run("--help", env=env)
    expect_clean_cli(res, 0, "--help")
    for name in ("decide", "merge-config", "validate-config", "probe", "scenario"):
        check(name in res.stdout, f"the top-level help must list {name}: {res.stdout!r}")
        expect_clean_cli(run(name, "--help", env=env), 0, f"{name} --help")
    for name in ("run", "verdict", "verify"):
        expect_clean_cli(run("scenario", name, "--help", env=env), 0, f"scenario {name} --help")
    res = run("scenario", "--help", env=env)
    for name in ("run", "verdict", "verify"):
        check(name in res.stdout, f"the scenario help must list {name}: {res.stdout!r}")

    # 9.2 usage errors exit 2 without a traceback — and no subcommand is silently defaulted.
    expect_clean_cli(run(env=env), 2, "no subcommand")
    expect_clean_cli(run("unknown-subcommand", env=env), 2, "unknown subcommand")
    expect_clean_cli(run("merge-config", "--nonsense", env=env), 2, "unknown merge-config option")
    expect_clean_cli(run("validate-config", env=env), 2, "validate-config without --path")
    expect_clean_cli(run("probe", env=env), 2, "probe without --repo")
    expect_clean_cli(run("scenario", env=env), 2, "scenario without a subcommand")
    expect_clean_cli(run("scenario", "run", env=env), 2, "scenario run without arguments")

    # 9.3 non-ASCII input and output survive a legacy console code page (cp1251/cp866).
    legacy = run("--help", env={**env, "PYTHONIOENCODING": "cp1251"})
    check(legacy.returncode == 0 and "Traceback" not in legacy.stderr,
          f"--help must survive a legacy code page: {legacy.stderr!r}")
    # The task text is written with `\u` escapes on purpose: this module is a tracked file under the
    # English-only rule, so it may not carry a non-ASCII literal even in a fixture.
    cyrillic = ("Roblox: \u0434\u043e\u0431\u0430\u0432\u044c \u0441\u0431\u043e\u0440 "
                "\u043c\u043e\u043d\u0435\u0442 \u0432 \u0438\u0433\u0440\u0443 \u0438 "
                "playtest \u0435\u0451 \u0432 Studio.")
    res = run("decide", "--repo", str(roblox_repo(tmp / "cli" / "coin-game")), "--text", cyrillic,
              "--json", env={**env, "PYTHONIOENCODING": "cp1251"})
    check(res.returncode == 0 and "Traceback" not in res.stderr,
          f"a non-ASCII task text must not crash the CLI: {res.stderr!r}")
    check(json.loads(res.stdout)["applicable"] is True,
          f"a non-ASCII Roblox task must still classify: {res.stdout!r}")


def test_skill_guidance() -> None:
    """10. The shipped guidance scopes the LocalScript prohibition and keeps every client container.

    Content is DATA: nothing here starts Studio or executes the skill's advice — the assertion is
    that the text an agent is handed tells the truth about which containers run a `LocalScript`.
    """
    check(GAME_SKILL.is_file(), f"the Roblox guidance must ship at {GAME_SKILL}")
    text = GAME_SKILL.read_text(encoding="utf-8")

    # 10.1 The false blanket is gone: no wording may call every LocalScript outside the character
    # dead, because that contradicts the skill's own StarterPlayerScripts/StarterGui rows.
    lowered = text.lower()
    for claim in BLANKET_CLAIMS:
        check(claim not in lowered,
              f"{GAME_SKILL}: the blanket claim {claim!r} is false - a LocalScript in "
              "StarterPlayerScripts/StarterCharacterScripts/StarterGui does run")

    # 10.2 The prohibition is a SINGLE, SCOPED statement: one paragraph says where a LocalScript
    # never runs, and it names the unsupported containers instead of generalising.
    paragraphs = [p for p in text.split("\n\n") if "never runs" in p]
    check(len(paragraphs) == 1,
          f"{GAME_SKILL}: expected exactly one paragraph stating where a LocalScript never runs, "
          f"got {len(paragraphs)}")
    paragraph = paragraphs[0]
    flat = " ".join(paragraph.split())
    sentences = [s for s in flat.split(". ") if "never runs" in s]
    check(len(sentences) == 1,
          f"{GAME_SKILL}: the prohibition must be one sentence, got {sentences!r}")
    prohibition = sentences[0]
    check(any(name in prohibition for name in UNSUPPORTED_CONTAINERS),
          f"{GAME_SKILL}: the never-runs sentence must name the unsupported container(s) "
          f"{UNSUPPORTED_CONTAINERS}: {prohibition!r}")
    check("ServerScriptService" in prohibition,
          f"{GAME_SKILL}: ServerScriptService is the core unsupported location and must be named: "
          f"{prohibition!r}")

    # 10.3 The supported client containers stay enumerated in THAT paragraph - the reader learns both
    # halves of the rule where the rule is made, and no valid client script is implied dead.
    for name in CLIENT_CONTAINERS:
        check(name in paragraph,
              f"{GAME_SKILL}: the execution-model guidance must name the supported client "
              f"container {name!r} next to the prohibition")

    # 10.4 ...and the table keeps its LocalScript rows, so a "fix" cannot delete the valid ones.
    for name in ("StarterPlayerScripts", "StarterCharacterScripts", "StarterGui"):
        rows = [line for line in text.splitlines() if line.startswith(f"| `{name}`")]
        check(len(rows) == 1, f"{GAME_SKILL}: the table must keep exactly one {name!r} row: {rows!r}")
        check("LocalScript" in rows[0],
              f"{GAME_SKILL}: the {name!r} row must keep its LocalScript marker: {rows[0]!r}")

    # 10.5 The supported client LOCATIONS are complete (review-2 finding 3): `StarterPack` is cloned
    # into the player's `Backpack` and a script also runs parented directly at runtime, so a reader
    # must learn those next to the prohibition instead of being told there are only three.
    for name in CLIENT_DESTINATIONS:
        check(name in paragraph,
              f"{GAME_SKILL}: the execution-model guidance must name the supported client "
              f"destination {name!r} next to the prohibition")

    # 10.6 ...and no wording may close the list again: an exhaustive claim sends a valid tool or
    # runtime script into a container that does not fit it.
    flat = " ".join(text.split())
    for claim in EXHAUSTIVE_CLAIMS:
        check(claim not in flat,
              f"{GAME_SKILL}: the exhaustive claim {claim!r} is false - a `StarterPack` tool is "
              "cloned into the `Backpack` and a script also runs parented directly at runtime")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        test_decide(tmp)
        test_non_roblox_repository(tmp)
        test_merge_config_default_target(tmp)
        test_merge_config_target_override(tmp)
        test_merge_preserves_unrelated_entries(tmp)
        test_merge_conflict_never_overwrites(tmp)
        test_merge_invalid_and_dry_run(tmp)
        test_validate_config(tmp)
        test_scenario_runner(tmp)
        test_stop_kills_descendants_after_launcher_exit(tmp)
        test_job_refusal_fails_closed(tmp)
        test_console_capture_precedes_teardown(tmp)
        test_scenario_verify(tmp)
        test_probe(tmp)
        test_probe_check_mcp_start(tmp)
        test_cli_contract(tmp)
        test_skill_guidance()

    print(f"PASS - roblox_mcp.py contract holds: {COUNTER['checks']} assertions over the "
          "BOTH-conditions applicability matrix (repository identity alone, task text alone and a "
          "models.roblox_expert pin alone all stay off; a standalone Studio subject counts while a "
          "documentation-bound action or a studio meaning another product/place is discarded, and "
          "the factory repository itself decides not applicable), the user-scope GLOBAL config "
          "resolved from KIMI_CODE_HOME or the home directory with an undeterminable/nonexistent "
          "data root refused and every hermetic case redirected into a temp dir, the symlink-resolved "
          "--target override with its echoed resolved path, the ONE byte-preserving idempotent merge "
          "contract (unrelated entries kept, conflicts reported with exit 3 and never overwritten, "
          "no stored value echoed, --dry-run writing nothing), the managed-entry invariants of "
          "validate-config, the scenario runner against an injected fake Studio server (structured "
          "PASS/FAIL derived from the captured console output with its sha256, a screenshot never "
          "the verdict, a PRESENT non-boolean isError (string, number, null, container) refused "
          "before any content can read as success, zero-step and out-of-range budgets refused, the "
          "bounded stop reaching a "
          "descendant whose launcher already exited, the fail-closed refusal "
          "of a host that cannot guarantee that stop, and the console capture taken BEFORE that stop "
          "so a peer's teardown noise never becomes a verdict) with its strict `scenario "
          "verify` gate, the fail-soft capability probe whose Studio handshake is strictly opt-in "
          "and seam-driven, the argparse CLI contract, and the shipped Roblox guidance that scopes the "
          "LocalScript prohibition to its unsupported containers while keeping every supported "
          "client container listed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
