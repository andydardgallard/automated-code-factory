#!/usr/bin/env python3
"""
Deterministic self-test for `validate_documentation.py` (zero LLM tokens).

Builds synthetic before/after file trees and verifies the documentation validator
allows documentation-only changes and rejects any code/test/config change. Also runs one
end-to-end CLI round-trip (`snapshot` + `check`) to pin the documented invocation.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import validate_documentation as vd


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        base = pathlib.Path(td) / "baseline"
        (root / "docs").mkdir(parents=True)
        (root / "src").mkdir(parents=True)

        # 1. Markdown change -> allowed.
        (root / "docs" / "README.md").write_text("old\n", encoding="utf-8")
        vd.snapshot(root, base, ["docs/README.md"])
        (root / "docs" / "README.md").write_text("new docs\n", encoding="utf-8")
        expect(vd.check(root, base, ["docs/README.md"]) == [], "markdown change must pass")

        # 2. Config file touched -> rejected.
        (root / "config.toml").write_text("x=1\n", encoding="utf-8")
        vd.snapshot(root, base, ["config.toml"])
        (root / "config.toml").write_text("x=2\n", encoding="utf-8")
        expect(vd.check(root, base, ["config.toml"]) != [], "config change must fail")

        # 3. Source file, doc-comment-only change -> allowed.
        (root / "src" / "lib.py").write_text("def f():\n    \"\"\"doc\"\"\"\n    return 1\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/lib.py"])
        (root / "src" / "lib.py").write_text("def f():\n    \"\"\"new doc\"\"\"\n    return 1\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/lib.py"]) == [], "docstring-only change must pass")

        # 4. Source file, code line changed -> rejected.
        (root / "src" / "lib.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/lib.py"])
        (root / "src" / "lib.py").write_text("def f():\n    return 2\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/lib.py"]) != [], "code change must fail")

        # 5. Rust doc-comment change -> allowed.
        (root / "src" / "lib.rs").write_text("/// docs\npub fn f() -> i32 { 1 }\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/lib.rs"])
        (root / "src" / "lib.rs").write_text("/// better docs\npub fn f() -> i32 { 1 }\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/lib.rs"]) == [], "rustdoc-only change must pass")

        # 6. New source file with only doc lines -> allowed.
        (root / "src" / "new.py").write_text("# module doc\n# more\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/new.py"]) == [], "new doc-only source must pass")

        # 7. New source file with code -> rejected.
        (root / "src" / "new2.py").write_text("x = 1\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/new2.py"]) != [], "new source with code must fail")

        # 8. Test path touched -> rejected.
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "t.py").write_text("# t\n", encoding="utf-8")
        expect(vd.check(root, base, ["tests/t.py"]) != [], "test file must fail")

        # 9. End-to-end CLI round-trip (snapshot + check via subprocess) -> passes.
        script = pathlib.Path(vd.__file__)
        (root / "docs" / "cli.md").write_text("old\n", encoding="utf-8")
        r1 = subprocess.run([sys.executable, str(script), "snapshot", "--repo", td,
                             "--baseline", str(base / "cli"), "--files", "docs/cli.md"],
                            capture_output=True, text=True)
        expect(r1.returncode == 0, f"snapshot CLI must exit 0: {r1.stderr}")
        (root / "docs" / "cli.md").write_text("new content\n", encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(script), "check", "--repo", td,
                             "--baseline", str(base / "cli"), "--files", "docs/cli.md"],
                            capture_output=True, text=True)
        expect(r2.returncode == 0, f"check CLI must exit 0 for md-only change: {r2.stderr}")

    print("PASS - documentation validator allows only documentation-only changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
