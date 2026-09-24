#!/usr/bin/env python3
"""
Deterministic self-test for the Windows launchers of Code Factory (zero LLM tokens).

The Windows deployment is a family of files that must stay in sync, and none of them can be
exercised by importing a module, so this pins them structurally AND end to end:

  - `prepare_factory.cmd` — the double-clickable entry point: finds PowerShell, forwards every
    argument to `prepare_factory.ps1`, propagates its exit code and prints the usage line. It
    must pause ONLY on a double-click (an unconditional `pause` would hang any automated run),
  - `prepare_factory.ps1` — the real deployer (PowerShell 5.1). It carries INLINE templates of
    `start.cmd` (CRLF) and of `start.sh` (LF) and writes both into the target project,
  - `start.cmd` — the Windows launcher it writes, committed at the repo root as the source of
    truth (the generated file must be byte-identical to it),
  - `prepare_factory.sh` — the bash deployer, which owns the `start.sh` here-doc and must stay
    untouched by the Windows work.

Verified here:
  1. existence, encoding (BOM only in the .ps1) and CRLF-only line endings (no lone CR/LF),
  2. the `prepare_factory.cmd` contract (PowerShell flags, argument forwarding, exit code,
     usage string) and that its `pause` really is guarded by the double-click detection,
  3. the `start.cmd` contract and its exact first line (`@echo off`),
  4. anti-drift: the inline `start.cmd` template in the .ps1 == the committed `start.cmd`,
  5. anti-drift: the inline `start.sh` template in the .ps1 == the here-doc of `prepare_factory.sh`,
  6. `prepare_factory.sh` was NOT touched (it must not mention `start.cmd` at all),
  7. `.gitattributes` pins `*.cmd`/`*.ps1` to CRLF at checkout, so the CRLF-only checks above
     hold on a clone with `core.autocrlf=false` too (never an LF-only checked-out launcher), and
     pins `*.sh` to LF — the bash deployer is an LF file and the deployer writes `start.sh` as LF,
  8. end-to-end (Windows only, otherwise SKIPPED): `cmd.exe /c prepare_factory.cmd <fresh tmp>`
     into two fresh target paths — one with a space, one with non-ASCII characters — a real
     deployment each, then a second run to prove idempotency (existing project memory is never
     overwritten) and that the project name Python reported back is not mangled,
  9. the deployers' FAILURE paths stay business-like: the `.ps1` `Copy-Item` fallback turns a copy
     failure into a message via `Err` plus the hard-error flag (never raw PowerShell records), and
     a failed memory init in the `.sh` is reported as the short reason — the last non-empty line of
     the output — never as a dump of the whole output (a traceback).

A project deployed by the factory contains only `.agents/` (plus the generated launchers), so
there this test SKIPs cleanly instead of failing on a missing factory repo root.

Exit code 0 = every check passed (skips are fine), 1 = at least one check failed.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable

BOM = b"\xef\xbb\xbf"

SCRIPTS = pathlib.Path(__file__).resolve().parent

PS1_NAME = "prepare_factory.ps1"
CMD_NAME = "prepare_factory.cmd"
START_CMD_NAME = "start.cmd"
SH_NAME = "prepare_factory.sh"

GITATTRIBUTES_NAME = ".gitattributes"
# Pinned at checkout whatever the machine's core.autocrlf says: an LF-only `*.cmd`/`*.ps1`
# working copy is a broken launcher, and the CRLF-only checks below only hold if the checkout
# forced CRLF (a clone with core.autocrlf=false would otherwise hand out LF).
EOL_PINS = ("*.cmd text eol=crlf", "*.ps1 text eol=crlf")
# The bash side is pinned the other way round: bash scripts are LF files, and the deployer itself
# writes start.sh with LF, so a CRLF checkout would only diverge from what the deployer produces.
SH_EOL_PIN = "*.sh text eol=lf"

# Deployment-failure markers, pinned by name (this file never hard-codes a line number).
PS1_COPY_FUNCTION = "Copy-FactoryTree"
# The fallback branch itself: the recursive copy of every top-level entry, and the SAME Copy-Item
# invocation with the failure turned terminating - the flag has to sit ON the call, so a comment
# that merely mentions it does not satisfy the check (comments are dropped before matching).
PS1_FALLBACK_TOKENS = ("Get-ChildItem -LiteralPath $Source -Force",
                       "Copy-Item -LiteralPath $_.FullName -Destination $Destination "
                       "-Recurse -Force -ErrorAction Stop",
                       "$script:HardError = $true",
                       'Err "')
SH_MEM_FAIL_MARKER = "Project memory: failed to create"
# The reason shown for a failed init must be the LAST NON-EMPTY line of the output: the whole
# blob (an interpreter traceback) drowns the actual message, the exception line does not.
SH_REASON_TOKENS = ("$MEM_INIT_OUT", "awk", "NF", "END", "print last")

# The Windows deployer must produce exactly these files in a fresh project.
CREATED_RELS = (
    ".agents/skills/code-factory/SKILL.md",
    "memory/change-log.md",
    "memory/summary.md",
    ".gitignore",
    ".git",
    "start.cmd",
    "start.sh",
)
MEMORY_RELS = ("memory/change-log.md", "memory/summary.md")
GITIGNORE_PATTERNS = (".agents/", ".code-factory/", "__pycache__/", "*.pyc",
                      ".env", ".env.*", "*.env", "*.pem", "*.key")

CMD_USAGE = "Usage: prepare_factory.cmd <path-to-project>"
PS_INVOCATION = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_factory.ps1" %*'

CMD_TOKENS = ("chcp 65001", "-NoProfile", "-ExecutionPolicy Bypass", "-File",
              "%~dp0prepare_factory.ps1", "%*", "exit /b")
START_CMD_TOKENS = ("chcp 65001", 'cd /d "%~dp0"',
                    "set KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1",
                    "where kimi", "kimi %*", "exit /b")


REPO_FILES = (PS1_NAME, CMD_NAME, SH_NAME, START_CMD_NAME)


def find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    """The deployment root: the one directory holding the .ps1/.cmd/.sh deployer + start.cmd.

    `None` when there is none - a project deployed BY the factory receives only `.agents/` plus
    the generated launchers, so these files are absent there and the test cannot run (main()
    reports that as a SKIP instead of a failure).
    """
    for path in (start, *start.parents):
        if all((path / name).is_file() for name in REPO_FILES):
            return path
    return None


FOUND_REPO = find_repo_root(SCRIPTS)      # None inside a project deployed by the factory
REPO = FOUND_REPO or SCRIPTS              # keep the module-level paths defined for the summary
PS1 = REPO / PS1_NAME
CMD = REPO / CMD_NAME
START_CMD = REPO / START_CMD_NAME
SH = REPO / SH_NAME
GITATTRIBUTES = REPO / GITATTRIBUTES_NAME


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def read_text(path: pathlib.Path) -> str:
    """UTF-8 text of a file, with a possible BOM stripped."""
    return path.read_bytes().decode("utf-8-sig")


def normalize_newlines(text: str) -> str:
    """Compare-ready form: no BOM, LF only, no trailing newline noise."""
    return text.lstrip("\ufeff").replace("\r\n", "\n").rstrip("\n")


def check_text_file(path: pathlib.Path, *, bom: bool, crlf_only: bool = True) -> str:
    """Existence, UTF-8 validity, BOM presence/absence and line endings.

    `crlf_only=True` (the Windows files) demands that every `\\r` and every `\\n` belongs to a
    `\\r\\n` pair. The bash deployer is checked with `crlf_only=False` instead: its canonical state
    is LF-only (`.gitattributes` pins `*.sh` to `eol=lf`), but a checkout with `core.autocrlf=true`
    still hands it out with CRLF - both whole-file states are fine, a file with MIXED line endings
    never is.
    """
    expect(path.is_file(), f"{path} must exist")
    data = path.read_bytes()
    if bom:
        expect(data.startswith(BOM),
               f"{path.name} must start with the UTF-8 BOM (EF BB BF), got {data[:3]!r}")
    else:
        expect(not data.startswith(BOM),
               f"{path.name} must NOT start with a BOM (cmd.exe would choke on it), got {data[:3]!r}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionError(f"{path.name} must be valid UTF-8: {exc}") from None
    # A lone \r is never right: it is not a line ending on its own, in any of these files.
    expect(text.count("\r\n") == text.count("\r"),
           f"{path.name} has a lone CR (not part of CRLF): {text.count(chr(13))} CR vs "
           f"{text.count(chr(13) + chr(10))} CRLF")
    if crlf_only:
        expect(text.count("\r\n") == text.count("\n"),
               f"{path.name} has a lone LF (not part of CRLF): {text.count(chr(10))} LF vs "
               f"{text.count(chr(13) + chr(10))} CRLF")
    else:
        crlf, lf = text.count("\r\n"), text.count("\n")
        expect(crlf == 0 or crlf == lf,
               f"{path.name} mixes line endings: {crlf} CRLF vs {lf} LF - a file is either all LF "
               "(what `.gitattributes` pins) or all CRLF (what core.autocrlf=true checks out), "
               "never a mix")
    return text


# --- PowerShell template extraction (no line numbers hard-coded anywhere) ------------------

_PS_ARRAY_HEAD = re.compile(r"^\s*\$\w+\s*=\s*@\(\s*$")
_PS_ARRAY_TAIL = re.compile(r"^\s*\)\s*$")
_PS_SQ_ELEMENT = re.compile(r"^\s*'((?:[^']|'')*)'\s*,?\s*$")
_PS_HERE_HEAD = re.compile(r"^\s*@(['\"])\s*$")
_PS_HERE_TAIL = re.compile(r"^\s*['\"]@\s*$")


def ps_string_arrays(text: str) -> list[list[str]]:
    """Every `$name = @( 'a', 'b' )` literal in `text`, as a list of its string elements.

    A block whose elements are not all plain single-quoted strings (nested expressions, code)
    is skipped entirely, so unrelated arrays in the script never produce a bogus template.
    """
    lines = text.splitlines()
    out: list[list[str]] = []
    i = 0
    while i < len(lines):
        if not _PS_ARRAY_HEAD.match(lines[i]):
            i += 1
            continue
        j = i + 1
        items: list[str] | None = []
        while j < len(lines) and not _PS_ARRAY_TAIL.match(lines[j]):
            match = _PS_SQ_ELEMENT.match(lines[j])
            if match is None:
                items = None
                break
            items.append(match.group(1).replace("''", "'"))
            j += 1
        if items:
            out.append(items)
        i = j + 1
    return out


def ps_here_strings(text: str) -> list[list[str]]:
    """Every PowerShell here-string (`@' ... '@`, `@" ... "@`) in `text`, line by line."""
    lines = text.splitlines()
    out: list[list[str]] = []
    i = 0
    while i < len(lines):
        if not _PS_HERE_HEAD.match(lines[i]):
            i += 1
            continue
        body: list[str] = []
        j = i + 1
        while j < len(lines) and not _PS_HERE_TAIL.match(lines[j]):
            body.append(lines[j])
            j += 1
        if j < len(lines):
            out.append(body)
        i = j + 1
    return out


def ps_function_body(text: str, name: str) -> list[str]:
    """The lines inside `function <name> {`, brace-counted (the body may contain `{ ... }` blocks).

    Braces inside strings or comments would confuse the counter, so this stays limited to the
    functions pinned here - none of them contains one.
    """
    lines = text.splitlines()
    head = re.compile(r"^\s*function\s+" + re.escape(name) + r"\s*\{\s*$")
    for i, line in enumerate(lines):
        if not head.match(line):
            continue
        body: list[str] = []
        depth = 1
        for later in lines[i + 1:]:
            depth += later.count("{") - later.count("}")
            if depth == 0:
                return body
            body.append(later)
        raise AssertionError(f"{PS1_NAME}: function {name} is never closed")
    raise AssertionError(f"{PS1_NAME} has no `function {name} {{` definition")


def extract_ps_template(text: str, first_line: str) -> list[str]:
    """The launcher template inlined in the .ps1 whose first line is exactly `first_line`.

    Both shapes are recognised (a single-quoted here-string and a single-quoted string array),
    so a future refactor of the script keeps working — only the template content is pinned.
    """
    for body in ps_here_strings(text) + ps_string_arrays(text):
        if body and body[0] == first_line:
            return body
    raise AssertionError(
        f"{PS1_NAME} has no inline template starting with {first_line!r} "
        "(expected a single-quoted here-string `@'...'@` or a string array `@( '...' )`)")


def extract_heredoc(text: str, marker: str) -> list[str]:
    """The body of the `<<'EOF'` / `<<EOF` here-document terminated by `marker`."""
    lines = text.splitlines()
    opener = re.compile(r"<<-?\s*'?\"?([A-Za-z_][A-Za-z0-9_]*)'?\"?\s*$")
    for i, line in enumerate(lines):
        match = opener.search(line)
        if not match or match.group(1) != marker:
            continue
        body: list[str] = []
        for later in lines[i + 1:]:
            if later.strip() == marker:
                return body
            body.append(later)
        raise AssertionError(f"{SH_NAME}: here-doc <<{marker}> is never terminated")
    raise AssertionError(f"{SH_NAME} has no <<{marker} here-document")


def describe_diff(expected: list[str], actual: list[str],
                  expected_name: str, actual_name: str) -> str:
    """A short, explicit drift report pointing at the first differing line."""
    if len(expected) != len(actual):
        head = f"line count differs: {expected_name} has {len(expected)}, {actual_name} has {len(actual)}"
    else:
        head = f"line count matches ({len(expected)} lines)"
    for number, (left, right) in enumerate(zip(expected, actual), 1):
        if left != right:
            return (f"{head}; first difference on line {number}:\n"
                    f"  {expected_name}: {left!r}\n"
                    f"  {actual_name}: {right!r}")
    return head


# --- individual static checks ----------------------------------------------------------------


def prepare_cmd_contract() -> None:
    text = check_text_file(CMD, bom=False)
    for token in CMD_TOKENS:
        expect(token in text, f"{CMD_NAME} must contain {token!r}")
    expect(PS_INVOCATION in text,
           f"{CMD_NAME} must launch the deployer exactly as {PS_INVOCATION!r}")
    # cmd.exe prints the usage line; `<>` are caret-escaped in batch, so compare unescaped.
    unescaped = text.replace("^<", "<").replace("^>", ">")
    expect("echo " + CMD_USAGE in unescaped,
           f"{CMD_NAME} must print {CMD_USAGE!r}")


def prepare_cmd_pause_guard() -> None:
    text = check_text_file(CMD, bom=False)
    lines = text.splitlines()
    pauses = [i for i, line in enumerate(lines) if line.strip() == "pause"]
    expect(pauses, f"{CMD_NAME} must still pause on a double-click (no 'pause' line found)")
    guards = [i for i, line in enumerate(lines) if "%cmdcmdline%" in line]
    expect(guards, f"{CMD_NAME}: 'pause' is unguarded - no %cmdcmdline% double-click detection; "
                   "an unconditional pause hangs automated runs")
    guard = guards[0]
    for index in pauses:
        expect(index > guard,
               f"{CMD_NAME}: 'pause' on line {index + 1} comes BEFORE the %cmdcmdline% guard on "
               f"line {guard + 1}: it would hang an automated run")
    expect(any("goto :no_pause" in line for line in lines[guard:pauses[0]]),
           f"{CMD_NAME}: the double-click guard must jump over the pause (`goto :no_pause`)")
    expect(any(line.strip().startswith(":no_pause") for line in lines[pauses[-1]:]),
           f"{CMD_NAME}: the :no_pause label must follow the pause")
    # Second half of the double-click test: timeout.exe fails on redirected input, so an
    # automated run (stdin=DEVNULL) also skips the pause.
    expect(any("timeout.exe" in line for line in lines[guard:pauses[0]]),
           f"{CMD_NAME}: the guard must also check that stdin is an interactive console "
           "(timeout.exe refuses redirected input) before pausing")


def start_cmd_contract() -> None:
    text = check_text_file(START_CMD, bom=False)
    first = text.splitlines()[0] if text.splitlines() else ""
    expect(first == "@echo off",
           f"{START_CMD_NAME} must start with exactly '@echo off', got {first!r}")
    for token in START_CMD_TOKENS:
        expect(token in text, f"{START_CMD_NAME} must contain {token!r}")


def antidrift_start_cmd() -> None:
    template = extract_ps_template(read_text(PS1), "@echo off")
    actual = normalize_newlines(read_text(START_CMD)).split("\n")
    expect(template == actual,
           "the inline start.cmd template in " + PS1_NAME + " drifted from " + START_CMD_NAME
           + ": " + describe_diff(template, actual, "template in " + PS1_NAME, START_CMD_NAME))


def antidrift_start_sh() -> None:
    template = extract_ps_template(read_text(PS1), "#!/usr/bin/env bash")
    heredoc = extract_heredoc(read_text(SH), "EOF")
    expect(template == heredoc,
           "the inline start.sh template in " + PS1_NAME + " drifted from the here-doc in "
           + SH_NAME + ": " + describe_diff(template, heredoc, "template in " + PS1_NAME + " (start.sh)",
                                            "here-doc in " + SH_NAME))


def bash_deployer_untouched() -> None:
    text = check_text_file(SH, bom=False, crlf_only=False)
    expect("start.cmd" not in text,
           f"{SH_NAME} must not mention start.cmd: the Windows work must leave the bash "
           "deployer untouched")
    expect(extract_heredoc(text, "EOF")[0] == "#!/usr/bin/env bash",
           f"{SH_NAME}: the start.sh here-doc must still start with the bash shebang")


def bash_memory_failure_is_short() -> None:
    """A failed `memory_project.py init` must be reported by its REASON, not by its whole output.

    The deployer deliberately stays non-fatal there (the factory creates the memory on first use),
    so the one warning line is all the user sees: dumping the raw output puts a Python traceback
    into it, where the exception line alone says what went wrong.
    """
    text = check_text_file(SH, bom=False, crlf_only=False)
    fail_lines = [line for line in text.splitlines() if SH_MEM_FAIL_MARKER in line]
    expect(fail_lines, f"{SH_NAME} must still warn when the memory init fails")
    for line in fail_lines:
        expect("MEM_INIT_OUT" not in line,
               f"{SH_NAME}: the failure warning must not interpolate the whole init output "
               f"($MEM_INIT_OUT) - that is what puts a traceback there; got {line.strip()!r}")
    reason_lines = [line for line in text.splitlines() if "$MEM_INIT_OUT" in line and "awk" in line]
    expect(reason_lines,
           f"{SH_NAME} must derive a short reason from the init output "
           "(awk 'NF{last=$0}END{print last}' over $MEM_INIT_OUT)")
    for line in reason_lines:
        missing = [token for token in SH_REASON_TOKENS if token not in line]
        expect(not missing,
               f"{SH_NAME}: the reason must be the LAST NON-EMPTY line of the init output "
               f"(missing {missing}); got {line.strip()!r}")
        name = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)=", line)
        expect(name is not None,
               f"{SH_NAME}: the short reason must be stored in a variable, got {line.strip()!r}")
        expect(any("${" + name.group(1) + "}" in fail or "${" + name.group(1) + ":-" in fail
                   for fail in fail_lines),
               f"{SH_NAME}: the failure warning must show the short reason "
               f"(${{{name.group(1)}}}...), got {fail_lines[0].strip()!r}")


def ps1_copy_fallback_is_guarded() -> None:
    """The non-robocopy fallback must turn a copy failure into a business message + exit 1.

    `Copy-Item` fails NON-terminating: outside a try/catch it prints raw engine records
    (CategoryInfo, FullyQualifiedErrorId) and the deployer would still end with the "Done"
    banner and exit 0 for a half-copied `.agents/` tree - the contract there is exit 1 and no banner.
    """
    body = ps_function_body(check_text_file(PS1, bom=True), PS1_COPY_FUNCTION)
    # Comments are dropped first: a comment that only *mentions* a token must not satisfy the pin.
    code = "\n".join(line for line in body if not line.lstrip().startswith("#"))
    for token in PS1_FALLBACK_TOKENS:
        expect(token in code, f"{PS1_NAME}: {PS1_COPY_FUNCTION} must contain {token!r}")
    positions = (code.find("try {"), code.find("Get-ChildItem -LiteralPath $Source -Force"),
                 code.find("catch {"))
    expect(-1 not in positions and positions[0] < positions[1] < positions[2],
           f"{PS1_NAME}: the fallback must sit in a try/catch "
           f"(`try {{` ... Get-ChildItem ... `}} catch {{`), got offsets {positions}")


def gitattributes_rules() -> set[str]:
    """Every rule line of .gitattributes (comments and blanks dropped, CRLF-agnostic)."""
    expect(GITATTRIBUTES.is_file(),
           f"{GITATTRIBUTES.name} must exist: it is what pins the deployer files' line endings")
    # splitlines() drops the CRLF terminator of a CRLF working copy as well - git strips that CR
    # itself, so the pins hold whether or not this machine rewrote the checkout.
    return {line.strip() for line in read_text(GITATTRIBUTES).splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def gitattributes_pins_crlf() -> None:
    """The CRLF-only checks above must hold on ANY clone, not just one with core.autocrlf=true.

    Without the pin, git hands the launchers out with LF where core.autocrlf=false, and LF-only
    .cmd/.ps1 files are broken (cmd.exe and PowerShell 5.1 both expect CRLF).
    """
    lines = gitattributes_rules()
    missing = [pin for pin in EOL_PINS if pin not in lines]
    expect(not missing,
           f"{GITATTRIBUTES.name} must contain {missing} - without the pin a clone with "
           "core.autocrlf=false checks the .cmd/.ps1 launchers out with LF, which no Windows "
           "shell can run")


def gitattributes_pins_sh_lf() -> None:
    """The bash side is pinned the other way round, for the mirrored reason.

    `*.sh` is checked out with CRLF wherever core.autocrlf=true, which is not what the deployer
    produces (it writes `start.sh` with LF) and not what bash expects: a CRLF shebang is a broken
    script, and the CRLF blob would follow the file into the repository.
    """
    lines = gitattributes_rules()
    expect(SH_EOL_PIN in lines,
           f"{GITATTRIBUTES.name} must contain {SH_EOL_PIN!r} - without the pin *.sh arrives with "
           "CRLF wherever core.autocrlf=true, so a Windows checkout diverges from the LF start.sh "
           "the deployer writes")


# --- end-to-end deployment (Windows only) -----------------------------------------------------


def sha256_or_none(path: pathlib.Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_bytes_or_none(path: pathlib.Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def tail(text: str | None, limit: int = 1200) -> str:
    body = (text or "").strip()
    if not body:
        return "(no output)"
    return body if len(body) <= limit else "(truncated) ...\n" + body[-limit:]


def find_cmd_exe() -> str | None:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    native = pathlib.Path(system_root) / "System32" / "cmd.exe"
    if native.is_file():
        return str(native)
    return shutil.which("cmd.exe") or shutil.which("cmd")


def find_powershell() -> str | None:
    found = shutil.which("powershell.exe") or shutil.which("powershell")
    if found:
        return found
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    native = pathlib.Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(native) if native.is_file() else None


def remove_tree(path: pathlib.Path) -> None:
    """Best-effort removal of the temp deployment (git can leave read-only objects behind)."""
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.chmod(pathlib.Path(root) / name, stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        print(f"WARNING - could not remove the temporary deployment directory {path}")


def deploy(cmd_exe: str, target: pathlib.Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    """`cmd.exe /c prepare_factory.cmd <target>` - what a double-click does, minus stdin.

    `cmd.exe` has no absolute cmd.exe path in the command line: the script is named relatively
    (the process runs in the repo root), because cmd.exe strips the quotes around a quoted first
    token and would then fail if the factory path itself contained a space. The spaced TARGET is
    still passed as its own list element, so subprocess quotes it for us - that is the quoting
    the deployer has to survive.
    """
    return subprocess.run(
        [cmd_exe, "/c", CMD_NAME, str(target)],   # a LIST: subprocess quotes the spaced target
        cwd=str(REPO),                            # the deployer is run from the factory repo root
        stdin=subprocess.DEVNULL,                 # must never wait for a keypress
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def collect_deployment_facts(cmd_exe: str, target: pathlib.Path) -> dict:
    """Deploy twice into `target` and return plain values only (nothing left open for cleanup)."""
    facts: dict = {"target": str(target)}
    started = time.monotonic()
    first = deploy(cmd_exe, target)
    facts["run1_rc"] = first.returncode
    facts["run1_output"] = (first.stdout or "") + (first.stderr or "")
    facts["created"] = {rel: (target / rel).exists() for rel in CREATED_RELS}
    gitignore = target / ".gitignore"
    facts["gitignore_text"] = (gitignore.read_text(encoding="utf-8", errors="replace")
                               if gitignore.is_file() else "")
    facts["start_cmd_bytes"] = read_bytes_or_none(target / "start.cmd")
    facts["start_sh_bytes"] = read_bytes_or_none(target / "start.sh")
    facts["hashes_run1"] = {rel: sha256_or_none(target / rel) for rel in MEMORY_RELS}
    second = deploy(cmd_exe, target)
    facts["run2_rc"] = second.returncode
    facts["run2_output"] = (second.stdout or "") + (second.stderr or "")
    facts["hashes_run2"] = {rel: sha256_or_none(target / rel) for rel in MEMORY_RELS}
    facts["seconds"] = time.monotonic() - started
    return facts


# Every target path is deployed for real. The space proves the argument forwarding quotes the
# target; the non-ASCII name proves the child Python processes run in UTF-8 - in the local code
# page (cp1251) the project name they print back is garbled, or the print fails outright for a
# character outside cp1251.
DEPLOY_CASES = (
    ("space in the path", "cf windows deploy "),
    ("non-ASCII in the path", "cf déploiement 部署 "),
)


def deploy_case(checker: "Checker", cmd_exe: str, case: str, prefix: str) -> None:
    """Deploy twice into a fresh temp dir and run the end-to-end checks against it."""
    temp_root = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    facts: dict = {"target": str(temp_root)}
    try:
        facts = collect_deployment_facts(cmd_exe, temp_root)
    except Exception as exc:                     # timeout, missing binary, permission, ...
        facts["error"] = exc
    finally:
        remove_tree(temp_root)                   # never leave temp dirs behind, not even on failure

    if "error" in facts:
        print(f"INFO - end-to-end deployment never completed: {facts['error']!r}")
    else:
        print(f"INFO - end-to-end deployment [{case}]: prepare_factory.cmd ran twice in "
              f"{facts['seconds']:.1f}s against {facts['target']!r}")

    def fact(key: str):
        if "error" in facts:
            raise AssertionError(f"the deployment run never completed: {facts['error']!r}")
        return facts[key]

    def check(label: str, run: Callable[[], object]) -> None:
        checker.check(f"end-to-end [{case}]: {label}", run)

    check("'cmd.exe /c prepare_factory.cmd <target>' (stdin closed) exits 0",
          lambda: expect(fact("run1_rc") == 0,
                         f"exit code {fact('run1_rc')}, expected 0 (a 'pause' would have hung until "
                         f"the timeout); output tail:\n{tail(facts.get('run1_output'))}"))

    def artifacts() -> None:
        created = fact("created")
        for rel in CREATED_RELS:
            expect(created.get(rel), f"the deployment must create {rel}")
        text = fact("gitignore_text")
        absent = [pattern for pattern in GITIGNORE_PATTERNS if pattern not in text]
        expect(not absent,
               f".gitignore must contain all 9 factory patterns (missing {absent}); got:\n"
               f"{tail(text)}")

    check("the deployed project has SKILL.md, memory/, .gitignore (9 patterns), .git/, "
          "start.cmd, start.sh", artifacts)

    def generated_start_cmd() -> None:
        data = fact("start_cmd_bytes")
        expect(data is not None, "the deployment must create start.cmd")
        reference = START_CMD.read_bytes()
        expect(data == reference,
               f"the generated start.cmd must be byte-identical to {START_CMD_NAME}: "
               f"{len(data)} bytes vs {len(reference)} bytes, "
               f"first difference at {next((i for i, (a, b) in enumerate(zip(data, reference)) if a != b), 'n/a')}; "
               f"generated head {data[:40]!r} vs reference head {reference[:40]!r}")

    check("the generated start.cmd is byte-identical to repo/start.cmd", generated_start_cmd)

    def generated_start_sh() -> None:
        data = fact("start_sh_bytes")
        expect(data is not None, "the deployment must create start.sh")
        expect(b"\r" not in data,
               f"the generated start.sh must use LF only, but contains "
               f"{data.count(bytes([13]))} CR byte(s)")
        expect(data.startswith(b"#!/usr/bin/env bash"),
               f"the generated start.sh must start with the bash shebang, got {data[:26]!r}")

    check("the generated start.sh is LF-only and starts with the bash shebang", generated_start_sh)

    def idempotent() -> None:
        expect(fact("run2_rc") == 0,
               f"the second run must exit 0, got {fact('run2_rc')}; output tail:\n"
               f"{tail(facts.get('run2_output'))}")
        before, after = fact("hashes_run1"), fact("hashes_run2")
        for rel in MEMORY_RELS:
            expect(before[rel] is not None, f"{rel} must exist after the first run")
            expect(before[rel] == after[rel],
                   f"the second run rewrote {rel} (SHA256 {before[rel]} -> {after[rel]}); "
                   "existing project memory must never be overwritten")

    check("the second run exits 0 and both memory files keep their SHA256 (idempotent)", idempotent)

    def memory_name_reported() -> None:
        """The deployer must read Python's output back as UTF-8, not as mojibake.

        With a target path the child Python cannot encode, the deployer reports a failure the
        moment the memory is fine - so the readiness line, the project name and the absence of
        failure markers are all pinned here.
        """
        output = fact("run1_output")
        expect("failed to create" not in output,
               "the memory step reported a failure although Python is available (a child Python "
               "that cannot encode the project name looks exactly like this); output tail:\n"
               f"{tail(output)}")
        expect("MISSING" not in output,
               f"the deployment reported a missing artifact; output tail:\n{tail(output)}")
        match = re.search(r"•\s*memory/:\s+created ✓ \(project (.+)\)", output)
        expect(match is not None,
               "the readiness report must show the memory as 'created ✓ (project <name>)'; "
               f"output tail:\n{tail(output)}")
        expect(match.group(1) == temp_root.name,
               f"the project name Python reported back must be {temp_root.name!r}, got "
               f"{match.group(1)!r}: the child Python did not write UTF-8 (PYTHONUTF8), so its "
               "output was decoded as mojibake")

    check("the memory step is reported as created and Python's project name survives as UTF-8",
          memory_name_reported)


def end_to_end(checker: "Checker") -> None:
    label = "end-to-end deployment (Windows only: cmd.exe + PowerShell + git)"
    if os.name != "nt":
        checker.skip(label, f"os.name={os.name!r} - the .cmd/.ps1 deployer only runs on Windows")
        return
    cmd_exe = find_cmd_exe()
    missing = [name for name, found in (("cmd.exe", cmd_exe),
                                        ("powershell.exe", find_powershell()),
                                        ("git", shutil.which("git"))) if not found]
    if missing:
        checker.skip(label, "not available on this machine: " + ", ".join(missing))
        return

    for case, prefix in DEPLOY_CASES:
        deploy_case(checker, cmd_exe, case, prefix)


# --- runner -----------------------------------------------------------------------------------


class Checker:
    """One PASS/FAIL/SKIP line per logical check; a failure never aborts the remaining checks."""

    def __init__(self) -> None:
        self.passed = 0
        self.skipped = 0
        self.failed: list[tuple[str, str]] = []

    def check(self, label: str, run: Callable[[], object]) -> None:
        try:
            run()
        except AssertionError as exc:
            self._fail(label, str(exc) or "assertion failed")
        except Exception as exc:          # infrastructure trouble is still just one failed check
            self._fail(label, f"{type(exc).__name__}: {exc}")
        else:
            self.passed += 1
            print(f"PASS - {label}")

    def _fail(self, label: str, message: str) -> None:
        self.failed.append((label, message))
        print(f"FAIL - {label}")
        for line in message.splitlines() or [""]:
            print(f"       {line}")

    def skip(self, label: str, reason: str) -> None:
        self.skipped += 1
        print(f"SKIP - {label} ({reason})")

    def finish(self) -> int:
        print("")
        print(f"SUMMARY - {self.passed} PASS, {len(self.failed)} FAIL, {self.skipped} SKIP "
              f"(repo {REPO})")
        for label, message in self.failed:
            print(f"  FAILED: {label}")
            print(f"          {message.splitlines()[0] if message.splitlines() else ''}")
        if self.failed:
            print(f"FAIL - Windows launcher scripts: {len(self.failed)} check(s) failed.")
            return 1
        print("PASS - Windows launcher scripts behave as expected (encoding, .cmd/.ps1 contracts, "
              "CRLF pinned in .gitattributes, no drift in the inline start.cmd/start.sh templates, "
              "real deployment idempotent).")
        return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so non-ASCII text survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251), which would replace the
    deployer's non-ASCII messages in failure reports with question marks - the .ps1 itself does
    the same thing for the same reason.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    checker = Checker()

    if FOUND_REPO is None:
        # A project deployed by the factory holds .agents/ + the generated launchers, never the
        # deployer itself: nothing to pin here, so this is a SKIP (exit 0), not a false red.
        checker.skip("all Windows launcher checks",
                     f"the factory repo root was not found above {SCRIPTS} "
                     f"({', '.join(REPO_FILES)} must live in one directory) - this looks like a "
                     "project deployed by the factory, not the factory repo itself")
        return checker.finish()

    # 1. Existence, encoding, CRLF-only line endings.
    checker.check("prepare_factory.ps1: exists, UTF-8 with BOM, decodes as UTF-8, CRLF-only",
                  lambda: check_text_file(PS1, bom=True))
    checker.check("prepare_factory.cmd: exists, no BOM, decodes as UTF-8, CRLF-only",
                  lambda: check_text_file(CMD, bom=False))
    checker.check("start.cmd: exists, no BOM, decodes as UTF-8, CRLF-only",
                  lambda: check_text_file(START_CMD, bom=False))

    # 2. prepare_factory.cmd contract + guarded pause.
    checker.check("prepare_factory.cmd: contract (chcp, PowerShell flags, arg forwarding, "
                  "exit /b, usage string)", prepare_cmd_contract)
    checker.check("prepare_factory.cmd: the pause is guarded by the double-click detection "
                  "(never unconditional)", prepare_cmd_pause_guard)

    # 3. start.cmd contract.
    checker.check("start.cmd: contract (chcp, cd /d, KIMI_CODE_EXPERIMENTAL_SECONDARY_MODEL=1, "
                  "where kimi, kimi %*, exit /b) + first line '@echo off'", start_cmd_contract)

    # 4./5. Anti-drift guards for the two inlined launcher templates.
    checker.check("anti-drift: the inline start.cmd template in prepare_factory.ps1 == repo/start.cmd",
                  antidrift_start_cmd)
    checker.check("anti-drift: the inline start.sh template in prepare_factory.ps1 == the here-doc "
                  "in prepare_factory.sh", antidrift_start_sh)

    # 6. The bash deployer must be untouched.
    checker.check("prepare_factory.sh: untouched (no mention of start.cmd, here-doc intact)",
                  bash_deployer_untouched)

    # 7. The checkout itself must hand these files over with the right line endings, on any machine.
    checker.check(".gitattributes: pins *.cmd/*.ps1 to CRLF at checkout (any core.autocrlf)",
                  gitattributes_pins_crlf)
    checker.check(".gitattributes: pins *.sh to LF at checkout (any core.autocrlf)",
                  gitattributes_pins_sh_lf)

    # 8. Failure paths of both deployers: business message, honest exit code, no raw dumps.
    checker.check("prepare_factory.ps1: the Copy-Item fallback is in a try/catch (-ErrorAction "
                  "Stop, Err + $HardError, exit 1 without the banner)", ps1_copy_fallback_is_guarded)
    checker.check("prepare_factory.sh: a failed memory init is reported as a short reason "
                  "(last non-empty line, no raw output)", bash_memory_failure_is_short)

    # 9. Real deployment (Windows only).
    end_to_end(checker)

    return checker.finish()


if __name__ == "__main__":
    sys.exit(main())
