#!/usr/bin/env python3
"""
Deterministic self-test for `validate_documentation.py` (zero LLM tokens).

Builds synthetic before/after file trees and verifies the documentation validator
allows documentation-only changes and rejects any code/test/config change. Also runs one
end-to-end CLI round-trip (`snapshot` + `check`) to pin the documented invocation, pins the
LANGUAGE-AWARE doc classifier (a `#define`/`#include` is CODE in the C family, a `#` comment is
documentation in shell/python; `;`/`%`/`--` count only where they are comments), and covers
`check --derive` against a scratch git repository: an undeclared changed file fails the run,
an undeclared untracked file fails it too while an ignored one stays out of scope, identical
declared/derived lists pass, and a non-git --repo degrades with exit 2. A final regression case
simulates an implement run whose own test/config/unknown-kind files are already changed before the
documenter starts: `--baseline-files` excludes that orchestrator-supplied pre-DOC2 set from the
undeclared-file comparison only, and only while the file still is in the state captured then — a
`path=sha256hex` entry whose file changed after capture is NOT exempted, so an undeclared edit to an
already-changed (even protected) file cannot hide behind its name (declared documenter edits pass,
undeclared ones and explicitly declared protected files still fail, and the option's input boundary
rejects name-only, absolute/`..`/blank and bad-hash entries and use without `--derive` with exit 2).
The `baseline` subcommand is the producer of exactly those entries.

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
        (grepo / ".gitignore").write_text("build/\n", encoding="utf-8")
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
        # 21c. Regression (C15): the derived set includes UNTRACKED (`??`) files, ignored (`!!`)
        #      ones stay out of scope. Before the fix `??` was skipped, so a documenter could
        #      create a new source/config/test file with real code, leave it out of --files, and
        #      --derive never submitted it to check().
        (grepo / "build").mkdir()
        (grepo / "build" / "out.py").write_text("x = 1\n", encoding="utf-8")  # ignored -> out of scope
        (grepo / "src" / "sneaky.py").write_text("dangerous = 1\n", encoding="utf-8")
        declared = ["docs/d.md", "src/app.py", unicode_rel]
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(grepo),
                            "--baseline", str(gbase), "--files", *declared, "--derive"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        expect(r.returncode != 0 and "src/sneaky.py" in r.stderr and "build/out.py" not in r.stderr,
               f"--derive must report an undeclared untracked file and skip an ignored one: "
               f"{r.returncode} {r.stderr!r}")
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(grepo),
                            "--baseline", str(gbase), "--files", *declared, "src/sneaky.py",
                            "--derive"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        expect(r.returncode != 0 and "src/sneaky.py" in r.stderr,
               f"a declared new file with code must still fail the doc-only gate: "
               f"{r.returncode} {r.stderr!r}")
        (grepo / "src" / "sneaky.py").unlink()
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

        # 22. Comment SPANS, not whole lines. A line is documentation only when everything on it
        #     outside a comment span is blank: `/* doc */ return x;` carries executable code AFTER
        #     the closing `*/`, so the whole line is a CODE line. Before the fix any line starting
        #     with `/*` counted as documentation, so `/* doc */ return safe_value;` could be edited
        #     into `/* doc */ return dangerous_value;` and pass the documentation-only gate.
        expect(vd._doc_mask(["/* doc */ return safe_value;"]) == [False],
               "code after a single-line block comment must be a code line")
        expect(vd._doc_mask(["/*", " * doc", " */ return safe_value;"]) == [True, True, False],
               "code on the closing line of a multi-line block comment must be a code line")
        expect(vd._doc_mask(["/* doc */"]) == [True],
               "a line holding only a block comment stays documentation")
        expect(vd._doc_mask(["/* a */ /* b */"]) == [True],
               "a line of comment spans only stays documentation")

        # 23. End-to-end: changing the value returned AFTER a single-line block comment is a code
        #     change and must be rejected (the finding's exact exploit).
        (root / "src" / "span.c").write_text(
            "int f(void)\n{\n/* doc */ return safe_value;\n}\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/span.c"])
        (root / "src" / "span.c").write_text(
            "int f(void)\n{\n/* doc */ return dangerous_value;\n}\n", encoding="utf-8")
        errs = vd.check(root, base, ["src/span.c"])
        expect(any(e.startswith("src/span.c: code line changed:") for e in errs),
               f"changing code after a single-line block comment must fail: {errs}")

        # 24. End-to-end: the same for code placed on the CLOSING line of a multi-line block.
        (root / "src" / "span.c").write_text(
            "int f(void)\n{\n/*\n * doc\n */ return safe_value;\n}\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/span.c"])
        (root / "src" / "span.c").write_text(
            "int f(void)\n{\n/*\n * doc\n */ return dangerous_value;\n}\n", encoding="utf-8")
        errs = vd.check(root, base, ["src/span.c"])
        expect(any(e.startswith("src/span.c: code line changed:") for e in errs),
               f"changing code on the closing line of a block comment must fail: {errs}")

        # 25. The fix must not over-reject: a comment-only line (nothing outside the spans) stays
        #     documentation in both a single-line and a multi-line block.
        (root / "src" / "span.c").write_text(
            "int f(void)\n{\n/* old doc */\nreturn 1;\n}\n", encoding="utf-8")
        vd.snapshot(root, base, ["src/span.c"])
        (root / "src" / "span.c").write_text(
            "int f(void)\n{\n/* new doc */\nreturn 1;\n}\n", encoding="utf-8")
        expect(vd.check(root, base, ["src/span.c"]) == [],
               "changing a comment-only block comment line must still pass")

        # 26. Regression (C14): a Python docstring line is documentation only when nothing but
        #     whitespace sits OUTSIDE its triple-quoted spans — `"""doc"""; safe = 1` carries
        #     executable code after the closing delimiter and is therefore a CODE line. Before the
        #     fix any line starting with a triple quote counted as documentation, so the value after
        #     the docstring could be edited freely (the finding's exact exploit).
        expect(vd._doc_mask(['"""doc"""; safe = 1']) == [False],
               "code after a single-line docstring must be a code line")
        expect(vd._doc_mask(['x = 1; """doc"""']) == [False],
               "code before a single-line docstring must be a code line")
        expect(vd._doc_mask(['"""doc"""']) == [True],
               "a line holding only a docstring stays documentation")
        expect(vd._doc_mask(['"""', "doc", '""" + x']) == [True, True, False],
               "code on the closing line of a docstring must be a code line")
        expect(vd._doc_mask(["'''doc'''; safe = 1"]) == [False],
               "the same holds for the ''' delimiter")

        # 27. End-to-end: changing the value assigned AFTER a docstring on the same line is a code
        #     change and must be rejected.
        (root / "src" / "ds.py").write_text('def f():\n    """doc"""; safe = 1\n',
                                            encoding="utf-8")
        vd.snapshot(root, base, ["src/ds.py"])
        (root / "src" / "ds.py").write_text('def f():\n    """doc"""; dangerous = 1\n',
                                            encoding="utf-8")
        errs = vd.check(root, base, ["src/ds.py"])
        expect(any(e.startswith("src/ds.py: code line changed:") for e in errs),
               f"changing code after a docstring must fail: {errs}")

        # 28. Regression (--derive scope conflict, mutually unsatisfiable modes): an implement run
        #     has ALREADY changed test/config/unknown-kind files before the documenter starts.
        #     `--derive` recomputes the changed set from git, so those files were reported as
        #     "changed but not declared" no matter what the documenter declared — protected and
        #     unknown kinds failed unconditionally. `--baseline-files` names that pre-DOC2 set WITH
        #     its captured state (`path=sha256hex`, produced by the `baseline` subcommand) and
        #     excludes it from the UNDECLARED comparison only: the documenter's declared .md edit
        #     passes, an undeclared documenter edit and an explicitly declared protected file still
        #     fail, and so does an undeclared edit to a baseline-listed file whose content changed
        #     after the baseline was captured (the name alone never exempts). On the pre-fix script
        #     the option does not exist at all (argparse exit 2), so every "must pass" assertion
        #     below fails there.
        irepo = root / "irepo"
        for sub in ("docs", "scripts", "config", "patches"):
            (irepo / sub).mkdir(parents=True)
        run_files = ["scripts/test_run.py", "config/settings.yaml", "patches/fix.patch"]

        def igit(*args: str) -> None:
            subprocess.run(["git", "-C", str(irepo), *args], check=True, capture_output=True)

        igit("init")
        igit("config", "user.email", "test@example.com")
        igit("config", "user.name", "Self Test")
        base_docs = {"docs/guide.md": "old guide\n", "docs/extra.md": "old extra\n"}
        base_run = {
            "scripts/test_run.py": "# base test\nassert 1\n",
            "config/settings.yaml": "a: 1\n",
            "patches/fix.patch": "--- a\n+++ b\n",
        }
        for rel, text in {**base_docs, **base_run}.items():
            (irepo / rel).write_text(text, encoding="utf-8")
        igit("add", ".")
        igit("commit", "-m", "base")
        ibase = root / "ibase"
        vd.snapshot(irepo, ibase, ["docs/guide.md"])          # the documenter's target, pre-edit
        # the implement run's own changes (captured before DOC2) ...
        (irepo / "scripts" / "test_run.py").write_text("# new test\nassert 2\n", encoding="utf-8")
        (irepo / "config" / "settings.yaml").write_text("a: 2\n", encoding="utf-8")
        (irepo / "patches" / "fix.patch").write_text("--- c\n+++ d\n", encoding="utf-8")

        def capture(*paths: str) -> list[str]:
            """The orchestrator's pre-DOC2 capture: `baseline` prints one `path=state` per file."""
            r = subprocess.run([sys.executable, str(script), "baseline", "--repo", str(irepo),
                                "--files", *paths], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            entries = r.stdout.split()
            expect(r.returncode == 0 and len(entries) == len(paths),
                   f"the baseline subcommand must print one path=state entry per file: "
                   f"{r.returncode} {r.stdout!r} {r.stderr!r}")
            return entries

        run_entries = capture(*run_files)
        for entry in run_entries:
            rel, _, state = entry.partition("=")
            expect(state == vd.baseline_state(irepo, rel),
                   f"the captured baseline must carry the file's current state: {entry!r}")
        # ... plus the documenter's own declared edit.
        (irepo / "docs" / "guide.md").write_text("new guide\n", encoding="utf-8")

        def icheck(*extra: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, str(script), "check", "--repo", str(irepo),
                                   "--baseline", str(ibase), "--files", "docs/guide.md", *extra],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")

        r = icheck("--derive")
        expect(r.returncode != 0 and "scripts/test_run.py" in r.stderr,
               f"--derive without a baseline must still fail on the run's own files: "
               f"{r.returncode} {r.stderr!r}")
        r = icheck("--derive", "--baseline-files", *run_entries)
        expect(r.returncode == 0,
               f"--baseline-files must exclude the pre-DOC2 run files from the derive comparison: "
               f"{r.returncode} {r.stderr!r}")
        # Windows separators name the same files (normalized), and duplicates are harmless.
        backslashed = [entry.replace("/", "\\") for entry in run_entries]
        r = icheck("--derive", "--baseline-files", *backslashed, run_entries[0])
        expect(r.returncode == 0,
               f"--baseline-files must normalize separators and deduplicate: "
               f"{r.returncode} {r.stderr!r}")
        # An EMPTY baseline list is legitimate input; it excludes nothing, so the run's own files
        # are still reported (an empty list must never be a silent "skip everything").
        r = icheck("--derive", "--baseline-files")
        expect(r.returncode != 0 and "scripts/test_run.py" in r.stderr,
               f"an empty --baseline-files list must be legal and exclude nothing: "
               f"{r.returncode} {r.stderr!r}")
        # A documenter edit that is neither declared nor part of the baseline still fails.
        (irepo / "docs" / "extra.md").write_text("undeclared doc edit\n", encoding="utf-8")
        r = icheck("--derive", "--baseline-files", *run_entries)
        expect(r.returncode != 0 and "docs/extra.md" in r.stderr,
               f"--baseline-files must not hide an undeclared documenter edit: "
               f"{r.returncode} {r.stderr!r}")
        (irepo / "docs" / "extra.md").write_text(base_docs["docs/extra.md"], encoding="utf-8")
        # A protected file the documenter DECLARES still fails, baseline or not: the option scopes
        # the undeclared comparison only, it never whitelists an explicit --files declaration.
        r = subprocess.run([sys.executable, str(script), "check", "--repo", str(irepo),
                            "--baseline", str(ibase), "--files", "config/settings.yaml",
                            "--derive", "--baseline-files", *run_entries],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        expect(r.returncode != 0 and "PROTECTED" in r.stderr,
               f"a declared protected file must fail even when it is in --baseline-files: "
               f"{r.returncode} {r.stderr!r}")
        # 29. Regression (name-only exemption hid a documenter edit): a baseline path is exempt
        #     ONLY while its content is still the captured one. An UNDECLARED edit to a file the
        #     run had already changed before DOC2 — here a PROTECTED one — must therefore fail, and
        #     the exemption must come back once the file is restored to its captured state.
        (irepo / "config" / "settings.yaml").write_text("a: 3\n", encoding="utf-8")
        r = icheck("--derive", "--baseline-files", *run_entries)
        expect(r.returncode != 0 and "config/settings.yaml" in r.stderr
               and "modified since the pre-DOC2 baseline was captured" in r.stderr,
               f"an undeclared edit to a baseline-listed file must still fail: "
               f"{r.returncode} {r.stderr!r}")
        (irepo / "config" / "settings.yaml").write_text("a: 2\n", encoding="utf-8")
        r = icheck("--derive", "--baseline-files", *run_entries)
        expect(r.returncode == 0,
               f"a baseline-listed file restored to its captured state must be exempted again: "
               f"{r.returncode} {r.stderr!r}")
        # A documenter DELETION of a baseline-listed file is a change of its state too.
        (irepo / "patches" / "fix.patch").unlink()
        r = icheck("--derive", "--baseline-files", *run_entries)
        expect(r.returncode != 0 and "patches/fix.patch" in r.stderr,
               f"a baseline-listed file deleted after capture must not be exempted: "
               f"{r.returncode} {r.stderr!r}")
        (irepo / "patches" / "fix.patch").write_text("--- c\n+++ d\n", encoding="utf-8")
        # The `-` sentinel records a file that was ABSENT at capture: it exempts an absence only,
        # never a file that appeared afterwards.
        expect(capture("patches/gone.patch") == ["patches/gone.patch=-"],
               "an absent baseline file must be recorded as `-`")
        (irepo / "patches" / "gone.patch").write_text("--- e\n+++ f\n", encoding="utf-8")
        r = icheck("--derive", "--baseline-files", *(run_entries + ["patches/gone.patch=-"]))
        expect(r.returncode != 0 and "patches/gone.patch" in r.stderr,
               f"an absent-file baseline entry must not exempt a file created later: "
               f"{r.returncode} {r.stderr!r}")
        (irepo / "patches" / "gone.patch").unlink()
        # Input boundary: a name-only entry is a usage error — name-only exemption is exactly the
        # hole the content state closes — and so are a bad state, a contradictory duplicate, an
        # absolute path, a `..` escape and a blank entry (exit 2, never a traceback).
        for bad in ("docs/guide.md",
                    "docs/guide.md=" + "a" * 63, "docs/guide.md=" + "z" * 64,
                    "docs/guide.md=" + "a" * 64 + "=x",
                    str((irepo / "docs" / "guide.md").resolve()) + "=" + "a" * 64,
                    "C:/repo/docs/guide.md=" + "a" * 64,
                    "../outside.md=" + "a" * 64, "docs/../../x.md=" + "a" * 64, ""):
            r = icheck("--derive", "--baseline-files", bad)
            expect(r.returncode == 2 and "error:" in r.stderr and "Traceback" not in r.stderr,
                   f"--baseline-files must reject {bad!r} with exit 2: "
                   f"{r.returncode} {r.stderr!r}")
        r = icheck("--derive", "--baseline-files", "docs/guide.md=" + "a" * 64,
                   "docs/guide.md=" + "b" * 64)
        expect(r.returncode == 2 and "contradicts" in r.stderr,
               f"two different states for one baseline path must exit 2: "
               f"{r.returncode} {r.stderr!r}")
        # Input boundary: --baseline-files without --derive is a usage error (exit 2).
        r = icheck("--baseline-files", "docs/guide.md=" + "a" * 64)
        expect(r.returncode == 2 and "--derive" in r.stderr and "Traceback" not in r.stderr,
               f"--baseline-files without --derive must exit 2: {r.returncode} {r.stderr!r}")
        # Input boundary: the producer rejects a path it cannot verify (absolute/`..`/unreadable).
        r = subprocess.run([sys.executable, str(script), "baseline", "--repo", str(irepo),
                            "--files", "../outside.md"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        expect(r.returncode == 2 and "error:" in r.stderr and "Traceback" not in r.stderr,
               f"the baseline subcommand must reject an escaping path: "
               f"{r.returncode} {r.stderr!r}")
        # Unit: normalization keeps order, unifies separators, drops duplicates and `./`.
        expect(vd.normalize_path_list(["a\\b.md", "a/b.md", "./c.md"]) == (["a/b.md", "c.md"], []),
               "normalize_path_list must unify separators and deduplicate")
        expect(vd.normalize_path_list([]) == ([], []), "an empty baseline list is legitimate")
        expect(vd.parse_baseline_entries([]) == ({}, []),
               "an empty baseline list is legitimate for the state parser too")
        expect(vd.parse_baseline_entries(["a\\b.md=" + "A" * 64])
               == ({"a/b.md": "a" * 64}, []),
               "parse_baseline_entries must normalize separators and lowercase the state")
        r = subprocess.run([sys.executable, str(script), "check", "--help"],
                           capture_output=True, text=True)
        expect(r.returncode == 0 and "--baseline-files" in r.stdout,
               f"--baseline-files must be discoverable in --help: {r.stdout[:400]!r}")
        r = subprocess.run([sys.executable, str(script), "baseline", "--help"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        expect(r.returncode == 0 and "path=state" in r.stdout,
               f"the baseline subcommand must be discoverable in --help: {r.stdout[:400]!r}")

        # 30. Regression (C39): snapshot/check --files must be confined to the repository —
        #     absolute paths and `..` traversal are usage errors (exit 2) rejected BEFORE any
        #     read or write: a snapshot of `../outside.md` reads outside --repo and writes
        #     outside the baseline, and an absolute entry makes `baseline / rel` the absolute
        #     path itself (a WRITE target outside the baseline).
        confined_repo = root / "confined-repo"
        (confined_repo / "docs").mkdir(parents=True)
        (confined_repo / "docs" / "c.md").write_text("doc\n", encoding="utf-8")
        outside_md = root / "outside.md"
        outside_md.write_text("secret\n", encoding="utf-8")
        confined_base = root / "confined-base"
        for cmd in ("snapshot", "check"):
            for bad in ("../outside.md", str(outside_md.resolve()), "docs/../../outside.md"):
                r = subprocess.run([sys.executable, str(script), cmd, "--repo",
                                    str(confined_repo), "--baseline", str(confined_base),
                                    "--files", "docs/c.md", bad],
                                   capture_output=True, text=True)
                expect(r.returncode == 2 and "error:" in r.stderr
                       and "Traceback" not in r.stderr,
                       f"{cmd} must reject {bad!r} with exit 2 before any read/write: "
                       f"{r.returncode} {r.stderr!r}")
        expect(not confined_base.exists(),
               "a rejected snapshot must not write anything into the baseline")
        expect(outside_md.read_text(encoding="utf-8") == "secret\n",
               "an absolute --files entry must never be used as a read/write target")
        # ... while plain repository-relative paths still snapshot and check fine.
        r = subprocess.run([sys.executable, str(script), "snapshot", "--repo",
                            str(confined_repo), "--baseline", str(confined_base),
                            "--files", "docs/c.md"], capture_output=True, text=True)
        expect(r.returncode == 0 and (confined_base / "docs" / "c.md").is_file(),
               f"a confined snapshot must still work: {r.returncode} {r.stderr!r}")
        r = subprocess.run([sys.executable, str(script), "check", "--repo",
                            str(confined_repo), "--baseline", str(confined_base),
                            "--files", "docs/c.md"], capture_output=True, text=True)
        expect(r.returncode == 0,
               f"a confined check must still work: {r.returncode} {r.stderr!r}")

    print("PASS - documentation validator allows only documentation-only changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
