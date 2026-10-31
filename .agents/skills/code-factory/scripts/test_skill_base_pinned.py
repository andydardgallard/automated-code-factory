#!/usr/bin/env python3
"""
Deterministic OFFLINE self-test for PINNED revisions and MULTIPLE sources in `skill_base.py`.

Two local bare Git repositories are published over LOOPBACK smart HTTP (`git http-backend` on
127.0.0.1 — the fixture of `test_remote_reference_docs.py`), so the suite never touches the
internet and stays reproducible.

Verifies: `--revision` on `resolve` / `hash` / `record` materializes EXACTLY the pinned commit and
signs the CHECKED-OUT content (not HEAD), an abbreviated sha pins its full commit, a cache checked
out at another revision is re-checked-out/re-cloned instead of being signed, a cached copy at
another revision is refused under `--offline`, an unreachable revision is exit 1 with an explicit
message and no traceback, a clone already at the pinned revision is reused without the network,
`--revision` with a local path or an http document (and a non-hex revision) is a usage error
(exit 2), the `-` hash of a pinned record (no warning noise), the repeatable
`--extra-source SOURCE[@REVISION]` and the `sources` list of a multi-source entry (the top-level
`source`/`sha256` stay the primary source's values), a hexadecimal URL query value staying part of
its source, an offline pinned reuse REFUSING a cached tree whose bytes were changed while its
metadata still names the pinned revision, the absence of a `sources` key without the option, and
the documented CLI.

Exit code 0 = all assertions pass, 1 = a check did not behave as expected.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

import skill_base as sb
from test_remote_reference_docs import Check, error_of, git, serve_git, stop, url_of

SCRIPT = pathlib.Path(__file__).resolve().parent / "skill_base.py"

# Three commits: the pinned revisions differ from HEAD in content, not only in the sha.
COMMITS = (("readme.md", "# Pinned v1\n"), ("docs/b.md", "b\n"), ("readme.md", "# Pinned v3\n"))


def cli(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, errors="replace")


def git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


def build_repo(root: pathlib.Path, name: str, www: pathlib.Path) -> list[str]:
    """A bare repository published at `<www>/<name>.git`; returns the sha of every commit."""
    seed = root / f"seed-{name}"
    git("init", "-q", "-b", "main", str(seed), cwd=root)
    shas: list[str] = []
    for index, (relative, content) in enumerate(COMMITS, start=1):
        target = seed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git("-c", "user.email=t@example.test", "-c", "user.name=t", "add", "-A", cwd=seed)
        git("-c", "user.email=t@example.test", "-c", "user.name=t", "commit", "-qm",
            f"commit {index}", cwd=seed)
        shas.append(git("rev-parse", "HEAD", cwd=seed).strip())
    git("clone", "-q", "--bare", str(seed), str(www / f"{name}.git"), cwd=root)
    return shas


def test_pinning(check: Check, root: pathlib.Path, base: pathlib.Path, server,
                 url: str, shas: list[str]) -> str:
    """A pinned revision materializes and signs exactly that commit; returns its digest."""
    head, head_digest = sb.materialize_and_hash(url, repo=root)
    check(head.resolved_revision == shas[2], "an unpinned resolve must land on the branch HEAD")

    pinned, pinned_digest = sb.materialize_and_hash(url, repo=root, revision=shas[0])
    check(pinned.resolved_revision == shas[0],
          f"a pinned resolve must report the pinned sha, got {pinned.resolved_revision}")
    check((pinned.local_path / "readme.md").read_text(encoding="utf-8") == "# Pinned v1\n",
          "a pinned resolve must materialize the pinned commit's content")
    check(not (pinned.local_path / "docs" / "b.md").exists(),
          "content added by a LATER commit must not appear in the pinned tree")
    check(pinned_digest != head_digest, "a pinned revision must not hash like HEAD")
    check(sb.hash_path(pinned.local_path) == pinned_digest,
          "the digest must cover exactly the checked-out (materialized) content")
    meta = sb._load_meta(sb.cache_root(root), sb.cache_key(url))
    check(meta.get("resolved_revision") == shas[0],
          "the cache metadata must record the pinned revision it holds")

    abbreviated, abbreviated_digest = sb.materialize_and_hash(url, repo=root,
                                                              revision=shas[1][:8])
    check(abbreviated.resolved_revision == shas[1],
          "an abbreviated sha must resolve to its full commit sha")
    check(abbreviated_digest != pinned_digest,
          "another pinned revision must change the content hash")
    check((abbreviated.local_path / "docs" / "b.md").is_file(),
          "the second commit's content must be materialized when it is the pinned revision")
    check(not (abbreviated.local_path / "readme.md").read_text(encoding="utf-8").endswith("v3\n"),
          "a later commit's edit must not leak into the pinned tree")

    again, again_digest = sb.materialize_and_hash(url, repo=root, revision=shas[0])
    check(again_digest == pinned_digest,
          "re-pinning a cache that holds another revision must restore the pinned content")

    hashed = cli("--repo", str(root), "hash", url, "--revision", shas[0])
    check(hashed.returncode == 0 and hashed.stdout.strip() == pinned_digest,
          f"hash --revision must print the pinned content digest: {hashed.stderr}")
    resolved = cli("--repo", str(root), "resolve", url, "--revision", shas[0])
    check(resolved.returncode == 0, f"resolve --revision must exit 0: {resolved.stderr}")
    payload = json.loads(resolved.stdout)
    check(payload["resolved_revision"] == shas[0] and payload["sha256"] == pinned_digest,
          "resolve --revision must report the pinned revision and its content digest")

    recorded = cli("--repo", str(root), "--base", str(base), "record", "pinned", url, "-",
                   "--revision", shas[0], "--task-id", "1")
    check(recorded.returncode == 0,
          f"record must accept '-' with a pinned source: {recorded.stderr}")
    check("warning" not in recorded.stderr.lower(),
          f"the intended '-' hash must not warn: {recorded.stderr}")
    entry = sb.load_manifest(base)["skills"]["pinned"]
    check(entry["sha256"] == pinned_digest,
          "the recorded digest must be the pinned materialization, not HEAD")
    check(entry["resolved_revision"] == shas[0], "the entry must record the pinned revision")
    check(entry["source_type"] == "http_git", "a Git source keeps its source type")
    check(entry["source"] == url, "the entry must keep the canonical source URL")
    check("sources" not in entry, "a single-source record must not grow a sources list")
    check(cli("--base", str(base), "lookup", "pinned", "--hash", pinned_digest
              ).stdout.strip() == "reuse",
          "lookup --hash must keep its meaning for a pinned entry")

    refusal = cli("--repo", str(root), "resolve", url, "--revision", shas[2], "--offline")
    check(refusal.returncode == 1,
          "an offline resolve of another revision than the cached one must fail, not sign it")
    check("Traceback" not in refusal.stderr,
          f"a refusal is a message, never a traceback: {refusal.stderr!r}")
    check(shas[2] in refusal.stderr and shas[0] in refusal.stderr,
          f"the refusal must name both the pinned and the cached revision: {refusal.stderr!r}")
    check(refusal.stdout.strip() == "", "a refused resolve must print no metadata")

    pinned_second = json.loads(cli("--repo", str(root), "resolve", url, "--revision",
                                   shas[1]).stdout)["sha256"]
    combo = cli("--repo", str(root), "--base", str(base), "record", "combo", url, "-",
                "--revision", shas[1], "--resolved-hash", pinned_second)
    check(combo.returncode == 0,
          f"--resolved-hash must work together with a pinned revision: {combo.stderr}")
    combo_entry = sb.load_manifest(base)["skills"]["combo"]
    check(combo_entry["sha256"] == pinned_second and combo_entry["resolved_revision"] == shas[1],
          "--resolved-hash with a pin must record the pinned materialization")
    divergent = cli("--repo", str(root), "--base", str(base), "record", "combo", url, "-",
                    "--revision", shas[1], "--resolved-hash", "0" * 64)
    check(divergent.returncode == 1 and "divergen" in divergent.stderr.lower()
          and "Traceback" not in divergent.stderr,
          "a divergent resolved hash must still be refused when a revision is pinned")
    return pinned_digest


def test_usage_errors(check: Check, root: pathlib.Path, base: pathlib.Path, server,
                      url: str, shas: list[str]) -> None:
    """A pin that cannot mean anything is a usage error: exit 2, a reason, no traceback."""
    local_doc = root / "local-note.md"
    local_doc.write_text("# Local note\n", encoding="utf-8")
    document_url = url_of(server, "/docs/guide.md")      # no .git: an http document source
    unreachable = "dead" * 10                            # a valid, non-existent 40-hex sha
    cases = {
        "a local path cannot be pinned": cli("--repo", str(root), "--base", str(base), "record",
                                             "bad", local_doc.name, "0" * 64,
                                             "--revision", shas[0]),
        "hash --revision of a local path": cli("--repo", str(root), "hash", local_doc.name,
                                               "--revision", shas[0]),
        "a document URL cannot be pinned": cli("--repo", str(root), "resolve", document_url,
                                               "--revision", shas[0]),
        "a branch name is not a revision": cli("--repo", str(root), "hash", url,
                                               "--revision", "main"),
        "a '-' hash needs --revision": cli("--repo", str(root), "--base", str(base), "record",
                                           "bad", local_doc.name, "-"),
        "an extra source pin of a local path": cli("--repo", str(root), "--base", str(base),
                                                   "record", "bad", local_doc.name,
                                                   sb.hash_path(local_doc),
                                                   "--extra-source", f"{local_doc.name}@{shas[0]}"),
    }
    for what, result in cases.items():
        check(result.returncode == 2,
              f"{what} must be a usage error (exit 2), got {result.returncode}: {result.stderr!r}")
        check("Traceback" not in result.stderr, f"{what} must not print a traceback")
        check("usage:" in result.stderr.lower(),
              f"{what} must print the usage, got: {result.stderr!r}")
    check("hex" in cases["a branch name is not a revision"].stderr.lower(),
          "a non-hex revision must say that a hex commit sha is required")

    check(sb._parse_extra_source("docs/a.md") == ("docs/a.md", None),
          "an extra source without a pin has no pinned revision")
    check(sb._parse_extra_source(f"{url}@abc1234") == (url, "abc1234"),
          "an extra source must split its hex revision off at the '@'")
    check(sb._parse_extra_source("https://h/r.git?ref=main") == ("https://h/r.git?ref=main", None),
          "a query string must not be mistaken for a pinned revision")
    check(sb._parse_extra_source("https://h/r.git?ref=abc1234")
          == ("https://h/r.git?ref=abc1234", None),
          "a HEXADECIMAL query value must stay part of the source, never become a revision")
    check(sb._parse_extra_source("https://h/r.git?ref=deadbeef&x=1")
          == ("https://h/r.git?ref=deadbeef&x=1", None),
          "a hex query value inside a longer query must stay part of the source")
    check(sb._parse_extra_source("https://h/r.git@abc1234") == ("https://h/r.git", "abc1234"),
          "an explicit '@REVISION' must still pin the source")
    ambiguous = cli("--repo", str(root), "--base", str(base), "record", "bad", local_doc.name,
                    sb.hash_path(local_doc), "--extra-source", "https://127.0.0.1:9/r.git=abc1234")
    check(ambiguous.returncode == 1 and "Traceback" not in ambiguous.stderr,
          "the old '=' form must not split a hex value off a source (it is an unresolvable URL), "
          f"got rc={ambiguous.returncode}: {ambiguous.stderr!r}")
    check("https://127.0.0.1:9/r.git=abc1234" in ambiguous.stderr,
          "a '=HEX' tail must stay part of the source it belongs to, never become a revision: "
          f"{ambiguous.stderr!r}")

    missing = cli("--repo", str(root), "hash", url, "--revision", unreachable)
    check(missing.returncode == 1,
          f"an unreachable revision must exit 1, got {missing.returncode}: {missing.stderr!r}")
    check("Traceback" not in missing.stderr, "an unreachable revision is a message, not a traceback")
    check(unreachable in missing.stderr and "not reachable" in missing.stderr.lower(),
          f"the message must name the revision and the reason: {missing.stderr!r}")
    check(missing.stdout.strip() == "", "a failed pin must not print a hash")


def test_multi_source(check: Check, root: pathlib.Path, base: pathlib.Path, url: str,
                      shas: list[str], url2: str, shas2: list[str]) -> None:
    """`--extra-source` writes a `sources` list; the top-level keys stay the primary source's."""
    notes = root / "notes.md"
    notes.write_text("# Notes\n", encoding="utf-8")
    primary_digest = sb.materialize_and_hash(url, repo=root, revision=shas[0])[1]
    extra_digest = sb.materialize_and_hash(url2, repo=root, revision=shas2[1])[1]

    recorded = cli("--repo", str(root), "--base", str(base), "record", "multi", url, "-",
                   "--revision", shas[0],
                   "--extra-source", f"{url2}@{shas2[1]}",
                   "--extra-source", notes.name,
                   "--task-id", "4")
    check(recorded.returncode == 0, f"a multi-source record must succeed: {recorded.stderr}")
    check("warning" not in recorded.stderr.lower(), f"no warning expected: {recorded.stderr}")
    entry = sb.load_manifest(base)["skills"]["multi"]
    check(entry["source"] == url and entry["sha256"] == primary_digest,
          "the top-level source/sha256 must stay the POSITIONAL source's values")
    check(entry["resolved_revision"] == shas[0] and entry["source_type"] == "http_git",
          "the top-level remote metadata must describe the positional source")
    check(entry["task_ids"] == ["4"], "a multi-source record must keep the task id")

    sources = entry.get("sources")
    check(isinstance(sources, list) and len(sources) == 3,
          f"the entry must list every contributing source (primary included), got {sources}")
    check(sources[0] == {"source": url, "sha256": primary_digest, "source_type": "http_git",
                         "resolved_revision": shas[0]},
          f"the positional source must be the first list item, got {sources[0]}")
    check(sources[1]["source"] == url2 and sources[1]["sha256"] == extra_digest,
          "an extra Git source must be materialized at its own pinned revision")
    check(sources[1]["source_type"] == "http_git"
          and sources[1]["resolved_revision"] == shas2[1],
          f"the pinned extra source must record its revision, got {sources[1]}")
    check(sources[2] == {"source": notes.name, "sha256": sb.hash_path(notes)},
          f"a local extra source carries neither a source type nor a revision, got {sources[2]}")
    check(cli("--base", str(base), "lookup", "multi", "--hash", primary_digest
              ).stdout.strip() == "reuse",
          "lookup --hash must keep querying the positional source's digest")
    check("multi" in json.loads(cli("--base", str(base), "list").stdout)["skills"],
          "list must keep showing a multi-source entry")

    head_digest = sb.materialize_and_hash(url, repo=root)[1]
    rerecorded = cli("--repo", str(root), "--base", str(base), "record", "multi", url,
                     head_digest, "--task-id", "6")
    check(rerecorded.returncode == 0, f"a single-source re-record must succeed: {rerecorded.stderr}")
    entry = sb.load_manifest(base)["skills"]["multi"]
    check("sources" not in entry,
          "a re-record without --extra-source must not keep a stale sources list")
    check(entry["sha256"] == head_digest and entry["task_ids"] == ["4", "6"],
          "the re-record must update the entry as before")


def test_cli_contract(check: Check) -> None:
    """The documented `record` command carries both new options."""
    result = cli("record", "--help")
    check(result.returncode == 0, f"record --help must exit 0: {result.stderr!r}")
    for option in ("--revision", "--extra-source"):
        check(option in result.stdout, f"record --help must document {option}")
    usage = next(line for line in (sb.__doc__ or "").splitlines() if " record " in line)
    check("--revision" in usage and "--extra-source" in usage,
          f"the documented record command must carry both new options: {usage.strip()}")


def test_no_network(check: Check, root: pathlib.Path, url: str, shas: list[str],
                    pinned_digest: str) -> None:
    """With the source gone, a matching pin is still reused and a different one is refused."""
    reused, digest = sb.materialize_and_hash(url, repo=root, revision=shas[0])
    check(digest == pinned_digest and reused.resolved_revision == shas[0],
          "a clone already checked out at the pinned revision must be reused, not refetched")
    message = error_of(lambda: sb.materialize_and_hash(url, repo=root, revision=shas[1]))
    check("cannot resolve" in message and "127.0.0.1" in message,
          f"a pin that needs the network must name the source and the reason (got: {message})")
    cached_tree = sb.cache_root(root) / "git" / sb.cache_key(url)
    check(sb.hash_path(cached_tree) == pinned_digest,
          "a failed re-checkout must leave the pinned materialization untouched")


def test_query_revision(check: Check, url: str, shas: list[str]) -> None:
    """A hex URL QUERY value stays part of the source: it is never split off as a revision.

    This is the value `record --extra-source` receives, so the regression is asserted at the step
    that misparsed it — the split between source and pinned revision. (A real clone cannot carry
    the query: `git` appends `info/refs?service=git-upload-pack` to every URL.)
    """
    queried = f"{url}?ref={shas[0][:7]}"
    check(sb._parse_extra_source(queried) == (queried, None),
          "the hex query value of a real source must stay part of it")
    check(sb.classify_source(queried) == "http_git", "the whole URL must stay one Git source")


def test_tampered_cache(check: Check, root: pathlib.Path, url: str, shas: list[str],
                        pinned_digest: str) -> None:
    """Changed cached bytes with unchanged metadata are REFUSED, offline and by the CLI."""
    tree = sb.cache_root(root) / "git" / sb.cache_key(url)
    readme = tree / "readme.md"
    original = readme.read_bytes()
    readme.write_bytes(original + b"tampered\n")
    tampered_digest = sb.hash_path(tree)
    meta = sb._load_meta(sb.cache_root(root), sb.cache_key(url))
    check(meta.get("resolved_revision") == shas[0],
          "the tamper must leave the cache metadata claiming the pinned revision")
    message = error_of(lambda: sb.materialize_and_hash(url, repo=root, revision=shas[0],
                                                       offline=True))
    check("no longer matches" in message and shas[0] in message,
          f"a tampered cached tree must be refused with a reason (got: {message})")
    cli_result = cli("--repo", str(root), "hash", url, "--revision", shas[0], "--offline")
    check(cli_result.returncode == 1 and cli_result.stdout.strip() == "",
          f"the CLI must refuse a tampered cache instead of printing its digest: {cli_result!r}")
    check("Traceback" not in cli_result.stderr,
          "a refused cache is a message, never a traceback")
    readme.write_bytes(original)
    check(sb.hash_path(tree) == pinned_digest, "restoring the bytes must restore the pinned digest")
    restored = sb.materialize_and_hash(url, repo=root, revision=shas[0], offline=True)[1]
    check(restored == pinned_digest, "an intact cache must still verify and be reused offline")


def run(check: Check, root: pathlib.Path) -> None:
    test_cli_contract(check)
    if not git_available():
        check.skip("the git executable is unavailable: the pinned-revision cases were not run")
        return
    www = root / "www"
    www.mkdir()
    shas = build_repo(root, "repo", www)
    shas2 = build_repo(root, "other", www)
    base = root / "skill-base"
    sb.cmd_init(base)
    server = serve_git(www)
    url = url_of(server, "/repo.git")
    url2 = url_of(server, "/other.git")
    try:
        pinned_digest = test_pinning(check, root, base, server, url, shas)
        test_usage_errors(check, root, base, server, url, shas)
        test_multi_source(check, root, base, url, shas, url2, shas2)
        test_query_revision(check, url, shas)
        sb.materialize_and_hash(url, repo=root, revision=shas[0])   # leave the cache pinned
    finally:
        stop(server)
    test_no_network(check, root, url, shas, pinned_digest)
    test_tampered_cache(check, root, url, shas, pinned_digest)


def main() -> int:
    check = Check()
    with tempfile.TemporaryDirectory() as td:
        try:
            run(check, pathlib.Path(td))
        except AssertionError as exc:
            print(f"FAIL - {exc}")
            print(f"FAIL - {check.count} checks passed before the failure.")
            return 1
    print(f"PASS - {check.count} checks of the pinned-revision and multi-source contract "
          "behave as expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
