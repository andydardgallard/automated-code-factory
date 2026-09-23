#!/usr/bin/env python3
"""
Verified acceptance for the Code Factory (anti-tautology, zero LLM tokens).

Turns acceptance criteria into a machine-checked artifact: every criterion MAY carry a `verify`
command; the command is executed for real, and its exit code plus an output excerpt land in
`acceptance.md`. Criteria without `verify` are UNVERIFIED and labeled `derived` (inferred from
other artifacts) or `unverified`, so the report never claims proof it does not have.

Input (JSON — the main agent builds it from task.yaml, since stdlib has no YAML parser):
  [{"criterion": "...", "verify": "python -m pytest -q", "derived": true}, ...]
  `verify` and `derived` are optional; `derived` defaults to false.

Verdict (SUCCESS is the only accepted outcome):
  SUCCESS  — at least one criterion carries `verify`, ALL of them are MET, the regression baseline
             is proven (`--regression pass`), and — when `--ledger` is given — the ledger holds
             FRESH `regression=pass` evidence.
  DEGRADED — nothing failed, but the baseline is not proven (`--regression not-run`), no criterion
             carries a `verify` command (nothing was actually verified), or the evidence ledger is
             STALE / has no FRESH `regression=pass` entry (stale evidence downgrades an otherwise
             SUCCESS run, even with `--regression pass`).
  FAILURE  — any verify criterion FAILED, or `--regression fail`.

Exit code 0 only for SUCCESS, so a degraded or degenerate run can never be accepted silently.

Command execution: `shell=True` is intentional — the commands are authored by the task owner
(task.yaml), not by untrusted input, and they run with `cwd=<repo>`. On Windows they are executed
by cmd.exe, on POSIX by /bin/sh: for portable tasks keep `verify` free of shell-specific syntax.
`--timeout` (default 600s, 0 = unlimited) kills the whole timed-out process tree and marks the
criterion FAILED, so a hung command can never block the gate.

Usage:
  python verify_acceptance.py --input criteria.json --output acceptance.md --repo . \\
         [--regression pass|fail|not-run] [--timeout 600] [--run-id 20260922-442cd2f8] \\
         [--ledger state/evidence.json --evidence-files src/a.py src/b.py]

`--ledger`/`--evidence-files` are optional and off by default: when given, the ledger is
re-checked in-process via `evidence_ledger` (import, not subprocess) against the current content
of `--evidence-files`. Any STALE entry, a non-pass entry, or the absence of a FRESH
`regression=pass` entry downgrades the verdict to DEGRADED with the reason quoted in
acceptance.md — a green log from an older revision is not proof about the current tree.

`--run-id` (see `run_id.py`) is optional and only adds the line `run_id: <id>` to the header of
acceptance.md, so the artifact names the run it belongs to.

Exit code 0 = SUCCESS, 1 = FAILURE / DEGRADED / usage error. stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import signal
import subprocess
import sys

# Sibling script imported as a library: the acceptance gate and the reviewer must share ONE
# implementation of the FRESH/STALE rule (a subprocess would fork it into two).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import evidence_ledger  # noqa: E402  (needs the sys.path line above)

BACKTICKS = re.compile(r"`+")
EXCERPT_MAX_CHARS = 4096
EXCERPT_MAX_LINES = 20
TRUNCATION_MARK = "[... output truncated, showing the tail]"
REGRESSION_CHOICES = ("pass", "fail", "not-run")
VERDICTS = ("SUCCESS", "DEGRADED", "FAILURE")


def tail_excerpt(text: str, max_lines: int = EXCERPT_MAX_LINES,
                 max_chars: int = EXCERPT_MAX_CHARS) -> str:
    """Keep the last `max_lines` lines and at most `max_chars` characters of `text`.

    Output tails carry the failure cause; the head is noise. The mark makes a truncated
    excerpt explicit, so nobody mistakes a cut tail for the whole evidence.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    truncated = False
    lines = text.split("\n")
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
    out = "\n".join(lines).strip("\n")
    if len(out) > max_chars:
        out = out[-max_chars:]
        truncated = True
    if truncated:
        out = f"{TRUNCATION_MARK}\n{out}"
    return out


def _as_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill a timed-out command AND its children; a leaked test runner must not block the gate.

    Windows: `taskkill /F /T` (the shell is cmd.exe, the real work runs in its children).
    POSIX: SIGKILL to the whole process group (the child was started in its own session).
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_verify(command: str, repo: pathlib.Path, timeout: int) -> dict:
    """Execute one `verify` command in `repo` and return its observed evidence."""
    popen_kwargs = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                    else {"start_new_session": True})
    try:
        proc = subprocess.Popen(command, shell=True, cwd=str(repo), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace", **popen_kwargs)
    except OSError as exc:  # never crash silently; a criterion we cannot run is FAILED
        return {"exit_code": None, "excerpt": "", "status": "FAILED",
                "note": f"could not run the command: {exc}"}
    try:
        stdout, stderr = proc.communicate(timeout=timeout if timeout > 0 else None)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        out = _as_text(stdout) + _as_text(stderr)
        return {"exit_code": None, "excerpt": tail_excerpt(out),
                "status": "FAILED", "note": f"timeout after {timeout}s (process tree killed)"}
    out = (stdout or "") + (stderr or "")
    return {"exit_code": proc.returncode,
            "excerpt": tail_excerpt(out),
            "status": "MET" if proc.returncode == 0 else "FAILED",
            "note": ""}


def evaluate(criteria: list[dict], repo: pathlib.Path, timeout: int) -> list[dict]:
    """Run every verifiable criterion; unverifiable ones become UNVERIFIED with a label."""
    results: list[dict] = []
    for item in criteria:
        command = item.get("verify", "")
        if command:
            observed = run_verify(command, repo, timeout)
            results.append({"criterion": item["criterion"], "command": command,
                            "label": "", **observed})
        else:
            results.append({"criterion": item["criterion"], "command": "",
                            "exit_code": None, "excerpt": "",
                            "status": "UNVERIFIED",
                            "label": "derived" if item.get("derived") else "unverified",
                            "note": ("marked derived: inferred from other artifacts, not observed"
                                     if item.get("derived")
                                     else "no verify command: unproven in this run")})
    return results


def decide_verdict(results: list[dict], regression: str) -> tuple[str, str]:
    """Map observed evidence to a verdict; only SUCCESS is acceptable at the gate."""
    if regression == "fail":
        return "FAILURE", "regression baseline failed"
    if any(r["status"] == "FAILED" for r in results):
        failed = [r for r in results if r["status"] == "FAILED"]
        return "FAILURE", f"{len(failed)} verify criterion/criteria failed"
    if not any(r["command"] for r in results):
        return "DEGRADED", "no criterion carries a verify command: nothing was actually verified"
    if regression != "pass":
        return "DEGRADED", ("regression not proven (--regression not-run): SUCCESS is impossible "
                            "without regression evidence")
    return "SUCCESS", "all verify criteria MET and the regression baseline passed"


def check_ledger(ledger_path: pathlib.Path, evidence_files: list[str], repo: pathlib.Path) -> dict:
    """Re-check the evidence ledger against the current files; "" reason = trustworthy.

    Fail-safe by construction: an unreadable or broken ledger is never "no evidence", it is a
    rejection — a damaged ledger must not be able to certify a run.
    """
    try:
        entries = evidence_ledger.load_ledger(ledger_path)
        report = evidence_ledger.evaluate(entries, evidence_files, repo)
    except ValueError as exc:
        return {"path": str(ledger_path), "reason": f"evidence ledger unusable: {exc}",
                "detail": str(exc), "fingerprint": "", "rows": [], "files": len(evidence_files)}
    return {"path": str(ledger_path), "reason": evidence_ledger.acceptance_blocker(report["rows"]),
            "detail": report["reason"], "fingerprint": report["fingerprint"],
            "rows": report["rows"], "files": len(evidence_files)}


def _cell(text: str, limit: int = 160) -> str:
    """Make one markdown table cell out of arbitrary text."""
    flat = " ".join(str(text).replace("|", "\\|").split())
    return flat if len(flat) <= limit else flat[:limit - 3] + "..."


def _fence(text: str) -> str:
    """Fence `text` with a backtick run longer than any run inside it."""
    longest = max((len(m.group()) for m in BACKTICKS.finditer(text)), default=0)
    return "`" * max(3, longest + 1)


def render_markdown(results: list[dict], verdict: str, reason: str, regression: str,
                    ledger: dict | None = None, run_id: str = "") -> str:
    verified = sum(1 for r in results if r["status"] in ("MET", "FAILED"))
    unverified = sum(1 for r in results if r["status"] == "UNVERIFIED")
    lines = [
        "# Acceptance — verified criteria",
        "",
        f"Verdict: **{verdict}**",
        "",
    ]
    if run_id:  # run provenance: the artifact names the run it belongs to (see run_id.py)
        lines.append(f"- run_id: {run_id}")
    lines += [
        f"- Verdict reason: {reason}",
        f"- Regression baseline: {regression}",
        f"- Criteria: {len(results)} (verified: {verified}, unverified: {unverified})",
    ]
    if ledger:
        lines.append(f"- Evidence ledger: `{_cell(ledger['path'])}` "
                     f"({'REJECTED' if ledger['reason'] else 'all entries FRESH'})")
    lines += [
        "",
        "| # | Criterion | Command | Exit code | Status |",
        "|---|---|---|---|---|",
    ]
    for idx, res in enumerate(results, start=1):
        status = res["status"] if not res["label"] else f"{res['status']} ({res['label']})"
        exit_code = "n/a" if res["exit_code"] is None else str(res["exit_code"])
        if res["command"] and res["exit_code"] is None:
            exit_code = "err"
        command = f"`{_cell(res['command'])}`" if res["command"] else "n/a"
        lines.append(f"| {idx} | {_cell(res['criterion'])} | {command} | {exit_code} | {status} |")
    lines += ["", "## Evidence", ""]
    for idx, res in enumerate(results, start=1):
        lines += [f"### {idx}. {res['criterion']}", "",
                  f"- status: {res['status']}" + (f" ({res['label']})" if res["label"] else "")]
        if res["command"]:
            exit_code = "timeout/error" if res["exit_code"] is None else str(res["exit_code"])
            lines.append(f"- command: `{res['command']}`")
            lines.append(f"- exit code: {exit_code}")
            if res["note"]:
                lines.append(f"- note: {res['note']}")
            lines.append(f"- output excerpt (last {EXCERPT_MAX_LINES} lines, "
                         f"max {EXCERPT_MAX_CHARS} chars):")
            lines.append("")
            if res["excerpt"]:
                fence = _fence(res["excerpt"])
                lines += [fence, res["excerpt"], fence]
            else:
                lines.append("(no output)")
        else:
            lines.append(f"- label: {res['label']}")
            lines.append(f"- note: {res['note']}")
        lines.append("")
    if ledger:
        lines += ["", "## Evidence ledger", "",
                  f"- ledger: `{_cell(ledger['path'])}`",
                  f"- signed files: {ledger['files']}",
                  f"- current working-tree fingerprint: "
                  f"`{_cell(ledger['fingerprint'], 64) or 'n/a'}`",
                  f"- ledger check: {ledger['detail']}",
                  f"- reason: "
                  f"{ledger['reason'] or 'accepted: every evidence entry is FRESH and passes'}"]
        if ledger["rows"]:
            lines += ["", "| Evidence | Result | Freshness | Fingerprint |", "|---|---|---|---|"]
            for row in ledger["rows"]:
                lines.append(f"| {_cell(row['name'], 60)} | {_cell(row['result'], 20)} | "
                             f"{row['status']} | "
                             f"`{_cell(row['fingerprint'][:12] or 'n/a', 24)}` |")
    return "\n".join(lines).rstrip("\n") + "\n"


def load_criteria(path: pathlib.Path) -> list[dict]:
    """Read and validate the criteria JSON; raise ValueError with a human-readable cause."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read criteria file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"criteria file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"criteria file {path} must contain a JSON array of objects")
    criteria: list[dict] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"criterion #{idx} must be a JSON object")
        criterion = item.get("criterion")
        if not isinstance(criterion, str) or not criterion.strip():
            raise ValueError(f"criterion #{idx} needs a non-empty 'criterion' string")
        verify = item.get("verify", "")
        if verify is not None and not isinstance(verify, str):
            raise ValueError(f"criterion #{idx}: 'verify' must be a string")
        derived = item.get("derived", False)
        if not isinstance(derived, bool):
            raise ValueError(f"criterion #{idx}: 'derived' must be true or false")
        criteria.append({"criterion": criterion.strip(), "verify": (verify or "").strip(),
                         "derived": derived})
    return criteria


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help survives being piped or redirected.

    A Windows console defaults to a legacy code page (cp866/cp1251) and the help text carries a
    non-ASCII character (`—`, the em dash), which that codec cannot encode: `print_help()` would
    raise UnicodeEncodeError and the user would get a traceback instead of the help.
    `errors="replace"` keeps a stream that cannot be reconfigured from ever raising.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):      # an old interpreter or a replaced stream
            pass


def main() -> int:
    use_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Criteria JSON file (see module docstring)")
    ap.add_argument("--output", required=True, help="Path of the acceptance.md to write")
    ap.add_argument("--repo", default=".", help="Directory the verify commands run in")
    ap.add_argument("--regression", choices=REGRESSION_CHOICES, default="not-run",
                    help="Regression baseline outcome (default: not-run -> DEGRADED)")
    ap.add_argument("--timeout", type=int, default=600,
                    help="Seconds per verify command; 0 disables the timeout (default: 600)")
    ap.add_argument("--ledger", default="",
                    help="Optional evidence ledger JSON; checked when given (see module docstring)")
    ap.add_argument("--evidence-files", nargs="*", default=[], metavar="FILE",
                    help="Files the ledger evidence was signed over (required in practice for "
                         "--ledger: a different scope makes every entry STALE)")
    ap.add_argument("--run-id", default="",
                    help="Run id (see run_id.py); when given it is recorded in acceptance.md")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo)
    if not repo.is_dir():
        print(f"error: --repo is not a directory: {repo}", file=sys.stderr)
        return 1
    try:
        criteria = load_criteria(pathlib.Path(args.input))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results = evaluate(criteria, repo, args.timeout)
    verdict, reason = decide_verdict(results, args.regression)

    ledger_report = None
    if args.ledger:
        ledger_report = check_ledger(pathlib.Path(args.ledger), args.evidence_files, repo)
        if ledger_report["reason"]:
            if verdict == "SUCCESS":
                verdict, reason = "DEGRADED", f"evidence ledger rejected: {ledger_report['reason']}"
            else:
                reason = f"{reason}; evidence ledger rejected: {ledger_report['reason']}"
    # Explicit, -O-proof contract check: an `assert` would vanish under `python -O` and an
    # out-of-contract verdict would be rendered into acceptance.md as if it were a real one.
    if verdict not in VERDICTS:
        raise ValueError(f"internal verdict outside the contract: {verdict!r} not in {VERDICTS}")

    output = pathlib.Path(args.output)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(results, verdict, reason, args.regression,
                                          ledger_report, args.run_id),
                          encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {output}: {exc}", file=sys.stderr)
        return 1

    met = sum(1 for r in results if r["status"] == "MET")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    unverified = sum(1 for r in results if r["status"] == "UNVERIFIED")
    print(f"verify_acceptance: verdict={verdict} MET={met} FAILED={failed} "
          f"UNVERIFIED={unverified} regression={args.regression}")
    if ledger_report:
        print(f"verify_acceptance: ledger={ledger_report['path']} "
              f"entries={len(ledger_report['rows'])} "
              f"verdict_impact={'none' if not ledger_report['reason'] else 'downgraded'}")
    print(f"verify_acceptance: {reason}; report: {output}")
    return 0 if verdict == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
