#!/usr/bin/env python3
"""
Deterministic self-test for `version_manager.py` (zero LLM tokens, stdlib only).

Verifies get/bump/sync/validate/set and the deterministic version-type matrix (`suggest`),
plus the "stdlib only" contract (no third-party imports).

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tempfile

import version_manager as vm


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def build_repo(root: pathlib.Path) -> None:
    (root / ".agents" / "skills" / "code-factory").mkdir(parents=True, exist_ok=True)
    (root / ".agents").mkdir(exist_ok=True)
    (root / "VERSION").write_text("12.1.0\n", encoding="utf-8")
    (root / "README.md").write_text("# Autonomous Code Factory v12.1.0\n\nCurrent version: **12.1.0**\n",
                                    encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [12.1.0] — 2026-09-01\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Project\n", encoding="utf-8")
    (root / ".agents" / "README.md").write_text("# Code Factory\n", encoding="utf-8")
    (root / ".agents" / "skills" / "code-factory" / "SKILL.md").write_text(
        "---\nname: code-factory\n---\n# Code Factory\n", encoding="utf-8")


def suggest(**flags) -> str:
    ns = argparse.Namespace(new_subagent=False, new_task_type=False, new_field=False,
                            breaking=False, fix=False, no_change=False)
    for k, v in flags.items():
        setattr(ns, k, v)
    # capture stdout
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = vm.suggest(ns)
    return buf.getvalue().strip(), code


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_repo(root)

        # 1. get
        expect(vm.read_version(root / "VERSION") == "12.1.0", "read_version must return VERSION")

        # 2-4. bump arithmetic
        expect(vm.bump("12.1.0", "patch") == "12.1.1", "bump patch")
        expect(vm.bump("12.1.0", "minor") == "12.2.0", "bump minor resets patch")
        expect(vm.bump("12.1.0", "major") == "13.0.0", "bump major resets minor+patch")

        # 5-10. deterministic version-type matrix
        expect(suggest(new_subagent=True)[0] == "minor", "new subagent -> minor")
        expect(suggest(new_task_type=True)[0] == "minor", "new task type -> minor")
        expect(suggest(new_field=True)[0] == "minor", "new field -> minor")
        expect(suggest(breaking=True)[0] == "major", "breaking -> major")
        expect(suggest(fix=True)[0] == "patch", "fix -> patch")
        expect(suggest(no_change=True)[0] == "none", "no-change -> none")
        expect(suggest()[1] == 1, "suggest without a signal must exit 1")

        # 11. sync propagates to README title/footer + adds markers + CHANGELOG section
        vm.sync(root, "12.5.0", "2026-09-08")
        readme = (root / "README.md").read_text(encoding="utf-8")
        expect("v12.5.0" in readme and "Current version: **12.5.0**" in readme, "sync must update README")
        expect("code-factory-version: 12.5.0" in (root / "AGENTS.md").read_text(encoding="utf-8"),
               "sync must add marker to AGENTS.md")
        expect("code-factory-version: 12.5.0" in (root / ".agents" / "README.md").read_text(encoding="utf-8"),
               "sync must add marker to .agents/README.md")
        expect("code-factory-version: 12.5.0" in (root / ".agents" / "skills" / "code-factory" / "SKILL.md").read_text(encoding="utf-8"),
               "sync must add marker to SKILL.md")
        expect("## [12.5.0] — 2026-09-08" in (root / "CHANGELOG.md").read_text(encoding="utf-8"),
               "sync must add CHANGELOG section at top")

        # 12. sync is idempotent (no duplicate CHANGELOG section / marker)
        vm.sync(root, "12.5.0", "2026-09-08")
        cl = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        expect(cl.count("## [12.5.0]") == 1, "sync must be idempotent for CHANGELOG")
        expect((root / "AGENTS.md").read_text(encoding="utf-8").count("code-factory-version: 12.5.0") == 1,
               "sync must be idempotent for markers")

        # 13. validate returns 0 after sync
        (root / "VERSION").write_text("12.5.0\n", encoding="utf-8")
        ok, problems = vm.validate(root, "12.5.0")
        expect(ok, f"validate must pass after sync, got {problems}")

        # 14. validate returns 1 when a file has a stale version
        (root / "AGENTS.md").write_text("<!-- code-factory-version: 12.4.0 -->\n# Project\n",
                                        encoding="utf-8")
        ok, _ = vm.validate(root, "12.5.0")
        expect(not ok, "validate must fail on stale marker")

        # 15. validate returns 1 when VERSION is malformed
        (root / "VERSION").write_text("not.a.version\n", encoding="utf-8")
        try:
            vm.read_version(root / "VERSION")
            expect(False, "read_version must reject malformed VERSION")
        except SystemExit:
            pass

        # 16. set overrides and syncs
        (root / "VERSION").write_text("12.1.0\n", encoding="utf-8")
        vm.write_version(root / "VERSION", "13.0.0")
        vm.sync(root, "13.0.0", "2026-09-08")
        expect((root / "VERSION").read_text(encoding="utf-8").strip() == "13.0.0",
               "set must write VERSION")
        expect("v13.0.0" in (root / "README.md").read_text(encoding="utf-8"),
               "set must sync README")

    # 17. stdlib-only contract (no third-party imports).
    src = pathlib.Path(vm.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from)\s+([A-Za-z0-9_]+)", src, flags=re.M))
    allowed = {"__future__", "argparse", "datetime", "pathlib", "re", "sys"}
    expect(imported <= allowed, f"version_manager must be stdlib-only, imports={imported}")

    print("PASS - version manager get/bump/sync/validate/set/suggest behave as expected "
          "(stdlib only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
