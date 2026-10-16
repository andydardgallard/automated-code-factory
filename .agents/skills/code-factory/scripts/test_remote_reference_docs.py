#!/usr/bin/env python3
"""
Deterministic OFFLINE self-test for the remote `reference_docs` support of `skill_base.py`.

Everything runs against LOOPBACK fixtures only: a local `http.server` publishing Markdown/HTML and
a local smart-HTTP Git server backed by `git http-backend` on 127.0.0.1. The default suite never
touches the internet, so it stays fast and reproducible.

Verifies: source classification (local / http_doc / http_git and the rejected schemes and
credential URLs), HTTP materialization into `<repo>/.code-factory/cache/reference-docs/`, the
create -> reuse -> update lifecycle, redirect re-validation, download size and timeout limits,
offline/stale reuse after the source stops, Git materialization (shallow clone, `.git` exclusion,
fresh-clone hash stability, resolved revision), manifest backward compatibility and the
`resolve` / `hash` / `record` CLI contract for URLs.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

import skill_base as sb

SCRIPT = pathlib.Path(__file__).resolve().parent / "skill_base.py"
SLOW_SECONDS = 5.0


class Check:
    """Assertion counter: a failing check reports what was expected and fails the whole test."""

    def __init__(self) -> None:
        self.count = 0
        self.skips: list[str] = []

    def __call__(self, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)
        self.count += 1

    def skip(self, message: str) -> None:
        self.skips.append(message)
        print(f"SKIP - {message}")


class DocHandler(http.server.SimpleHTTPRequestHandler):
    """Static files plus the redirect and slow routes the fetch-limits tests need."""

    redirects: dict[str, str] = {}
    slow_routes: set[str] = set()
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, "": "text/markdown"}

    def log_message(self, *args) -> None:                 # keep the test output quiet
        pass

    def do_GET(self) -> None:
        route = urllib.parse.urlsplit(self.path).path
        if route in self.slow_routes:
            time.sleep(SLOW_SECONDS)                      # only a finite client timeout can end this
        target = self.redirects.get(route)
        if target is not None:
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            super().do_GET()
        except OSError:
            pass              # the client aborted the download (the size-cap test): a fixture artefact


class GitHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Minimal smart-HTTP Git server: every request is delegated to `git http-backend` (CGI)."""

    protocol_version = "HTTP/1.0"
    project_root = "."

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        self._backend()

    def do_POST(self) -> None:
        self._backend()

    def _backend(self) -> None:
        parts = urllib.parse.urlsplit(self.path)
        body = b""
        if self.command == "POST":
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        env = dict(os.environ)
        env.update({
            "GIT_PROJECT_ROOT": str(self.project_root),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": parts.path,
            "QUERY_STRING": parts.query,
            "REQUEST_METHOD": self.command,
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(len(body)),
            "REMOTE_ADDR": "127.0.0.1",
        })
        result = subprocess.run(["git", "http-backend"], input=body, capture_output=True, env=env)
        separator = b"\r\n\r\n" if b"\r\n\r\n" in result.stdout else b"\n\n"
        head, _, payload = result.stdout.partition(separator)
        status = 200
        headers: list[tuple[str, str]] = []
        for line in head.replace(b"\r\n", b"\n").split(b"\n"):
            name, _, value = line.partition(b":")
            if not line.strip():
                continue
            if name.lower() == b"status":
                status = int(value.split()[0])
            elif name.lower() != b"transfer-encoding":
                headers.append((name.decode(), value.strip().decode()))
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(handler, directory: pathlib.Path) -> http.server.ThreadingHTTPServer:
    """A loopback HTTP server on an ephemeral port; its threads die with the test."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(handler, directory=str(directory)))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def serve_git(root: pathlib.Path) -> http.server.ThreadingHTTPServer:
    handler = type("BoundGitHandler", (GitHTTPHandler,), {"project_root": str(root)})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def url_of(server: http.server.ThreadingHTTPServer, route: str) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}{route}"


def stop(server: http.server.ThreadingHTTPServer) -> None:
    """Stop accepting and CLOSE the listening socket — a simulated source outage.

    `shutdown()` alone leaves the socket open, so the kernel would still accept the next connection
    and never answer it: the client would then burn its whole timeout instead of seeing a refusal.
    """
    server.shutdown()
    server.server_close()


def cli(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, errors="replace")


def git(*args: str, cwd: pathlib.Path) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                            errors="replace", env=env)
    if result.returncode != 0:
        raise AssertionError(f"fixture: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def error_of(call) -> str:
    """The message of the SourceError a call must raise (a call that passes is a failure)."""
    try:
        call()
    except sb.SourceError as exc:
        return str(exc)
    raise AssertionError("expected a SourceError, nothing was raised")


def test_classification(check: Check, doc_url: str, git_url: str, plain_url: str) -> None:
    check(sb.classify_source("docs/book.md") == "local", "a relative path must classify as local")
    check(sb.classify_source(r"C:\docs\book.md") == "local", "a Windows path must classify as local")
    check(sb.classify_source(doc_url) == "http_doc", "an http(s) document URL must classify as http_doc")
    check(sb.classify_source(plain_url) == "http_doc", "a suffix-less document URL is still http_doc")
    check(sb.classify_source(git_url) == "http_git", "a URL ending in .git must classify as http_git")
    check(sb.classify_source("https://github.com/o/r.git") == "http_git",
          "a remote .git URL must classify as http_git")
    for rejected in ("ftp://host/doc.md", "file:///etc/doc.md", "ssh://git@host/r.git",
                     "git@github.com:o/r.git", "git://host/r.git"):
        message = error_of(lambda source=rejected: sb.classify_source(source))
        check(bool(message.strip()), f"rejecting {rejected} must explain why")
    for credentials in ("https://user:secret@127.0.0.1/doc.md", "http://token@127.0.0.1/r.git"):
        message = error_of(lambda source=credentials: sb.classify_source(source))
        check("credential" in message.lower(), f"a credential URL must be rejected ({credentials})")
        check("secret" not in message and "token" not in message,
              "a rejected URL must not leak its credentials into the log")


def test_documents(check: Check, root: pathlib.Path, server, www: pathlib.Path) -> tuple[str, str]:
    """The create -> reuse -> update lifecycle of an http_doc source; returns (url, hash)."""
    url = url_of(server, "/guide.md")
    cache = root / ".code-factory" / "cache" / "reference-docs"
    created, first_hash = sb.materialize_and_hash(url, repo=root)
    check(created.source_type == "http_doc", "a document URL must materialize as http_doc")
    check(cache in created.local_path.parents, "a remote source must land in the repo's cache")
    check(created.local_path.is_file() and created.local_path.suffix == ".md",
          "the cached document must keep a convertible extension")
    check(created.local_path.read_text(encoding="utf-8").startswith("# Guide"),
          "the cached document must hold the fetched content")
    check(not created.offline and not created.stale, "a fetched source is neither offline nor stale")
    check(not list(cache.rglob("*.part")), "a completed download must not leave a .part file")

    reused, reused_hash = sb.materialize_and_hash(url, repo=root)
    check(reused_hash == first_hash, "unchanged remote content must hash identically (reuse)")
    check(reused.local_path == created.local_path, "reuse must return the same cached path")

    (www / "guide.md").write_text("# Guide\n\nchanged upstream\n", encoding="utf-8")
    updated, updated_hash = sb.materialize_and_hash(url, repo=root)
    check(updated_hash != first_hash, "changed upstream content must change the hash (update)")
    check("changed upstream" in updated.local_path.read_text(encoding="utf-8"),
          "an update must replace the cached content")
    check(sb.hash_path(updated.local_path) == updated_hash,
          "the reported hash must be the hash_path of the materialized content")

    html_url = url_of(server, "/page.html")
    html, _ = sb.materialize_and_hash(html_url, repo=root)
    check(html.local_path.suffix == ".html", "an HTML source must keep its extension")
    typeless_url = url_of(server, "/no-extension")
    typeless, _ = sb.materialize_and_hash(typeless_url, repo=root)
    check(typeless.local_path.suffix == ".md",
          "a suffix-less URL must inherit the extension from its Content-Type")
    return url, updated_hash


def test_redirects(check: Check, root: pathlib.Path, server, doc_url: str) -> None:
    allowed = url_of(server, "/redirect.md")
    materialized, _ = sb.materialize_and_hash(allowed, repo=root)
    direct, _ = sb.materialize_and_hash(doc_url, repo=root)
    check(materialized.local_path.read_text(encoding="utf-8")
          == direct.local_path.read_text(encoding="utf-8"),
          "a redirect to another loopback path must deliver the target content")
    check(materialized.local_path != direct.local_path, "every URL keeps its own cache entry")

    denied = error_of(lambda: sb.materialize_and_hash(url_of(server, "/evil.md"), repo=root))
    check("scheme" in denied.lower() or "file://" in denied,
          f"a redirect to file:// must be rejected by re-validation (got: {denied})")
    credentials = error_of(lambda: sb.materialize_and_hash(url_of(server, "/creds.md"), repo=root))
    check("credential" in credentials.lower(),
          f"a redirect to a credential URL must be rejected (got: {credentials})")


def test_fetch_limits(check: Check, root: pathlib.Path, server, doc_url: str) -> None:
    size = error_of(lambda: sb.materialize_and_hash(doc_url, repo=root, max_bytes=10))
    check("limit" in size.lower(), f"the download size cap must be enforced (got: {size})")
    result = cli("--repo", str(root), "hash", doc_url, "--max-bytes", "10")
    check(result.returncode == 1 and "limit" in result.stderr.lower(),
          "the CLI must fail with an explicit reason when the size cap is hit")
    check(result.stdout.strip() == "", "a failed fetch must not print a hash")

    slow = url_of(server, "/slow.md")
    started = time.monotonic()
    message = error_of(lambda: sb.materialize_and_hash(slow, repo=root, timeout=1.0))
    elapsed = time.monotonic() - started
    check(elapsed < SLOW_SECONDS - 1, f"the fetch timeout must end the request early ({elapsed:.1f}s)")
    check("cannot resolve" in message and "127.0.0.1" in message,
          f"a failed fetch must name the source and the reason (got: {message})")


def test_cli(check: Check, root: pathlib.Path, base: pathlib.Path, doc_url: str, digest: str) -> None:
    resolved = cli("--repo", str(root), "resolve", doc_url)
    check(resolved.returncode == 0, f"resolve must exit 0 for a reachable source: {resolved.stderr}")
    payload = json.loads(resolved.stdout)
    for key in ("source", "source_type", "local_path", "sha256", "resolved_revision", "offline",
                "stale"):
        check(key in payload, f"resolve must report '{key}'")
    check(payload["source"] == doc_url, "resolve must echo the canonical original URL")
    check(payload["sha256"] == digest, "resolve must report the content hash")
    check(payload["offline"] is False and payload["stale"] is False,
          "a fetched source must not be reported offline or stale")

    after_subcommand = cli("resolve", doc_url, "--repo", str(root))
    check(after_subcommand.returncode == 0 and json.loads(after_subcommand.stdout)["local_path"],
          "--repo must also be accepted after the subcommand")

    hashed = cli("--repo", str(root), "--base", str(base), "hash", doc_url)
    check(hashed.returncode == 0 and hashed.stdout.strip() == digest,
          "hash must accept a URL and print the fetched content hash")

    recorded = cli("--repo", str(root), "--base", str(base), "record", "guide", doc_url, "0" * 64,
                   "--task-id", "2")
    check(recorded.returncode == 0, f"record must accept a URL: {recorded.stderr}")
    entry = sb.load_manifest(base)["skills"]["guide"]
    check(entry["source"] == doc_url, "the manifest must keep the canonical original URL as source")
    check(entry["sha256"] == digest, "the manifest must store the fetched content hash")
    check(entry["source_type"] == "http_doc", "the manifest must record the source type")
    check("resolved_revision" in entry, "a remote manifest entry carries resolved_revision")
    check(entry["task_ids"] == ["2"], "record must keep the task id")
    check("0" * 64 not in json.dumps(entry), "a wrong caller hash must not be stored as the signature")
    check("not the content hash" in recorded.stderr, "a wrong caller hash must be reported")

    looked_up = cli("--base", str(base), "lookup", "guide", "--hash", digest)
    check(looked_up.returncode == 0 and looked_up.stdout.strip() == "reuse",
          "lookup of an unchanged URL source must report reuse")
    stale = cli("--base", str(base), "lookup", "guide", "--hash", "1" * 64)
    check(stale.stdout.strip() == "update", "lookup of changed content must report update")

    local_file = root / "local-note.md"
    local_file.write_text("# Local note\n", encoding="utf-8")
    local = cli("--repo", str(root), "resolve", local_file.name)
    check(local.returncode == 0, f"resolve must accept a local path: {local.stderr}")
    check(json.loads(local.stdout)["source_type"] == "local",
          "a relative local path stays local and is anchored to --repo")
    check(json.loads(local.stdout)["local_path"] == str(local_file.resolve()),
          "--repo must anchor a relative local source")


def test_offline(check: Check, root: pathlib.Path, base: pathlib.Path, server, doc_url: str,
                 digest: str) -> None:
    stop(server)                    # the source goes away: the cache is now the only content left
    failure = error_of(lambda: sb.materialize_and_hash(doc_url, repo=root, timeout=2.0))
    check(doc_url in failure, f"a failed fetch must report its source (got: {failure})")
    check(sb.load_manifest(base)["skills"]["remote"]["source"] == doc_url,
          "a source outage must not change what the manifest already recorded")

    blocked = cli("--repo", str(root), "hash", doc_url)
    check(blocked.returncode == 1 and doc_url in blocked.stderr,
          "without a usable cache the CLI must exit non-zero and name the source")

    offline = cli("--repo", str(root), "resolve", doc_url, "--offline")
    check(offline.returncode == 0, f"--offline must reuse the cache: {offline.stderr}")
    payload = json.loads(offline.stdout)
    check(payload["offline"] is True and payload["stale"] is True,
          "offline reuse must be marked offline AND stale")
    check(payload["sha256"] == digest, "offline reuse must report the cached content hash")

    stale = cli("--repo", str(root), "resolve", doc_url, "--allow-stale")
    check(stale.returncode == 0 and json.loads(stale.stdout)["stale"] is True,
          "--allow-stale must reuse the cache and mark it stale")
    check("was NOT fetched" in stale.stderr, "stale reuse must say the source was not fetched")

    unknown = cli("--repo", str(root), "resolve", "http://127.0.0.1:9/never.md", "--offline")
    check(unknown.returncode == 1 and "no cached copy" in unknown.stderr,
          "--offline without any cached copy must fail, not invent content")


def test_git(check: Check, root: pathlib.Path, www: pathlib.Path) -> None:
    """A local Git repository served over loopback smart HTTP: clone, hash, update, offline."""
    seed = root / "seed"
    git("init", "-q", "-b", "main", str(seed), cwd=root)
    (seed / "readme.md").write_text("# Repo\n", encoding="utf-8")
    (seed / "docs").mkdir()
    (seed / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    git("-c", "user.email=t@example.test", "-c", "user.name=t", "add", "-A", cwd=seed)
    git("-c", "user.email=t@example.test", "-c", "user.name=t", "commit", "-qm", "init", cwd=seed)
    bare = www / "repo.git"
    git("clone", "-q", "--bare", str(seed), str(bare), cwd=root)
    server = serve_git(www)
    try:
        url = url_of(server, "/repo.git")
        materialized, first_hash = sb.materialize_and_hash(url, repo=root)
        check(materialized.source_type == "http_git", "a .git URL must materialize as http_git")
        check(materialized.local_path.is_dir(), "a Git source must materialize as a folder")
        check(not (materialized.local_path / ".git").exists(),
              "the resolved folder must not contain .git")
        check(re.fullmatch(r"[0-9a-f]{40}", materialized.resolved_revision or ""),
              "a Git source must report the resolved commit sha")
        names = sorted(p.relative_to(materialized.local_path).as_posix()
                       for p in materialized.local_path.rglob("*") if p.is_file())
        check(names == ["docs/a.md", "readme.md"],
              f"only reference content may be hashed, got {names}")

        manual = root / "manual"
        git("clone", "-q", "--depth", "1", url, str(manual), cwd=root)
        check(sb.hash_path(manual) != first_hash,
              "a clone that still contains .git must hash differently (.git is excluded)")

        cloned_again, second_hash = sb.materialize_and_hash(url, repo=root)
        check(second_hash == first_hash, "a second resolution must reuse the same content hash")
        sb.remove_tree(root / ".code-factory" / "cache" / "reference-docs")
        fresh, fresh_hash = sb.materialize_and_hash(url, repo=root)
        check(fresh_hash == first_hash,
              "a fresh clone in a fresh cache must hash identically (clone/platform stability)")

        limited = error_of(lambda: sb.materialize_and_hash(url, repo=root, max_bytes=1))
        check("limit" in limited.lower(), f"the clone size cap must be enforced (got: {limited})")

        (seed / "docs" / "b.md").write_text("b\n", encoding="utf-8")
        git("-c", "user.email=t@example.test", "-c", "user.name=t", "add", "-A", cwd=seed)
        git("-c", "user.email=t@example.test", "-c", "user.name=t", "commit", "-qm", "second", cwd=seed)
        git("push", "-q", str(bare), "main", cwd=seed)
        updated, updated_hash = sb.materialize_and_hash(url, repo=root)
        check(updated_hash != first_hash, "a new upstream commit must change the content hash")
        check(updated.resolved_revision != materialized.resolved_revision,
              "a new upstream commit must change the resolved revision")
        check((updated.local_path / "docs" / "b.md").is_file(),
              "an incremental update must contain the new upstream file")
    finally:
        stop(server)

    offline = sb.materialize_and_hash(url, repo=root, offline=True)
    check(offline[0].stale is True and offline[0].offline is True,
          "an offline Git resolution must be marked offline AND stale")
    check(offline[0].stale is True and offline[0].resolved_revision,
          "offline Git reuse must keep the persisted resolved revision")


def test_manifest_compatibility(check: Check, root: pathlib.Path, base: pathlib.Path,
                                doc_url: str) -> None:
    legacy = {
        "skills": {
            "old": {
                "name": "old", "source": "docs/old.md", "sha256": "a" * 64,
                "created_at": "2020-01-01T00:00:00+00:00", "last_used": "2020-01-01T00:00:00+00:00",
                "task_ids": ["1"],
            }
        }
    }
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    check(sb.load_manifest(base) == legacy, "an old manifest must load unchanged")

    local = root / "local.md"
    local.write_text("# Local\n", encoding="utf-8")
    namespace = argparse.Namespace(base=str(base), name="newlocal", source=str(local),
                                   hash=sb.hash_path(local), task_id="7")   # no repo/offline attrs
    check(sb.cmd_record(namespace) == 0, "record must still work for a local path without new flags")
    manifest = sb.load_manifest(base)
    check(manifest["skills"]["old"] == legacy["skills"]["old"], "a legacy entry must stay untouched")
    check("source_type" not in manifest["skills"]["newlocal"],
          "a local entry must not grow remote-only metadata")
    check(sb.cmd_lookup(argparse.Namespace(base=str(base), name="old", hash="a" * 64)) == 0,
          "lookup of a legacy entry must keep working")

    recorded = cli("--repo", str(root), "--base", str(base), "record", "remote", doc_url, "b" * 64)
    check(recorded.returncode == 0, f"recording a URL next to a legacy entry must work: {recorded.stderr}")
    manifest = sb.load_manifest(base)
    check(manifest["skills"]["old"] == legacy["skills"]["old"],
          "recording a remote source must not disturb the legacy entry")
    check(manifest["skills"]["remote"]["source_type"] == "http_doc",
          "the remote entry must carry its source type")


def run(check: Check, root: pathlib.Path) -> None:
    www = root / "www"
    www.mkdir()
    (www / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (www / "page.html").write_text("<h1>Page</h1>\n", encoding="utf-8")
    (www / "no-extension").write_text("# No extension\n", encoding="utf-8")
    (www / "slow.md").write_text("# Slow\n", encoding="utf-8")
    DocHandler.redirects = {"/redirect.md": "/guide.md", "/evil.md": "file:///etc/passwd"}
    DocHandler.slow_routes = {"/slow.md"}
    server = serve(DocHandler, www)
    doc_url = url_of(server, "/guide.md")
    try:
        DocHandler.redirects["/creds.md"] = f"http://user:secret@127.0.0.1:{server.server_address[1]}/guide.md"
        base = root / "skill-base"
        sb.cmd_init(base)
        test_classification(check, doc_url, url_of(server, "/repo.git"), url_of(server, "/no-extension"))
        fetch_url, digest = test_documents(check, root, server, www)
        test_redirects(check, root, server, doc_url)
        test_fetch_limits(check, root, server, doc_url)
        test_cli(check, root, base, fetch_url, digest)
        test_manifest_compatibility(check, root, base, fetch_url)
        test_offline(check, root, base, server, fetch_url, digest)
    finally:
        try:
            stop(server)
        except (AttributeError, OSError, ValueError):
            pass                      # the offline phase already closed this socket

    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        git_available = result.returncode == 0
    except OSError:
        git_available = False
    if git_available:
        test_git(check, root, www)
    else:
        check.skip("the git executable is unavailable: the Git-over-HTTP cases were not run")


def main() -> int:
    check = Check()
    with tempfile.TemporaryDirectory() as td:
        try:
            run(check, pathlib.Path(td))
        except AssertionError as exc:
            print(f"FAIL - {exc}")
            print(f"FAIL - {check.count} checks passed before the failure.")
            return 1
    print(f"PASS - {check.count} checks of the remote reference_docs contract behave as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
