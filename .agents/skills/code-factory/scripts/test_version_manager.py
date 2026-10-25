#!/usr/bin/env python3
"""
Deterministic self-test for `version_manager.py` (zero LLM tokens, stdlib only).

Verifies get/bump/sync/validate/set, the deterministic version-type matrix (`suggest`), the Rust
(`Cargo.toml`) manifests in the single source of truth, plus the "stdlib only" contract (no
third-party imports).

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


def build_clean_repo(root: pathlib.Path) -> None:
    """A repository whose every version marker already agrees with VERSION (12.1.0)."""
    build_repo(root)
    vm.sync(root, "12.1.0", "2026-09-01")


def write_manifest(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class OutputSink:
    """Minimal stdout/stderr sink: `io` and `contextlib` stay outside the import allowlist."""

    def __init__(self) -> None:
        self.text = ""

    def write(self, s: str) -> None:
        self.text += s

    def flush(self) -> None:
        pass


def run_validate(root: pathlib.Path) -> tuple[int, str, str]:
    """`version_manager.py --repo <root> validate` in-process -> (exit code, stdout, stderr)."""
    saved = sys.argv, sys.stdout, sys.stderr
    out, err = OutputSink(), OutputSink()
    sys.argv = ["version_manager.py", "--repo", str(root), "validate"]
    sys.stdout, sys.stderr = out, err
    try:
        code = vm.main()
    finally:
        sys.argv, sys.stdout, sys.stderr = saved
    return code, out.text, err.text


def suggest(**flags) -> tuple[str, int]:
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

    # 18-24. Rust manifests (Cargo.toml) are part of the single source of truth.
    ws_diverged = ('[workspace]\nmembers = ["crates/a", "crates/b"]\n\n[workspace.package]\n'
                   'version = "9.9.9"\nedition = "2021"\n')
    ws_consistent = ('[workspace]\nmembers = ["crates/a"]\n\n[workspace.package]\n'
                     'version = "12.1.0"\n')
    inherits = '[package]\nname = "b"\nversion.workspace = true\n'

    # 18. a diverging [workspace.package] version fails validate
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        write_manifest(root, "Cargo.toml", ws_diverged)
        code, _out, err = run_validate(root)
        expect(code == 1, "validate must exit 1 on a diverging [workspace.package] version")
        expect("Cargo.toml" in err and "9.9.9" in err and "12.1.0" in err,
               f"the failure must name the file, the declared version and VERSION: {err!r}")

    # 19. a member's literal [package] version must match VERSION too
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        write_manifest(root, "Cargo.toml", ws_consistent)
        write_manifest(root, "crates/a/Cargo.toml",
                       '[package]\nname = "a"\nversion = "9.9.9"\n')
        code, _out, err = run_validate(root)
        expect(code == 1, "validate must exit 1 on a diverging member [package] version")
        expect("crates/a/Cargo.toml" in err and "9.9.9" in err and "12.1.0" in err,
               f"the failure must name the member manifest: {err!r}")

    # 20. a member inheriting the workspace version is correct
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        write_manifest(root, "Cargo.toml", ws_consistent)
        write_manifest(root, "crates/b/Cargo.toml", inherits)
        code, out, err = run_validate(root)
        expect(code == 0, f"version.workspace = true must pass, got {err!r}")
        expect("PASS" in out, "a consistent Rust workspace must print PASS")

    # 21. a single-crate manifest (no workspace) is held to VERSION as well
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        write_manifest(root, "Cargo.toml", '[package]\nname = "solo"\nversion = "0.1.0"\n')
        code, _out, err = run_validate(root)
        expect(code == 1, "validate must exit 1 on a diverging single-crate version")
        expect("Cargo.toml" in err and "0.1.0" in err and "12.1.0" in err,
               f"the failure must name the single-crate manifest: {err!r}")

    # 22. sync rewrites the diverging workspace and member literals, byte-idempotently,
    #     and never inserts a version into a manifest that has none
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        write_manifest(root, "Cargo.toml", ws_diverged)
        write_manifest(root, "crates/a/Cargo.toml",
                       '[package]\nname = "a"\nversion = "9.9.9"  # keep the comment\n')
        write_manifest(root, "crates/b/Cargo.toml", inherits)
        write_manifest(root, "crates/c/Cargo.toml", '[package]\nname = "c"\n')
        notes = vm.sync(root, "12.1.0", "2026-09-01")
        expect(any("Cargo.toml" in n for n in notes),
               f"sync must report the Cargo rewrites: {notes}")
        ws = (root / "Cargo.toml").read_text(encoding="utf-8")
        member = (root / "crates/a/Cargo.toml").read_text(encoding="utf-8")
        expect('[workspace.package]\nversion = "12.1.0"' in ws,
               f"sync must rewrite the workspace: {ws!r}")
        expect('edition = "2021"' in ws,
               f"sync must keep the rest of the workspace section: {ws!r}")
        expect('version = "12.1.0"  # keep the comment' in member,
               f"sync must rewrite the member literal and keep its comment: {member!r}")
        expect((root / "crates/b/Cargo.toml").read_text(encoding="utf-8") == inherits,
               "sync must not touch a version.workspace = true member")
        expect("version" not in (root / "crates/c/Cargo.toml").read_text(encoding="utf-8"),
               "sync must never insert a version field")
        before = {p: p.read_bytes() for p in vm.cargo_manifests(root)}
        expect(vm.sync(root, "12.1.0", "2026-09-01") == [],
               "a second sync must have nothing to rewrite")
        expect({p: p.read_bytes() for p in vm.cargo_manifests(root)} == before,
               "a second sync must be byte-identical")
        code, out, _err = run_validate(root)
        expect(code == 0 and "PASS" in out, "validate must pass after sync rewrote the manifests")

    # 23. a repository with no Cargo.toml at all stays green and gains no file
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        code, out, _err = run_validate(root)
        expect(code == 0 and "PASS" in out, "no Cargo.toml must not create a problem")
        vm.sync(root, "12.1.0", "2026-09-01")
        expect(vm.cargo_manifests(root) == [], "sync must never create a Cargo.toml")

    # 24. a Cargo.toml under a pruned directory is invisible: the real root manifest is still
    #     checked, the scratch copy under .code-factory (3.10.0) is neither checked nor rewritten
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        build_clean_repo(root)
        pruned = root / ".code-factory" / "tmp" / "x" / "Cargo.toml"
        write_manifest(root, ".code-factory/tmp/x/Cargo.toml",
                       '[package]\nname = "scratch"\nversion = "3.10.0"\n')
        write_manifest(root, "target/debug/Cargo.toml",
                       '[package]\nname = "built"\nversion = "3.10.0"\n')
        code, out, _err = run_validate(root)
        expect(code == 0 and "PASS" in out,
               "manifests under .code-factory and target must be ignored")
        write_manifest(root, "Cargo.toml", '[package]\nname = "real"\nversion = "9.9.9"\n')
        code, _out, err = run_validate(root)
        expect(code == 1 and "9.9.9" in err and "3.10.0" not in err,
               f"only the unpruned manifest may fail validate: {err!r}")
        vm.sync(root, "12.1.0", "2026-09-01")
        expect('version = "3.10.0"' in pruned.read_text(encoding="utf-8"),
               "sync must not rewrite a manifest under a pruned directory")
        expect('version = "12.1.0"' in (root / "Cargo.toml").read_text(encoding="utf-8"),
               "sync must still rewrite the unpruned manifest")

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
