#!/usr/bin/env python3
"""
Deterministic self-test for `skill_base.py` (zero LLM tokens).

Verifies: content hashing (file and folder), the `--repo` anchor of local hashing (a relative path is
resolved against the DECLARED repository root, never against the process working directory), manifest
record/reuse/update (including recording a `--resolved-hash` materialization and rejecting a divergent
one), the documented CLI of every subcommand, and the missing-skill error contract for
`reference_skills`.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import skill_base as sb


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        base = root / "skill-base"

        # 1. init creates a manifest.
        base.mkdir()
        sb.cmd_init(base)
        expect((base / "manifest.json").is_file(), "init must create manifest.json")

        # 2. File hash is deterministic and content-sensitive.
        f = root / "doc.md"
        f.write_text("# Book\n", encoding="utf-8")
        h1 = sb.hash_path(f)
        expect(h1 == sb.hash_path(f), "file hash must be deterministic")
        f.write_text("# Book 2\n", encoding="utf-8")
        expect(h1 != sb.hash_path(f), "file hash must change with content")

        # 3. Folder hash is deterministic and content-sensitive.
        d = root / "folder"
        d.mkdir()
        (d / "a.md").write_text("a\n", encoding="utf-8")
        fh1 = sb.hash_path(d)
        expect(fh1 == sb.hash_path(d), "folder hash must be deterministic")
        (d / "b.md").write_text("b\n", encoding="utf-8")
        expect(fh1 != sb.hash_path(d), "folder hash must change with content")

        # 4. record -> manifest entry with required fields.
        h = sb.hash_path(f)
        manifest = sb.load_manifest(base)
        sb.save_manifest(base, manifest)  # ensure helpers usable
        # use the CLI-level handler directly
        ns = argparse.Namespace(base=str(base), name="mm", source="doc.md", hash=h, task_id="3")
        sb.cmd_record(ns)
        entry = sb.load_manifest(base)["skills"]["mm"]
        for k in ("name", "source", "sha256", "created_at", "last_used", "task_ids"):
            expect(k in entry, f"record must store '{k}'")
        expect(entry["task_ids"] == ["3"], "record must store task id")

        # 5. lookup: reuse (same hash), update (different hash), found (no hash), missing (exit 1).
        ns = argparse.Namespace(base=str(base), name="mm", hash=h)
        expect(sb.cmd_lookup(ns) == 0, "lookup same-hash must exit 0")
        ns = argparse.Namespace(base=str(base), name="mm", hash="0" * 64)
        expect(sb.cmd_lookup(ns) == 0, "lookup different-hash must exit 0")
        ns = argparse.Namespace(base=str(base), name="mm", hash=None)
        expect(sb.cmd_lookup(ns) == 0, "lookup without hash must exit 0")
        ns = argparse.Namespace(base=str(base), name="nope", hash=None)
        expect(sb.cmd_lookup(ns) == 1, "lookup missing skill must exit 1 (reference_skills error)")

        # 6. re-record same name appends task id and bumps last_used.
        ns = argparse.Namespace(base=str(base), name="mm", source="doc.md", hash=h, task_id="5")
        sb.cmd_record(ns)
        entry = sb.load_manifest(base)["skills"]["mm"]
        expect(entry["task_ids"] == ["3", "5"], "re-record must append task id, not duplicate")

        # 7. `hash --repo` anchors a relative local path to the DECLARED repository root.
        # A same-named file next to the working directory must never be hashed instead.
        other = root / "elsewhere"
        other.mkdir()
        anchored_doc = root / "anchored.md"
        anchored_doc.write_text("# Anchored\n", encoding="utf-8")
        decoy = other / "anchored.md"
        decoy.write_text("# Decoy\n", encoding="utf-8")
        cwd = pathlib.Path.cwd()
        try:
            os.chdir(other)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                expect(sb.cmd_hash(argparse.Namespace(path="anchored.md", repo=str(root))) == 0,
                       "hash must accept a relative path anchored at --repo")
        finally:
            os.chdir(cwd)
        expect(printed.getvalue().strip() == sb.hash_path(anchored_doc),
               "a relative path must be hashed from the declared repo root, not the working directory")
        expect(printed.getvalue().strip() != sb.hash_path(decoy),
               "the same-named file next to the working directory must not be hashed")

        script = pathlib.Path(__file__).resolve().parent / "skill_base.py"
        cli_hash = subprocess.run([sys.executable, str(script), "--repo", str(root), "hash",
                                   "anchored.md"], cwd=str(other), capture_output=True, text=True,
                                  errors="replace")
        expect(cli_hash.returncode == 0 and cli_hash.stdout.strip() == sb.hash_path(anchored_doc),
               f"the hash CLI must anchor a relative path at --repo from any cwd: {cli_hash.stderr}")

        # 8. `record --resolved-hash` records that digest and REFUSES a divergent materialization.
        resolved_doc = root / "resolved.md"
        resolved_doc.write_text("# Resolved\n", encoding="utf-8")
        resolved_hash = sb.hash_path(resolved_doc)
        ns = argparse.Namespace(base=str(base), name="res", source="resolved.md", hash="0" * 64,
                                task_id="8", resolved_hash=resolved_hash, repo=str(root))
        expect(sb.cmd_record(ns) == 0, "record must accept the resolved hash of an anchored path")
        entry = sb.load_manifest(base)["skills"]["res"]
        expect(entry["sha256"] == resolved_hash,
               "record must store the resolved digest, not the stale caller hash")
        before = json.dumps(entry, sort_keys=True)
        resolved_doc.write_text("# Resolved, changed after the resolve\n", encoding="utf-8")
        try:
            sb.cmd_record(ns)
            raise AssertionError("recording a divergent materialization must be refused")
        except sb.SourceError as exc:
            expect("divergen" in str(exc).lower(),
                   f"a refused record must say the materialization diverged (got: {exc})")
        expect(json.dumps(sb.load_manifest(base)["skills"]["res"], sort_keys=True) == before,
               "a refused record must leave the manifest untouched")

        # 9. The documented `record` command carries the repository flag and the resolved-hash
        # contract (a documented command that omits the anchor re-creates finding F8/F10).
        usage = next(line for line in (sb.__doc__ or "").splitlines() if " record " in line)
        expect("[--repo <root>]" in usage and "--resolved-hash" in usage,
               f"the documented record command must carry --repo and --resolved-hash: {usage.strip()}")

    print("PASS - skill_base hashing, repo anchoring, resolved-hash recording, manifest, reuse and "
          "error contract behave as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
