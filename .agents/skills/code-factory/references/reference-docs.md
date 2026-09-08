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
reference_skills:
  - "market-making"                       # reuse an existing skill by name
```

- `reference_docs` — documents to turn into skills. First use of a path generates the skill;
  reuse of the same path reuses it (deterministically, by content hash); a changed source updates
  it incrementally.
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

## Relevance matrix (deterministic — no LLM reasoning)

Which subagents receive the resolved skill instructions in their dynamic context:

| Subagent | Reads skills? | Rule |
|----------|---------------|------|
| analyzer | yes | always, if any skills exist |
| planner | yes | always, if any skills exist |
| coder | yes | always, if any skills exist |
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

`skill_base.py` provides: `hash <path>` (SHA-256 of file or folder), `lookup <name>` (resolve and
report reuse/update/error), `record <name> <source> <hash> <task_id>` (update the manifest),
`list` (dump the manifest). Reuse vs regeneration is decided by the content hash, never by the
LLM.
