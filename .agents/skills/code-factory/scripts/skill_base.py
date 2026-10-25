#!/usr/bin/env python3
"""
Deterministic skill-base manager for `reference_docs` / `reference_skills` (zero LLM tokens).

Persistent, committable base at `skill-base/` with a manifest that tracks every generated skill:
name, source, sha256, created_at, last_used, task_ids. Freshness is decided ONLY by the SHA-256 of
the source content (equal -> reuse, different -> update), never by the LLM.

`reference_docs[].path` may be a local file/folder OR a PUBLIC http(s) source: a document URL
(`http_doc`) or a Git repository URL (`http_git` — a URL ending in `.git`). Remote sources are
materialized into the resolved repository's uncommitted runtime cache
`<repo>/.code-factory/cache/reference-docs/` and are handled from then on exactly like a local
path. The `{path, skill}` task schema is unchanged: a URL is simply a new kind of `path` value.

Usage (`--base` and `--repo` are TOP-LEVEL options, so they must precede the subcommand):
  python3 skill_base.py [--base skill-base] init
  python3 skill_base.py [--base skill-base] [--repo <root>] resolve <path-or-url> [--offline]
  python3 skill_base.py [--base skill-base] [--repo <root>] hash <path-or-url>
  python3 skill_base.py [--base skill-base] lookup <name> [--hash <hex>] # reuse|update|found|missing
  python3 skill_base.py [--base skill-base] [--repo <root>] record <name> <source> <hash> [--resolved-hash <hex>] [--task-id <id>]
  python3 skill_base.py [--base skill-base] list

`resolve`, `hash` and `record` also accept the remote-source flags `--offline`, `--allow-stale`,
`--timeout <seconds>` (default 60) and `--max-bytes <n>` (default 67108864 — the download/clone cap).
The cap is enforced DURING a transfer too: a download is counted chunk by chunk, a clone is
supervised while its temporary tree grows, and crossing the cap aborts the transfer with an explicit
reason and removes the partial content.

`resolve` materializes a source (fetching/caching it when remote) and prints its metadata as JSON on
stdout: `source`, `source_type`, `local_path`, `sha256`, `resolved_revision`, `offline`, `stale`. A
fetch or cache failure is reported on stderr with the source and the reason and exits 1 — a failure
is a message, never a traceback. A cached copy is
reused ONLY when explicitly asked for with `--offline` (no network access at all) or `--allow-stale`
(fetch attempted, failed, cached copy used); it is then marked `stale: true`, because a cached copy
is never fresh remote content. `--repo <root>` (a synonym: `--root`) is the resolved repo_path of
the run: the cache lives under it and a RELATIVE source path is resolved against it — for `resolve`,
`hash` AND `record` alike (default: the caller's working directory, so nothing changes without the
flag).

`record` stores the signature of the materialization the skill was generated FROM: pass
`--resolved-hash <hex>` (the `sha256` that `resolve` printed) and the already materialized content is
recorded WITHOUT a second fetch. A materialization that no longer matches that digest is refused
with exit 1 instead of being described by a diverging hash — re-run `resolve` and regenerate the
skill in that case. Without the flag a URL is fetched first, exactly as before.

`lookup` exits 1 for a missing skill (the reference_skills error contract). stdlib only.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


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


def local_path_of(source: str, repo: str | pathlib.Path | None = None) -> pathlib.Path:
    """The absolute path of a LOCAL source: a relative one is anchored to the declared repo root.

    The single resolution contract of the whole tool: `resolve`, `hash` and `record` all reach a
    relative source through it, so a relative path never depends on the process working directory.
    """
    path = pathlib.Path(source)
    if repo and not path.is_absolute():
        path = pathlib.Path(repo) / path
    return path.resolve()


# --- remote `reference_docs` support ------------------------------------------------------------
#
# Public, unauthenticated http(s) sources only. Remote content is UNTRUSTED reference data: nothing
# of it is ever executed, no hooks run, no submodules and no LFS content are fetched, and a URL
# carrying credentials is rejected before it could reach a log, a manifest or a generated skill.

CACHE_SUBDIR = pathlib.Path(".code-factory") / "cache" / "reference-docs"
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 60.0
_ALLOWED_SCHEMES = ("http", "https")
_DOC_SUFFIXES = (".md", ".markdown", ".html", ".htm", ".txt", ".pdf", ".epub", ".docx")
_CONTENT_TYPE_SUFFIXES = {
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/pdf": ".pdf",
    "application/epub+zip": ".epub",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
_USER_AGENT = "code-factory-skill-base/1.0 (reference_docs)"
REPO_HELP = ("Resolved repo_path of the run: the remote-source cache lives under it and a RELATIVE "
             "source path is resolved against it (default: the caller's working directory)")
CLONE_POLL_SECONDS = 0.05          # how often a running clone's temporary tree is measured
_GIT_CONFIG = ("-c", f"core.hooksPath={os.devnull}",     # a downloaded hook must never run
               "-c", "core.autocrlf=false", "-c", "core.eol=lf",   # platform-independent content
               "-c", "core.symlinks=false", "-c", "core.fsmonitor=false",
               "-c", "credential.helper=")


class SourceError(RuntimeError):
    """A remote source that cannot be classified, fetched or reused safely (a clear message)."""


def _redact(source: str) -> str:
    """The source with any userinfo removed, so a rejected URL cannot leak a secret into a log."""
    try:
        parts = urllib.parse.urlsplit(str(source))
    except ValueError:
        return "<unparsable source>"
    if "@" in parts.netloc:
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[1], parts.path,
                                        parts.query, ""))
    return str(source)


def _validate_url(url: str, context: str) -> None:
    """A URL must be public http(s): no other scheme and no embedded credentials.

    Applied to the source itself AND to every redirect target, so an allowed source can never jump
    to `file://`, an unsupported scheme or a credentials-bearing URL half way through a fetch.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise SourceError(f"{context} is not a valid URL: {exc}") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SourceError(f"{context} uses the unsupported scheme '{scheme}://': only public "
                          f"http:// and https:// sources are supported ({_redact(url)})")
    if "@" in parts.netloc:
        raise SourceError(f"{context} carries embedded credentials, which are never allowed: only "
                          f"public, unauthenticated sources are supported ({_redact(url)})")
    if not parts.hostname:
        raise SourceError(f"{context} has no host ({_redact(url)})")


def classify_source(source: str) -> str:
    """`"local" | "http_doc" | "http_git"` for a `reference_docs` path; SourceError when rejected."""
    text = (source or "").strip()
    if not text:
        raise SourceError("empty reference_docs path")
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*)://", text)
    if match:
        scheme = match.group(1).lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise SourceError(f"reference_docs URL uses the unsupported scheme '{scheme}://': only "
                              f"public http:// and https:// sources are supported "
                              f"({_redact(text)})")
        _validate_url(text, context="reference_docs URL")
        path = urllib.parse.urlsplit(text).path.rstrip("/").lower()
        return "http_git" if path.endswith(".git") else "http_doc"
    scp_like = re.match(r"^[\w.\-]+@[\w.\-]+:(?P<tail>.+)$", text)
    if scp_like and ("/" in scp_like.group("tail") or scp_like.group("tail").endswith(".git")):
        raise SourceError("reference_docs source looks like an ssh/scp Git URL, which needs "
                          f"credentials: only public http(s) sources are supported ({_redact(text)})")
    return "local"


def canonical_url(source: str) -> str:
    """Cache identity of a URL: lowercase scheme/host, no fragment (never sent to a server)."""
    parts = urllib.parse.urlsplit(source.strip())
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/",
                                    parts.query, ""))


def cache_key(source: str) -> str:
    """Stable cache folder name of a URL, derived from its canonical form."""
    return _sha256_bytes(canonical_url(source).encode("utf-8"))[:16]


def cache_root(repo: str | pathlib.Path | None) -> pathlib.Path:
    """`<resolved repo root>/.code-factory/cache/reference-docs` — the uncommitted runtime cache."""
    root = pathlib.Path(repo).resolve() if repo else pathlib.Path.cwd()
    return root / CACHE_SUBDIR


@dataclasses.dataclass
class Materialized:
    """A `reference_docs` source ready to be hashed or turned into a skill."""
    source: str
    source_type: str
    local_path: pathlib.Path
    resolved_revision: str | None = None
    offline: bool = False
    stale: bool = False

    def to_dict(self, sha256: str | None = None) -> dict:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "local_path": str(self.local_path),
            "sha256": sha256,
            "resolved_revision": self.resolved_revision,
            "offline": self.offline,
            "stale": self.stale,
        }


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Auto-following handler that re-validates EVERY redirect target before it is followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        _validate_url(target, context="redirect target")
        return super().redirect_request(req, fp, code, msg, headers, target)


def _load_meta(cache: pathlib.Path, key: str) -> dict:
    try:
        data = json.loads((cache / "_meta" / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_meta(cache: pathlib.Path, key: str, data: dict) -> None:
    folder = cache / "_meta"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{key}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    except OSError as exc:
        raise SourceError(f"cannot write the cache: {exc}") from exc


def _doc_filename(url: str, content_type: str | None) -> str:
    """Stable file name of a downloaded document: the URL's name, or the content type's extension.

    The existing conversion rules pick the converter from the file extension, so a URL without a
    usable one (`/docs/getting-started`) has to inherit it from the response's Content-Type.
    """
    raw = pathlib.PurePosixPath(urllib.parse.urlsplit(url).path or "").name or "index"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")[:80] or "document"
    path = pathlib.PurePosixPath(name)
    if path.suffix.lower() in _DOC_SUFFIXES:
        return name
    return f"{path.stem or 'document'}{_CONTENT_TYPE_SUFFIXES.get((content_type or '').lower(), '.txt')}"


def _download_doc(url: str, folder: pathlib.Path, *, max_bytes: int, timeout: float) -> tuple[pathlib.Path, str | None]:
    """Download one document into `folder` (atomic: `body.part` is renamed only when complete)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SourceError(f"cannot write the cache: {exc}") from exc
    part = folder / "body.part"
    opener = urllib.request.build_opener(_ValidatingRedirectHandler())
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as resp:
            _validate_url(resp.geturl(), context="response URL")
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise SourceError(f"the source is larger than the {max_bytes} byte limit "
                                  f"({length} bytes advertised)")
            with part.open("wb") as out:
                total = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise SourceError(f"the download exceeded the {timeout:g}s time limit")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise SourceError(f"the download exceeded the {max_bytes} byte limit")
                    out.write(chunk)
            content_type = resp.headers.get_content_type()
    except SourceError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        part.unlink(missing_ok=True)
        raise SourceError(str(getattr(exc, "reason", None) or exc)) from exc
    filename = _doc_filename(url, content_type)
    try:
        part.replace(folder / filename)
        for other in folder.iterdir():                  # exactly one document per cache key
            if other.name != filename and other.is_file():
                other.unlink()
    except OSError as exc:
        raise SourceError(f"cannot write the cache: {exc}") from exc
    return folder / filename, content_type


def _cached_doc(folder: pathlib.Path, filename: str | None) -> pathlib.Path | None:
    if filename and (folder / filename).is_file():
        return folder / filename
    if folder.is_dir():
        files = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix != ".part")
        if len(files) == 1:
            return files[0]
    return None


def _materialize_http_doc(source: str, cache: pathlib.Path, *, max_bytes: int, timeout: float,
                          offline: bool) -> Materialized:
    key = cache_key(source)
    folder = cache / "http" / key
    if offline:
        cached = _cached_doc(folder, _load_meta(cache, key).get("filename"))
        if cached is None:
            raise SourceError(f"there is no cached copy of {_redact(source)} under {cache}, so it "
                              "cannot be resolved offline")
        return Materialized(source, "http_doc", cached, offline=True, stale=True)
    path, content_type = _download_doc(source, folder, max_bytes=max_bytes, timeout=timeout)
    _save_meta(cache, key, {"source": canonical_url(source), "source_type": "http_doc",
                            "filename": path.name, "content_type": content_type,
                            "fetched_at": _now()})
    return Materialized(source, "http_doc", path)


def _git_env(timeout: float) -> dict:
    """Environment that keeps the clone hermetic and non-interactive (never execute, never hang)."""
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"          # never fetch LFS content: reference data only
    env["GIT_TERMINAL_PROMPT"] = "0"          # fail instead of blocking on a credential prompt
    env["GIT_ASKPASS"] = "echo"
    env["GIT_CONFIG_NOSYSTEM"] = "1"          # the host's git config (autocrlf, insteadOf, filters)
    env["GIT_CONFIG_GLOBAL"] = os.devnull     # must not change what is cloned or how it is hashed
    env["GIT_HTTP_LOW_SPEED_LIMIT"] = "1000"  # abort a stalled transfer instead of hanging forever
    env["GIT_HTTP_LOW_SPEED_TIME"] = str(max(1, int(timeout)))
    return env


def _git(args: list[str], *, timeout: float, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Run the git executable with hooks, filters and auto-conversion disabled."""
    try:
        return subprocess.run(["git", *_GIT_CONFIG, *args], cwd=str(cwd) if cwd else None,
                              env=_git_env(timeout), timeout=timeout, capture_output=True,
                              text=True, errors="replace")
    except FileNotFoundError as exc:
        raise SourceError("the git executable is not available on PATH, so a Git repository "
                          "source cannot be materialized") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"git {args[0] if args else ''} exceeded the {timeout:g}s time limit"
                          ) from exc


def _first_line(text: str | None) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "unknown git error"


def _content_bytes(path: pathlib.Path) -> int:
    """Total size of the files under `path` (a tree being written can change during the walk)."""
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue          # a temporary pack file may vanish between the walk and the stat
    return total


def _remove_entry(entry: pathlib.Path) -> None:
    """Best-effort removal of one file or folder, clearing the read-only bit first."""
    try:
        os.chmod(entry, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        if entry.is_dir() and not entry.is_symlink():
            entry.rmdir()
        else:
            entry.unlink()
    except OSError:
        pass          # the caller verifies the result and reports a clear error if it failed


def remove_tree(path: pathlib.Path) -> None:
    """Remove a cached folder, READ-ONLY files included.

    Git for Windows marks `.git/objects/*` read-only, and `shutil.rmtree` cannot delete such a file
    (PermissionError). A leftover cache folder is not harmless: a later replacement would move the
    new content INSIDE it (the `shutil.move` nesting trap), so the bit is cleared explicitly.
    """
    if not path.exists():
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            _remove_entry(pathlib.Path(root) / name)
        for name in dirs:
            _remove_entry(pathlib.Path(root) / name)
    _remove_entry(path)


def _replace_tree(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Move `src` onto `dst`, replacing it.

    The destination is verified to be gone first: `shutil.move` silently moves a source INSIDE an
    existing destination directory, which would nest the cache one level deeper on every reuse.
    """
    remove_tree(dst)
    if dst.exists():
        raise SourceError(f"cannot replace the cache folder {dst}: it cannot be removed")
    try:
        os.replace(src, dst)
    except OSError as exc:
        raise SourceError(f"cannot write the cache: {exc}") from exc


def _export_clean_tree(clone: pathlib.Path, tree: pathlib.Path) -> None:
    """Copy the clone's working tree WITHOUT `.git`: the hash and the skill hold content only."""
    tmp = tree.with_name(tree.name + ".part")
    remove_tree(tmp)
    try:
        shutil.copytree(clone, tmp, ignore=shutil.ignore_patterns(".git"))
    except OSError as exc:
        raise SourceError(f"cannot write the cache: {exc}") from exc
    _replace_tree(tmp, tree)


def _kill_clone(proc: subprocess.Popen) -> None:
    """Terminate a supervised clone and wait for it, so its temporary files can be removed."""
    try:
        proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass              # the caller reports the removal result, which covers a survivor


def _supervised_clone(source: str, tmp: pathlib.Path, *, max_bytes: int,
                      timeout: float) -> tuple[int, str]:
    """Run a shallow clone while its temporary tree is measured; abort at the cap or the deadline.

    Returns `(returncode, stderr)` of a clone that finished on its own. A clone that crosses
    `max_bytes` DURING the transfer (or the overall time limit) is killed, its partial content is
    removed and a `SourceError` carrying the explicit reason is raised — the limit is a transfer
    limit, not a check applied to whatever has already been downloaded.
    """
    args = ["clone", "--quiet", "--depth", "1", "--single-branch", "--no-tags",
            "--no-recurse-submodules", source, str(tmp)]
    deadline = time.monotonic() + timeout
    reason = ""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        try:
            proc = subprocess.Popen(["git", *_GIT_CONFIG, *args], env=_git_env(timeout),
                                    stdout=subprocess.DEVNULL, stderr=err)
        except FileNotFoundError as exc:
            raise SourceError("the git executable is not available on PATH, so a Git repository "
                              "source cannot be materialized") from exc
        except OSError as exc:
            raise SourceError(f"git clone could not be started: {exc}") from exc
        try:
            while proc.poll() is None:
                size = _content_bytes(tmp)
                if size > max_bytes:
                    reason = (f"the clone exceeded the {max_bytes} byte limit during transfer "
                              f"({size} bytes)")
                    break
                if time.monotonic() >= deadline:
                    reason = f"the clone exceeded the {timeout:g}s time limit during transfer"
                    break
                time.sleep(CLONE_POLL_SECONDS)
        except BaseException:
            _kill_clone(proc)     # an interrupted run must not leave a transfer running behind it
            raise
        if reason:
            _kill_clone(proc)
            for _ in range(5):        # a killed transfer may still be releasing its files
                remove_tree(tmp)
                if not tmp.exists():
                    break
                time.sleep(0.2)
            if tmp.exists():
                raise SourceError(f"{reason}; the partial clone at {tmp} could not be removed")
            raise SourceError(f"{reason}; the partial clone was removed")
        err.seek(0)
        return proc.returncode, err.read()


def _clone_git(source: str, clone: pathlib.Path, *, max_bytes: int, timeout: float) -> str | None:
    """Shallow, single-branch clone without submodules/tags; returns the resolved commit sha."""
    tmp = clone.with_name(clone.name + ".part")
    remove_tree(tmp)
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SourceError(f"cannot write the cache: {exc}") from exc
    returncode, stderr = _supervised_clone(source, tmp, max_bytes=max_bytes, timeout=timeout)
    if returncode != 0:
        remove_tree(tmp)
        raise SourceError(f"git clone failed: {_first_line(stderr)}")
    size = _content_bytes(tmp)            # the cap can also be crossed between two polls
    if size > max_bytes:
        remove_tree(tmp)
        raise SourceError(f"the clone is larger than the {max_bytes} byte limit ({size} bytes); "
                          "the partial clone was removed")
    _replace_tree(tmp, clone)
    revision = _git(["rev-parse", "HEAD"], cwd=clone, timeout=timeout)
    sha = revision.stdout.strip() if revision.returncode == 0 else ""
    return sha or None


def _materialize_git(source: str, cache: pathlib.Path, *, max_bytes: int, timeout: float,
                     offline: bool) -> Materialized:
    key = cache_key(source)
    tree = cache / "git" / key
    if offline:
        if not tree.is_dir():
            raise SourceError(f"there is no cached copy of {_redact(source)} under {cache}, so it "
                              "cannot be resolved offline")
        meta = _load_meta(cache, key)
        return Materialized(source, "http_git", tree, resolved_revision=meta.get("resolved_revision"),
                            offline=True, stale=True)
    revision = _clone_git(source, cache / "_clones" / key, max_bytes=max_bytes, timeout=timeout)
    _export_clean_tree(cache / "_clones" / key, tree)
    _save_meta(cache, key, {"source": canonical_url(source), "source_type": "http_git",
                            "resolved_revision": revision, "fetched_at": _now()})
    return Materialized(source, "http_git", tree, resolved_revision=revision)


def resolve_source(source: str, *, repo: str | pathlib.Path | None = None,
                   cache: pathlib.Path | None = None, max_bytes: int = MAX_DOWNLOAD_BYTES,
                   timeout: float = FETCH_TIMEOUT_SECONDS, offline: bool = False,
                   allow_stale: bool = False) -> Materialized:
    """Classify and materialize a `reference_docs` source (local path or public URL).

    A local path is returned as it is (a relative one is resolved against `repo`). A remote source
    is fetched into the cache under `repo`. `offline` forbids network access entirely and
    `allow_stale` permits a cached copy after a failed fetch; ONLY those two flags yield a `stale`
    result, so a cached copy is never passed off as checked remote content.
    """
    kind = classify_source(source)
    if kind == "local":
        return Materialized(source=str(source), source_type="local",
                            local_path=local_path_of(source, repo))
    cache_dir = cache if cache is not None else cache_root(repo)
    fetch = _materialize_git if kind == "http_git" else _materialize_http_doc
    options = {"max_bytes": max_bytes, "timeout": timeout}
    if offline:
        return fetch(source, cache_dir, offline=True, **options)
    try:
        return fetch(source, cache_dir, offline=False, **options)
    except SourceError as exc:
        cached = None
        if allow_stale:
            try:
                cached = fetch(source, cache_dir, offline=True, **options)
            except SourceError:
                cached = None
        if cached is not None:
            print(f"warning: {exc}; reusing the cached copy instead (stale: true)", file=sys.stderr)
            return cached
        raise SourceError(f"cannot resolve {_redact(source)}: {exc}") from exc


def materialize_and_hash(source: str, **kwargs) -> tuple[Materialized, str]:
    """Materialize `source` and return it together with the SHA-256 of its content."""
    materialized = resolve_source(source, **kwargs)
    return materialized, hash_path(materialized.local_path)


def add_repo(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the optional repo anchor to a subcommand parser (the run_id.py convention)."""
    parser.add_argument("--repo", "--root", dest="repo", metavar="ROOT",
                        default=argparse.SUPPRESS, help=REPO_HELP)
    return parser


def add_remote_options(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Flags of every subcommand that may materialize a remote source."""
    parser.add_argument("--offline", action="store_true",
                        help="Never touch the network: reuse a cached copy, marked stale: true "
                             "(exit 1 when no cached copy exists)")
    parser.add_argument("--allow-stale", action="store_true",
                        help="Reuse a cached copy, marked stale: true, when the fetch fails")
    parser.add_argument("--timeout", type=float, default=FETCH_TIMEOUT_SECONDS, metavar="SECONDS",
                        help=f"Overall fetch time limit (default: {FETCH_TIMEOUT_SECONDS:g})")
    parser.add_argument("--max-bytes", type=int, default=MAX_DOWNLOAD_BYTES, metavar="N",
                        help=f"Download/clone size limit in bytes (default: {MAX_DOWNLOAD_BYTES})")
    return parser


def _source_options(args) -> dict:
    """The `resolve_source` options a subcommand carries (`getattr`: old callers stay valid)."""
    return {
        "repo": getattr(args, "repo", None),
        "max_bytes": getattr(args, "max_bytes", MAX_DOWNLOAD_BYTES),
        "timeout": getattr(args, "timeout", FETCH_TIMEOUT_SECONDS),
        "offline": getattr(args, "offline", False),
        "allow_stale": getattr(args, "allow_stale", False),
    }


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
    """Print the SHA-256 of a local path OR of a remote source (resolved into the cache first).

    A relative local path goes through the same `--repo` anchor as `resolve` and `record`: the
    declared repository root decides which file is meant, never the process working directory.
    """
    if classify_source(args.path) == "local":
        print(hash_path(local_path_of(args.path, getattr(args, "repo", None))))
        return 0
    materialized, digest = materialize_and_hash(args.path, **_source_options(args))
    if materialized.stale:
        print(f"stale: {args.path} was NOT fetched; the cached copy was hashed", file=sys.stderr)
    print(digest)
    return 0


def cmd_resolve(args) -> int:
    """Print the local path and metadata of a materialized `reference_docs` source as JSON."""
    materialized, digest = materialize_and_hash(args.source, **_source_options(args))
    if materialized.stale:
        print(f"stale: {_redact(args.source)} was NOT fetched; reusing the cached copy",
              file=sys.stderr)
    print(json.dumps(materialized.to_dict(sha256=digest), indent=2, ensure_ascii=False))
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


def _divergent(source: str, expected: str, actual: str) -> SourceError:
    """A materialization that is no longer the one the skill was generated from."""
    return SourceError(
        f"divergent materialization of {_redact(source)}: the resolved hash {expected} does not "
        f"describe the materialized content ({actual}); recording it would sign bytes other than "
        "the ones the skill was generated from — re-run resolve and regenerate the skill")


def _record_source(args) -> tuple[str, str, dict]:
    """The manifest `source`, `sha256` and the remote-only metadata of a `record` call.

    A URL is materialized first, so the stored signature is the content signature of the fetched
    content, while `source` stays the canonical original URL. A local path is recorded unchanged.

    `--resolved-hash <hex>` (the digest `resolve` reported) switches BOTH kinds to recording the
    already-resolved materialization: no second fetch happens, the materialization is verified
    against that digest, and a divergence is refused instead of being signed with another hash.
    """
    source = args.source
    kind = classify_source(source)
    repo = getattr(args, "repo", None)
    expected = getattr(args, "resolved_hash", None)
    if kind == "local":
        if expected:
            digest = hash_path(local_path_of(source, repo))
            if digest != expected:
                raise _divergent(source, expected, digest)
            return source, digest, {}
        return source, args.hash, {}
    if expected:
        materialized = resolve_source(source, repo=repo, offline=True)
        digest = hash_path(materialized.local_path)
        if digest != expected:
            raise _divergent(source, expected, digest)
        return source, digest, {
            "source_type": materialized.source_type,
            "resolved_revision": materialized.resolved_revision,
        }
    materialized, digest = materialize_and_hash(source, **_source_options(args))
    if materialized.stale:
        print(f"stale: {_redact(source)} was NOT fetched; the cached content was recorded",
              file=sys.stderr)
    if args.hash and args.hash != digest:
        print(f"warning: the given hash {args.hash} is not the content hash {digest} of "
              f"{_redact(source)}; recording the content hash", file=sys.stderr)
    return source, digest, {
        "source_type": materialized.source_type,
        "resolved_revision": materialized.resolved_revision,
    }


def cmd_record(args) -> int:
    base = pathlib.Path(args.base).resolve()
    manifest = load_manifest(base)
    now = _now()
    source, digest, extra = _record_source(args)
    existing = manifest["skills"].get(args.name)
    if existing:
        existing.update({
            "source": source,
            "sha256": digest,
            "last_used": now,
            **extra,
        })
        if args.task_id and args.task_id not in existing.get("task_ids", []):
            existing.setdefault("task_ids", []).append(args.task_id)
    else:
        manifest["skills"][args.name] = {
            "name": args.name,
            "source": source,
            "sha256": digest,
            "created_at": now,
            "last_used": now,
            "task_ids": [args.task_id] if args.task_id else [],
            **extra,
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
    ap.add_argument("--repo", "--root", dest="repo", metavar="ROOT", default=None, help=REPO_HELP)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    ph = add_remote_options(add_repo(sub.add_parser("hash")))
    ph.add_argument("path", help="Local file/folder, an http(s) document URL or a Git URL (.git)")

    pl = sub.add_parser("lookup")
    pl.add_argument("name")
    pl.add_argument("--hash")

    pr = add_remote_options(add_repo(sub.add_parser("record")))
    pr.add_argument("name")
    pr.add_argument("source", help="Canonical source of the skill: a local path OR a public URL")
    pr.add_argument("hash", help="Content hash (for a URL: the digest of the resolved materialization)")
    pr.add_argument("--resolved-hash", dest="resolved_hash", metavar="HEX",
                    help="Digest printed by `resolve`: record the ALREADY materialized content of a "
                         "URL without fetching it again, and refuse a divergent materialization")
    pr.add_argument("--task-id")

    ps = add_remote_options(add_repo(sub.add_parser(
        "resolve", help="Materialize a source and print path + metadata as JSON")))
    ps.add_argument("source", help="Local path, http(s) document URL or Git URL (.git)")

    sub.add_parser("list")

    args = ap.parse_args()
    handlers = {
        "init": lambda: cmd_init(pathlib.Path(args.base).resolve()),
        "resolve": lambda: cmd_resolve(args),
        "hash": lambda: cmd_hash(args),
        "lookup": lambda: cmd_lookup(args),
        "record": lambda: cmd_record(args),
        "list": lambda: cmd_list(args),
    }
    try:
        return handlers[args.cmd]()
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # Backstop: a failure is a message naming the source and the reason, never a traceback.
        source = getattr(args, "source", None) or getattr(args, "path", None)
        print(f"error: {f'{source}: ' if source else ''}{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
