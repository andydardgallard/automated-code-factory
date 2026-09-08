#!/usr/bin/env python3
"""
Deterministic self-test for `skill_base.py` (zero LLM tokens).

Verifies: content hashing (file and folder), manifest record/reuse/update, and the
missing-skill error contract for `reference_skills`.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import pathlib
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
        import argparse
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

    print("PASS - skill_base hashing, manifest, reuse and error contract behave as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
