#!/usr/bin/env python3
"""
Deterministic skill-base manager for `reference_docs` / `reference_skills` (zero LLM tokens).

Persistent, committable base at `skill-base/` with a manifest that tracks every generated skill:
name, source, sha256, created_at, last_used, task_ids. Freshness is decided ONLY by the SHA-256 of
the source content (equal -> reuse, different -> update), never by the LLM.

Usage (`--base` is a TOP-LEVEL option, so it must precede the subcommand):
  python3 skill_base.py [--base skill-base] init
  python3 skill_base.py hash <path>                                     # SHA-256 of a file/folder
  python3 skill_base.py [--base skill-base] lookup <name> [--hash <hex>] # reuse|update|found|missing
  python3 skill_base.py [--base skill-base] record <name> <source> <hash> [--task-id <id>]
  python3 skill_base.py [--base skill-base] list

`lookup` exits 1 for a missing skill (the reference_skills error contract). stdlib only.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_path(p: pathlib.Path) -> str:
    """Deterministic content hash of a file or a folder."""
    if p.is_file():
        return _sha256_bytes(p.read_bytes())
    if p.is_dir():
        parts: list[bytes] = []
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            rel = f.relative_to(p).as_posix()
            parts.append(rel.encode("utf-8"))
            parts.append(b"\0")
            parts.append(f.read_bytes())
            parts.append(b"\0")
        return _sha256_bytes(b"".join(parts))
    raise SystemExit(f"hash: not a file or directory: {p}")


def load_manifest(base: pathlib.Path) -> dict:
    mf = base / "manifest.json"
    if not mf.is_file():
        return {"skills": {}}
    return json.loads(mf.read_text(encoding="utf-8"))


def save_manifest(base: pathlib.Path, manifest: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def cmd_init(base: pathlib.Path) -> int:
    base.mkdir(parents=True, exist_ok=True)
    mf = base / "manifest.json"
    if not mf.is_file():
        save_manifest(base, {"skills": {}})
    print(f"skill base ready: {mf}")
    return 0


def cmd_hash(args) -> int:
    print(hash_path(pathlib.Path(args.path).resolve()))
    return 0


def cmd_lookup(args) -> int:
    manifest = load_manifest(pathlib.Path(args.base).resolve())
    entry = manifest["skills"].get(args.name)
    if entry is None:
        print(f"missing: skill '{args.name}' not found in the base; "
              f"specify the path to the document in reference_docs", file=sys.stderr)
        return 1
    if args.hash:
        if entry["sha256"] == args.hash:
            print("reuse")
        else:
            print("update")
    else:
        print(f"found {entry['sha256']}")
    return 0


def cmd_record(args) -> int:
    base = pathlib.Path(args.base).resolve()
    manifest = load_manifest(base)
    now = _now()
    existing = manifest["skills"].get(args.name)
    if existing:
        existing.update({
            "source": args.source,
            "sha256": args.hash,
            "last_used": now,
        })
        if args.task_id and args.task_id not in existing.get("task_ids", []):
            existing.setdefault("task_ids", []).append(args.task_id)
    else:
        manifest["skills"][args.name] = {
            "name": args.name,
            "source": args.source,
            "sha256": args.hash,
            "created_at": now,
            "last_used": now,
            "task_ids": [args.task_id] if args.task_id else [],
        }
    save_manifest(base, manifest)
    print(json.dumps(manifest["skills"][args.name], ensure_ascii=False))
    return 0


def cmd_list(args) -> int:
    manifest = load_manifest(pathlib.Path(args.base).resolve())
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def use_utf8_output() -> None:
    """Force UTF-8 on stdout/stderr so the help and printed names/paths survive a legacy console.

    A Windows console defaults to a legacy code page (cp866/cp1251), which cannot encode every
    character this manager prints (a skill name, a document path, the argparse help): printing
    them would raise UnicodeEncodeError and the user would get a traceback instead of the output.
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
    ap.add_argument("--base", default="skill-base", help="Skill-base directory (default: skill-base)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    ph = sub.add_parser("hash")
    ph.add_argument("path")

    pl = sub.add_parser("lookup")
    pl.add_argument("name")
    pl.add_argument("--hash")

    pr = sub.add_parser("record")
    pr.add_argument("name")
    pr.add_argument("source")
    pr.add_argument("hash")
    pr.add_argument("--task-id")

    sub.add_parser("list")

    args = ap.parse_args()
    handlers = {
        "init": lambda: cmd_init(pathlib.Path(args.base).resolve()),
        "hash": lambda: cmd_hash(args),
        "lookup": lambda: cmd_lookup(args),
        "record": lambda: cmd_record(args),
        "list": lambda: cmd_list(args),
    }
    return handlers[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
