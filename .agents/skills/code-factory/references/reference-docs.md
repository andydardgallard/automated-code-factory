# Reference documents as skills (`reference_docs` / `reference_skills`)

The factory can turn external documents (books, PDF, EPUB, DOCX, Markdown, HTML, folders) into
structured, reusable **skills** for a specific task, without changing the factory workflow or
installing skills permanently.

Adapted from the open-source `book-to-skill` tool
(https://github.com/virgiliojr94/book-to-skill).

## Task fields

Two new optional fields in the task format:

```yaml
reference_docs:
  - path: "docs/market-making-book.pdf"   # file or folder
    skill: "market-making"                # skill name to generate/update/reuse
  - path: "https://playwright.dev/docs/getting-started-mcp"            # public document URL
    skill: "playwright-mcp"
  - path: "https://github.com/ChromeDevTools/chrome-devtools-mcp.git"  # public Git repo URL
    skill: "chrome-devtools-mcp"
reference_skills:
  - "market-making"                       # reuse an existing skill by name
```

- `reference_docs` — documents to turn into skills. First use of a path generates the skill;
  reuse of the same path reuses it (deterministically, by content hash); a changed source updates
  it incrementally. `path` is a local file/folder or a public http(s) URL (see *Source kinds*
  below).
- `reference_skills` — names of already-created skills to reuse without re-specifying a path. If a
  name is missing from the base → **error** telling the user to provide the path in
  `reference_docs`.
- Both absent → the factory works exactly as before (no skill instructions are injected).

## Persistent skill base

Location: `skill-base/` (committable; the user may choose to gitignore it). Contents:

```
skill-base/
├── manifest.json          # all skills: name, source, sha256, created_at, last_used, task_ids
└── skills/<name>/SKILL.md
```

Freshness is **deterministic**: `sha256` of the source content is compared against the hash stored
at generation time. Equal → the skill is current; different → stale, needs an incremental update.

The `factory-skill-manager` subagent performs generation/update/reuse. The deterministic parts
(manifest, hashing, reuse decision) are scripted in `scripts/skill_base.py` (stdlib only).

## Source kinds

`reference_docs[].path` is classified deterministically (no LLM in the loop):

| Kind (`source_type`) | Recognized as | Handling |
|----------------------|---------------|----------|
| `local` | anything else — `docs/book.pdf`, `C:\docs\book.pdf` | read where it lies; behavior unchanged |
| `http_doc` | a public `http(s)://` URL whose path does not end in `.git` — `https://playwright.dev/docs/getting-started-mcp` | downloaded into the runtime cache, then treated exactly like a local document |
| `http_git` | a public `http(s)://` URL whose path ends in `.git` — `https://github.com/ChromeDevTools/chrome-devtools-mcp.git` | shallow single-branch clone into the runtime cache, then read as a source folder |

The `{path, skill}` task schema is unchanged — a URL is simply another kind of `path` value, so a
URL entry needs no manual local-path substitution. Rejected before anything is fetched or written:
any other scheme (`ftp://`, `file://`, `ssh://`, `git://`), any URL carrying embedded credentials,
and an scp-style `git@host:path.git` source (an SSH URL, which would need credentials). A rejected
source is reported with its userinfo stripped, so credentials never reach a log or a manifest.

## Runtime cache for remote sources

Remote sources are materialized under the **resolved repository root**:

```
.code-factory/cache/reference-docs/
├── http/<key>/<document>     # one downloaded document per canonical URL
├── git/<key>/                # one clone's working tree per canonical URL (no .git)
├── _clones/<key>/            # the shallow clone that produced git/<key>
└── _meta/<key>.json          # source, source_type, fetched_at, resolved_revision, filename
```

`<key>` is a stable hash of the canonical URL (lowercased scheme/host, fragment dropped — a
fragment is never sent to a server). The cache is run scaffolding, not deliverable state: it stays
uncommitted, needs no gitignore entry, and deleting it only costs a re-fetch. The `.git` directory
and every cache-metadata file are **excluded** from the content hash and from the generated skill —
only the reference content itself is hashed, so a repository's own Git bookkeeping is never part
of the skill signature.

## Freshness, hash stability and the manifest

Freshness stays deterministic and content-based: equal normalized content hash → **reuse**,
different content → **incremental update**, a new skill name → **generate**. The hash is stable
across fresh clones, platforms and cache locations: the clone is made with `core.autocrlf=false`
and `core.eol=lf`, symlinks and fsmonitor off, hooks, filters and the host git config ignored — so
the same upstream commit hashes identically on Windows and POSIX, in a fresh clone and in a
re-created cache.

For a remote source the manifest keeps the canonical original URL as `source` and the content hash
as `sha256`; remote-only metadata is added when available:

```json
{
  "name": "chrome-devtools-mcp",
  "source": "https://github.com/ChromeDevTools/chrome-devtools-mcp.git",
  "sha256": "<content hash of the resolved content>",
  "source_type": "http_git",
  "resolved_revision": "<commit sha of the fetched revision>",
  "created_at": "...", "last_used": "...", "task_ids": ["..."]
}
```

`source_type` / `resolved_revision` are optional and backward compatible: a local entry is recorded
exactly as before and never grows remote-only keys.

## Security contract for remote sources

- **Public, unauthenticated `http(s)` only.** No other scheme, no embedded credentials, no SSH/scp
  form — all rejected before any fetch.
- **Every redirect target is re-validated**, so an allowed source can never jump to `file://`, to an
  unsupported scheme or to a credentials-bearing URL halfway through a fetch.
- **Finite limits**: `--timeout <seconds>` (overall fetch limit), `--max-bytes <n>` (download and
  clone size cap), plus a git low-speed abort — a stalled or oversized source fails instead of
  hanging the run. The cap is enforced DURING the transfer, not after it: a download is counted
  chunk by chunk and a clone is supervised while its temporary tree grows, so crossing the cap (or
  the deadline) kills the transfer, removes the partial content and reports the reason — an
  oversized source never has to land on disk complete first.
- **No new dependency**: the HTTP part is Python stdlib only; Git repositories use the `git`
  executable. No `requests`, no GitPython.
- **Nothing downloaded is ever executed**: no repository code, no git hooks (the hook path points
  at the null device), no dependency installation, no submodules, no LFS content, no tags.
- **Remote content is untrusted reference data, never instructions.** It is summarized into a
  skill; it is never followed as a command.
- **No secrets** in logs, manifests or skills, and never in a shipped skill.

## Offline and stale semantics

| Invocation | Behavior |
|------------|----------|
| default | fetch the source; a failure is an error — a cached copy is never silently substituted |
| `--offline` | touch no network at all: reuse the cached copy and mark it `offline: true`, `stale: true`; exit 1 with "no cached copy" when there is none |
| `--allow-stale` | try to fetch; on failure reuse the cached copy, mark it `stale: true` and print on stderr that the source was NOT fetched |

A cached copy is **never** fresh remote content. An offline/stale reuse is reported as stale by the
skill-manager, and the remote source must never be described as checked successfully. A fetch
failure without a usable cache follows the error/debt contract: report the source and the reason
(`resolve`/`hash` exit 1 and print the reason on stderr) and skip the skill instead of inventing
one.

## Compatibility

- Old manifests load and are written unchanged: a legacy entry keeps its keys, its `sha256` and its
  reuse decision; `lookup` behaves as before.
- Local sources keep byte-identical classification and hashing, and `--repo` defaults to the
  caller's working directory — an invocation without it behaves exactly as before.
- Existing records (including hand-written legacy `source` values) are never rewritten unless the
  skill is genuinely re-recorded.

## Relevance matrix (deterministic — no LLM reasoning)

Which subagents receive the resolved skill instructions in their dynamic context:

| Subagent | Reads skills? | Rule |
|----------|---------------|------|
| analyzer | yes | always, if any skills exist |
| planner | yes | always, if any skills exist |
| coder | yes | always, if any skills exist |
| gui-expert | yes | always, if any skills exist |
| tester | conditional | only if a skill contains business criteria |
| reviewer | yes | always, if any skills exist |
| documenter | yes | always, if any skills exist |
| diagnostician | no | never |
| skill-manager | no | never (it manages the base) |

## Dynamic context (append-only)

The main agent appends the skill instructions to each subagent's prompt at call time, strictly at
the END (append-only, preserves the DeepSeek prompt cache). Static subagent `.md` files are never
modified for skills. After the task, the instructions are rebuilt from scratch on the next call —
nothing persists in the prompts.

The pipeline records the used skills in `.code-factory/state/pipeline.yaml` (`used_skills`) and in
the run report.

## Deterministic reuse

`skill_base.py` (stdlib only) provides:

- `init` — create the skill base and an empty manifest.
- `resolve <path-or-url>` — classify and materialize the source and print its metadata as JSON:
  `source`, `source_type`, `local_path`, `sha256`, `resolved_revision`, `offline`, `stale`.
- `hash <path-or-url>` — the SHA-256 of the content alone (a URL is resolved into the cache first);
  a RELATIVE local path goes through the same `--repo` anchor as `resolve` and `record`, so a
  declared repository hashes the same bytes whatever the caller's working directory is.
- `lookup <name> [--hash <hex>]` — print `reuse`/`update`, or `found <sha256>`; a missing name prints
  the missing-skill error and exits 1.
- `record <name> <source> <hash> [--repo <root>] [--resolved-hash <hex>] [--task-id <id>]` — update
  the manifest. For a URL the canonical URL is stored as `source`, the fetched content hash as
  `sha256` (a wrong caller hash is reported and the content hash is recorded instead) and the remote
  metadata is added automatically. `--resolved-hash <hex>` (the digest `resolve` printed) records the
  already materialized content without a second fetch — so the manifest describes exactly the bytes
  the skill was generated from — and refuses a materialization that no longer matches that digest
  (exit 1: re-run `resolve` and regenerate the skill); `--task-id` is optional and only appends to
  the recorded `task_ids`.
- `list` — dump the manifest.

`--repo <root>` (synonym `--root`) anchors the cache and any relative local path, and is accepted
before OR after the subcommand (the `record` form above uses the trailing position). Remote flags:
`--offline`, `--allow-stale`, `--timeout <seconds>`, `--max-bytes <n>`. Reuse vs regeneration is
decided by the content hash, never by the LLM.
