#!/usr/bin/env python3
"""
Deterministic self-test for `skill_base.py` (zero LLM tokens).

Verifies: content hashing (file and folder), the `--repo` anchor of local hashing (a relative path is
resolved against the DECLARED repository root, never against the process working directory), manifest
record/reuse/update (including recording a `--resolved-hash` materialization and rejecting a divergent
one), the documented CLI of every subcommand, the missing-skill error contract for
`reference_skills`, the cache-failure contract of `resolve` (exit 1, a message naming the
source and the reason, never a traceback), the PUBLIC-destination guard of remote sources
(loopback / private / link-local / cloud-metadata addresses and a DNS name resolving to one are
rejected for the initial URL and every redirect hop — hermetically, with an injected resolver) and
the `--timeout` / `--max-bytes` usage-error contract (a non-finite or non-positive timeout and a
non-positive or overflowing byte cap are exit 2 BEFORE any transfer).

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
import urllib.request

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

        # 10. An unusable cache directory is a message naming the source and the reason, never a
        # traceback: a regular file occupies the cache path, so the first cache write must fail
        # with exit 1 and `error: ... <source> ... cannot write the cache ...` on stderr.
        cache_repo = root / "cache-repo"
        blocker = cache_repo / sb.CACHE_SUBDIR
        blocker.parent.mkdir(parents=True)
        blocker.write_text("occupied\n", encoding="utf-8")
        source = "https://example.invalid/doc.md"
        res = subprocess.run([sys.executable, str(script), "--repo", str(cache_repo),
                              "resolve", source], capture_output=True, text=True, errors="replace")
        expect(res.returncode == 1,
               f"resolve with an unusable cache must exit 1: {res.returncode} {res.stdout!r}")
        expect("Traceback" not in res.stderr,
               f"a failure is a message, never a traceback: {res.stderr!r}")
        expect(source in res.stderr and "cannot write the cache" in res.stderr,
               f"the message must name the source and the reason: {res.stderr!r}")
        expect(res.stdout.strip() == "", f"a failed resolve must print no JSON: {res.stdout!r}")

        # 11. PUBLIC destination guard (hermetic: the resolver is injected, nothing touches the
        #     network). A literal IP is its own resolution; a DNS name is rejected when ANY
        #     resolved address is not globally routable, and an unresolvable host is rejected
        #     because a destination that cannot be checked is not a public source.
        def fake_resolver(mapping: dict) -> callable:
            def resolve(host: str, port) -> list:
                if host not in mapping:
                    raise OSError(f"name or service not known: {host}")
                return mapping[host]
            return resolve

        public = fake_resolver({"docs.example": ["93.184.216.34"]})
        sb._validate_destination("https://docs.example/guide.md", "test URL", resolve=public)
        sb._validate_destination("http://93.184.216.34/guide.md", "test URL")
        for bad_url, resolver in (
            ("http://127.0.0.1/doc.md", None),                      # loopback
            ("http://[::1]/doc.md", None),                          # loopback v6
            ("http://10.0.0.7/doc.md", None),                       # private
            ("http://192.168.1.1/doc.md", None),                    # private
            ("http://169.254.169.254/latest/meta-data", None),      # cloud metadata
            ("http://[fe80::1]/doc.md", None),                      # link-local v6
            ("https://internal.example/doc.md",
             fake_resolver({"internal.example": ["10.1.2.3"]})),    # DNS -> private
            ("https://mixed.example/doc.md",
             fake_resolver({"mixed.example": ["93.184.216.34", "192.168.0.1"]})),
        ):
            try:
                sb._validate_destination(bad_url, "test URL", resolve=resolver)
                raise AssertionError(f"a non-public destination must be rejected: {bad_url}")
            except sb.SourceError as exc:
                expect("non-public" in str(exc), f"the reason must say non-public: {exc}")
        try:
            sb._validate_destination("https://gone.example/doc.md", "test URL", resolve=public)
            raise AssertionError("an unresolvable host must be rejected")
        except sb.SourceError:
            pass

        # Every redirect hop is re-validated with the SAME resolver: a public source must not jump
        # to a loopback, a private DNS name or another scheme half way through a fetch.
        handler = sb._ValidatingRedirectHandler(resolve=public)
        request = urllib.request.Request("https://docs.example/start")
        for newurl in ("http://127.0.0.1:8080/admin", "https://internal.example/x",
                       "file:///etc/passwd"):
            try:
                handler.redirect_request(request, None, 302, "Found", {}, newurl)
                raise AssertionError(f"a redirect to {newurl} must be refused")
            except sb.SourceError:
                pass
        redirected = handler.redirect_request(request, None, 302, "Found", {},
                                              "https://docs.example/next")
        expect(redirected is not None and redirected.full_url == "https://docs.example/next",
               "a redirect to a public target must be followed")
        # End to end, still offline: a loopback source is refused before any socket is opened.
        try:
            sb.resolve_source("http://127.0.0.1:9/doc.md", cache=root / "cache-guard")
            raise AssertionError("resolving a loopback source must be refused")
        except sb.SourceError as exc:
            expect("non-public" in str(exc), f"the refusal must say non-public: {exc}")

        # 11b. REGRESSION (review R1, critical 36): the guard's resolution is the CONNECTION's
        #      resolution — pinning the validated address closes the DNS-rebinding window (the
        #      guard used to resolve, then `opener.open` resolved AGAIN for the real connection, so
        #      a second answer could be a private one). Proven hermetically: the resolver is
        #      injected, the dial seam is recorded, and no socket is ever opened.
        class _Answer:
            """A resolver that answers differently on each call (a rebinding attacker)."""

            def __init__(self, answers: list[list[str]]) -> None:
                self.answers = answers
                self.calls: list[str] = []

            def __call__(self, host: str, port) -> list[str]:
                self.calls.append(host)
                index = min(len(self.calls) - 1, len(self.answers) - 1)
                return self.answers[index]

        rebinding = _Answer([["93.184.216.34"], ["10.1.2.3"]])
        address = sb._validate_destination("https://docs.example/guide.md", "test URL",
                                           resolve=rebinding)
        expect(address == "93.184.216.34",
               f"the validated address must be RETURNED so the connection can pin it: {address!r}")
        expect(len(rebinding.calls) == 1,
               f"one resolution must serve the check and the connection: {rebinding.calls!r}")

        original_connect = sb._connect_to
        dialled: list[tuple] = []

        def recording_connect(target: str, port, timeout, source_address=None):
            dialled.append((target, port))
            raise OSError("the test never opens a socket")

        sb._connect_to = recording_connect
        try:
            with tempfile.TemporaryDirectory() as pin_dir:
                # ONE resolution per hop: the second, private answer of this resolver is never
                # asked for, and the socket dials the public address the guard validated.
                transfer = _Answer([["93.184.216.34"], ["10.1.2.3"]])
                try:
                    sb._download_doc("https://docs.example/guide.md", pathlib.Path(pin_dir),
                                     max_bytes=1024, timeout=5, resolve=transfer)
                except sb.SourceError:
                    pass                      # the dial was refused by the recording seam
                expect(len(transfer.calls) == 1,
                       f"the transfer must resolve the host exactly ONCE: {transfer.calls!r}")
                expect(dialled and dialled[0][0] == "93.184.216.34",
                       f"the transport must dial the VALIDATED address, never re-resolve the host: "
                       f"{dialled!r}")
                expect(all(entry[0] != "10.1.2.3" for entry in dialled),
                       f"a second, private DNS answer must never reach the socket: {dialled!r}")

                # Guard and transport disagreeing the other way round: the guard's answer is
                # private, so nothing may be dialled at all.
                dialled.clear()
                try:
                    sb._download_doc("https://docs.example/private.md", pathlib.Path(pin_dir),
                                     max_bytes=1024, timeout=5,
                                     resolve=fake_resolver({"docs.example": ["10.9.9.9"]}))
                except sb.SourceError as exc:
                    expect("non-public" in str(exc), f"the refusal must say non-public: {exc}")
                else:
                    raise AssertionError("a private destination must be refused before any transfer")
                expect(dialled == [],
                       f"a non-public destination must open NO socket: {dialled!r}")
        finally:
            sb._connect_to = original_connect

        # 12. --timeout / --max-bytes are validated BEFORE any transfer: a non-finite or
        #     non-positive timeout and a non-positive or overflowing byte cap are usage errors
        #     (exit 2), never an uncaught ValueError deep in the transfer machinery. A local
        #     source keeps the CLI hermetic.
        for bad in (("--timeout", "-5"), ("--timeout", "0"), ("--timeout", "nan"),
                    ("--timeout", "inf"), ("--max-bytes", "0"), ("--max-bytes", "-1"),
                    ("--max-bytes", str(sys.maxsize))):
            res = subprocess.run([sys.executable, str(script), "hash", str(f), *bad],
                                 capture_output=True, text=True, errors="replace")
            expect(res.returncode == 2 and "Traceback" not in res.stderr,
                   f"{bad} must be a usage error (exit 2): {res.returncode} {res.stderr!r}")
        res = subprocess.run([sys.executable, str(script), "hash", str(f),
                              "--timeout", "5", "--max-bytes", str(sys.maxsize - 1)],
                             capture_output=True, text=True, errors="replace")
        expect(res.returncode == 0 and res.stdout.strip() == sb.hash_path(f),
               f"valid limits must pass: {res.returncode} {res.stderr!r}")

    print("PASS - skill_base hashing, repo anchoring, resolved-hash recording, manifest, reuse, "
          "cache-failure reporting (a message, never a traceback), the public-destination guard "
          "(loopback/private/link-local rejected on the source and every redirect hop), the "
          "--timeout/--max-bytes usage-error contract and error contract behave as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
