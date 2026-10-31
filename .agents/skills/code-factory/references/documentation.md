# Documentation (factory-documenter methodology)

The `factory-documenter` subagent updates documentation after every successful `implement` or
`refactor` run. It runs automatically — the factory owner never has to ask. It is skipped for
`review` and `security_audit` (those tasks change no behavior to document).

This methodology is adapted from the open-source `developer-documentation-skill`
(https://github.com/NateBJones-Projects/developer-documentation-skill) to the factory's context.

## Core principles

1. **Read the code before writing.** Documentation describes what the code actually does. Never
   write docs from the plan, memory or assumptions — open the changed file, read it, then write.
2. **Separate implemented behavior from plans.** Document what is implemented now. Do not write
   "will support X" or "planned for Y" unless the code already does it. Future plans belong to the
   plan, not to shipped docs.
3. **Choose the form for the reader's task.** A quick "how to run" belongs in a README; a
   behavioral contract belongs in a doc-comment above the function; a domain concept belongs in an
   in-repo `.md`. Match form to reader, not to habit.

## Scope — what "documentation" means

- **In scope (may update):** doc-comments in source files (Rust `///`/`//!`, Python docstrings,
  JSDoc `/** */`, Go `//` doc comments, etc.), `README.md`, and `.md` files that sit next to code
  or describe modules/usage.
- **Out of scope (never touch):** executable code lines, test files, configuration files
  (`.toml`, `.yaml`, `.json`, `.ini`, `.env*`), build manifests, lockfiles. If a behavior change
  needs a code edit, that is the coder's job — report it as a skipped file, never fix it here.

## Validation (built-in, deterministic)

The documenter runs `scripts/validate_documentation.py` in two steps — a **snapshot** before
editing, then a **check** after. The task's `repo_path` is resolved ONCE to an absolute path and
both commands target that resolved repository: `--repo <resolved repo_path>`, with the baseline
snapshot INSIDE it — `<resolved repo_path>/.code-factory/docs_baseline`, written out explicitly,
because `--baseline` is resolved against the cwd and only the absolute form keeps it inside the
resolved repo. `--files` are repo-relative:

```bash
python .agents/skills/code-factory/scripts/validate_documentation.py snapshot \
  --repo <resolved repo_path> --baseline <resolved repo_path>/.code-factory/docs_baseline \
  --files <rel-path> ...
# ... edit the docs only ...
python .agents/skills/code-factory/scripts/validate_documentation.py check \
  --repo <resolved repo_path> --baseline <resolved repo_path>/.code-factory/docs_baseline \
  --files <rel-path> ...
```

After the plain `check` passes, run it once more with `--derive`: the validator then recomputes
the changed file set itself from `git -C <repo> status --porcelain` — modified TRACKED files PLUS
untracked (`??`) new ones, ignored (`!!`) entries excluded — and FAILS when a changed file is
missing from `--files`: a brand-new undeclared source file is as much an edit as a modified one,
so the declared list is not the authority on what was touched (when git cannot answer, the mode
degrades with a message and exit 2, never a traceback).

The validator checks, deterministically (stdlib only):

1. every touched file is a documentation target (`.md` or a source file whose diff vs the
   snapshot contains only doc-comment lines), and
2. no test/config/build file was modified, and
3. no non-documentation line changed in any touched source file.

Retry budget is **1**: pass → done; fail → fix the violations and run `check` once more; fail
again → record a `documentation_debt` item, return `status: debt`, and let the factory continue.
The factory must never fail because of documentation.
