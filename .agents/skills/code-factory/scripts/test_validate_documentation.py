#!/usr/bin/env python3
"""
Deterministic self-test for `validate_documentation.py` (zero LLM tokens).

Builds synthetic before/after file trees and verifies the documentation validator
allows documentation-only changes and rejects any code/test/config change. Also runs one
end-to-end CLI round-trip (`snapshot` + `check`) to pin the documented invocation, pins the
LANGUAGE-AWARE doc classifier (a `#define`/`#include` is CODE in the C family, a `#` comment is
documentation in shell/python; `;`/`%`/`--` count only where they are comments), and covers
`check --derive` against a scratch git repository: an undeclared changed file fails the run,
identical declared/derived lists pass, and a non-git --repo degrades with exit 2.

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

        # 10. Regression (F11): the SAME indented executable line occurs twice - once as real code
        # and once inside a docstring. Deleting the CODE occurrence (the docstring copy stays) is a
        # code change and must be rejected; a content search for the line would find the docstring
        # copy first and miss it, so the validator has to classify changed lines by POSITION.
        dup_old = 'def f():\n    """doc\n    return 1\n    """\n    return 1\n'
        dup_new = 'def f():\n    """doc\n    return 1\n    """\n'
        (root / "src" / "dup.py").write_text(dup_old, encoding="utf-8")
        vd.snapshot(root, base, ["src/dup.py"])
        (root / "src" / "dup.py").write_text(dup_new, encoding="utf-8")
        expect(vd.check(root, base, ["src/dup.py"]) != [],
               "deleting the code copy of a line duplicated in a docstring must fail")

        # 11. Same duplicated shape, but only the docstring text changes -> still allowed.
        (root / "src" / "dup.py").write_text(dup_old, encoding="utf-8")
        vd.snapshot(root, base, ["src/dup.py"])
        (root / "src" / "dup.py").write_text(dup_old.replace("doc", "new doc"), encoding="utf-8")
        expect(vd.check(root, base, ["src/dup.py"]) == [],
               "docstring-only change in a file with a duplicated line must pass")

        # 12. Same duplicated shape, deleting the DOCSTRING copy of the line -> documentation-only
        # edit, must still be allowed (the fix must not over-reject).
        (root / "src" / "dup.py").write_text(dup_old, encoding="utf-8")
        vd.snapshot(root, base, ["src/dup.py"])
        (root / "src" / "dup.py").write_text('def f():\n    """doc\n    """\n    return 1\n',
                                            encoding="utf-8")
        expect(vd.check(root, base, ["src/dup.py"]) == [],
               "deleting the docstring copy of a duplicated line must pass")

        # 13. Classifier unit: a bare `*` or `|` line OUTSIDE a block comment / docstring is code.
        # Before the fix these two lines were classified as documentation, so `*ptr = 1;` in a .c
        # file could be edited freely. A `/*` opener (not just `/**`) must turn the block state on
        # so `*` continuation lines stay documentation inside the block.
        expect(vd._doc_mask(["def f():", "*ptr = 1;", "| mask = 2;", "    return 3"])
               == [False, False, False, False],
               "bare '*'/'|' lines outside a block must be code")
        expect(vd._doc_mask(["/*", " * doc", " */", "int x;"]) == [True, True, True, False],
               "a plain /* block must open the block state")
        expect(vd._doc_mask(["/**", " * doc", " */"]) == [True, True, True],
               "a /** block must still be documentation")
        expect(vd._doc_mask(["/*!", " * doc", " */"]) == [True, True, True],
               "a /*! block must open the block state")
        expect(vd._doc_mask(['"""', "x = 1", '"""', "| mask = 2;"]) == [True, True, True, False],
               "a '|' line inside a docstring is doc, outside it is code")

        # 14. A changed `*ptr = 2;` line in a .c file is a CODE change -> rejected.
        (root / "src" / "ptr.c").write_text(
            "int f(void)\n{\n/* pointer doc */\n*ptr = 1;\n| mask = 2;\n    return 3;\n}\n",
            encoding="utf-8")
        vd.snapshot(root, base, ["src/ptr.c"])
        (root / "src" / "ptr.c").write_text(
            "int f(void)\n{\n/* pointer doc */\n*ptr = 2;\n| mask = 2;\n    return 3;\n}\n",
            encoding="utf-8")
        errs = vd.check(root, base, ["src/ptr.c"])
        expect(any(e.startswith("src/ptr.c: code line changed:") and "*ptr =" in e for e in errs),
               "changing a '*ptr = 2;' code line in a .c file must fail")

        # 15. A changed `| y = 3` line in a .py file is a CODE change -> rejected.
        (root / "src" / "mask.py").write_text("x = 1\n| y = 2\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/mask.py"])
        (root / "src" / "mask.py").write_text("x = 1\n| y = 3\n", encoding="utf-8")
        errs = vd.check(root, base, ["src/mask.py"])
        expect(any(e.startswith("src/mask.py: code line changed:") and "| y =" in e for e in errs),
               "changing a '| y = 3' line in a .py file must fail")

        # 16. A changed line INSIDE a `/* ... * ... */` block comment is documentation -> allowed.
        (root / "src" / "blk.c").write_text(
            "/*\n * old doc\n */\nint f(void) { return 1; }\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/blk.c"])
        (root / "src" / "blk.c").write_text(
            "/*\n * new doc\n */\nint f(void) { return 1; }\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/blk.c"]) == [],
               "a changed '/* ... * ... */' block comment line must pass")

        # 16b. Same for a `/*!` Doxygen block comment.
        (root / "src" / "blk.c").write_text(
            "/*!\n * old doc\n */\nint f(void) { return 1; }\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/blk.c"])
        (root / "src" / "blk.c").write_text(
            "/*!\n * new doc\n */\nint f(void) { return 1; }\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/blk.c"]) == [],
               "a changed '/*! ... * ... */' block comment line must pass")

        # 17. Protected set matches FILE NAMES, not only path segments: `scripts/test_x.py` sits
        # in no `tests/` directory, yet it is a test file and must be rejected; `src/app.py` is
        # normal source and must not be.
        for rel in ("scripts/test_x.py", "src/foo_test.go", "web/app.test.ts", "src/conftest.py",
                    "src/foo_spec.rb"):
            expect(vd._is_protected(rel), f"{rel} must be protected (file-name marker)")
        for rel in ("src/app.py", "docs/README.md", "src/lib.rs", "src/contest.py", "src/app.pyc"):
            expect(not vd._is_protected(rel), f"{rel} must not be protected")
        (root / "scripts").mkdir(exist_ok=True)
        (root / "scripts" / "test_x.py").write_text("# module doc\n", encoding="utf-8")
        expect(vd.check(root, base, ["scripts/test_x.py"]) != [],
               "scripts/test_x.py must fail as a protected test file")
        (root / "src" / "app.py").write_text("# app doc\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/app.py"]) == [],
               "src/app.py (doc-only, not protected) must pass")

        # 18. The doc classifier is LANGUAGE-AWARE: `#` is a comment in shell/python/ruby, but a
        #     preprocessor (CODE) line in the C family; `;` / `%` / `>` count only where they are
        #     comments, and `--` only in SQL/Lua/Haskell.
        expect(vd._doc_mask(["#define MAX 1", "#include <stdio.h>", " int x;"], "src/a.c")
               == [False, False, False],
               "'#define'/'#include' in a .c file are CODE lines, not documentation")
        expect(vd._doc_mask(["#define MAX 1"], "src/a.h") == [False],
               "'#define' in a .h file is a CODE line too")
        expect(vd._doc_mask(["# comment"], "run.sh") == [True]
               and vd._doc_mask(["# comment"], "mod.py") == [True],
               "a real '# comment' in a .sh/.py file stays documentation")
        expect(vd._doc_mask(["; comment", "% comment", "> quote"], "mod.py")
               == [False, False, False],
               "';'/'%'/'>' are not comments in Python")
        expect(vd._doc_mask(["; comment"], "app.clj") == [True],
               "';' is a comment in Clojure")
        expect(vd._doc_mask(["% comment"], "script.m") == [True],
               "'%' is a comment in the MATLAB flavour of .m")
        expect(vd._doc_mask(["-- comment"], "q.sql") == [True]
               and vd._doc_mask(["-- comment"], "mod.py") == [False],
               "'--' is a comment in SQL, not in Python")

        # 19. A changed `#include` line in a .c file is a CODE change -> rejected.
        (root / "src" / "inc.c").write_text("#include <stdio.h>\nint f(void) { return 1; }\n",
                                            encoding="utf-8")
        vd.snapshot(root, base, ["src/inc.c"])
        (root / "src" / "inc.c").write_text("#include <stdlib.h>\nint f(void) { return 1; }\n",
                                            encoding="utf-8")
        errs = vd.check(root, base, ["src/inc.c"])
        expect(any(e.startswith("src/inc.c: code line changed:") and "#include" in e for e in errs),
               "changing a '#include' preprocessor line in a .c file must fail")

        # 20. A changed `#` comment line in a .sh file is documentation -> allowed.
        (root / "run.sh").write_text("# old doc\necho hi\n", encoding="utf-8")
        vd.snapshot(root, base, ["run.sh"])
        (root / "run.sh").write_text("# new doc\necho hi\n", encoding="utf-8")
        expect(vd.check(root, base, ["run.sh"]) == [],
               "a changed '# comment' line in a .sh file must pass")

        # 21. `check --derive` computes the changed TRACKED set itself from `git status
        #     --porcelain` and FAILS when the declared --files omit a changed file (the policed
        #     agent does not choose the scope of its own police); identical lists pass.
        grepo = root / "grepo"
        (grepo / "docs").mkdir(parents=True)
        (grepo / "src").mkdir()

        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(grepo), *args], check=True, capture_output=True)

        git("init")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Self Test")
        (grepo / "docs" / "d.md").write_text("old\n", encoding="utf-8")
        (grepo / "src" / "app.py").write_text("# doc\nx = 1\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "base")
        gbase = root / "gbase"
        vd.snapshot(grepo, gbase, ["docs/d.md", "src/app.py"])
        (grepo / "docs" / "d.md").write_text("new docs\n", encoding="utf-8")
        (grepo / "src" / "app.py").write_text("# new doc\nx = 1\n", encoding="utf-8")  # doc-only
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(grepo),
                            "--baseline", str(gbase), "--files", "docs/d.md", "--derive"],
                           capture_output=True, text=True)
        expect(r.returncode != 0 and "src/app.py" in r.stderr,
               f"--derive must fail and name the undeclared changed file: "
               f"{r.returncode} {r.stderr!r}")
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(grepo),
                            "--baseline", str(gbase), "--files", "docs/d.md", "src/app.py",
                            "--derive"], capture_output=True, text=True)
        expect(r.returncode == 0,
               f"--derive with the full changed set declared must pass: {r.returncode} {r.stderr!r}")
        # 21b. A NON-ASCII path must survive the derivation: `git status --porcelain` C-quotes it
        #      (`"src/caf\303\251.py"`) unless `-z` is used, and no declared path could ever match
        #      that spelling — the mode would fail a correctly declared file.
        unicode_rel = "src/caf\u00e9.py"
        (grepo / unicode_rel).write_text("# doc\nx = 1\n", encoding="utf-8")
        git("add", unicode_rel)
        git("commit", "-m", "add unicode")
        vd.snapshot(grepo, gbase, ["docs/d.md", "src/app.py", unicode_rel])
        (grepo / unicode_rel).write_text("# new doc\nx = 1\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(grepo),
                            "--baseline", str(gbase), "--files", "docs/d.md", "src/app.py",
                            unicode_rel, "--derive"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        expect(r.returncode == 0,
               f"--derive must read a non-ASCII path unquoted: {r.returncode} {r.stderr!r}")
        # Degrade path: --repo is not a git repository -> exit 2 with a message, no traceback.
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(root),
                            "--baseline", str(base), "--files", "docs/README.md", "--derive"],
                           capture_output=True, text=True)
        expect(r.returncode == 2 and "error:" in r.stderr and "Traceback" not in r.stderr,
               f"--derive outside a git repository must degrade with exit 2: "
               f"{r.returncode} {r.stderr!r}")
        r = subprocess.run([sys.executable, str(script), "check", "--help"],
                           capture_output=True, text=True)
        expect(r.returncode == 0 and "--derive" in r.stdout,
               f"--derive must be discoverable in --help: {r.returncode} {r.stdout[:200]!r}")

    print("PASS - documentation validator allows only documentation-only changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
