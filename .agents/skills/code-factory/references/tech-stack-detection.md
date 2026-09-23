# Tech Stack Detection

Goal: quickly and reliably determine the programming languages, frameworks, build tools and test
commands of a project — for any language or combination of languages. The factory is
language-agnostic; never assume a stack.

## 1. Fast signals (parallel Glob/Grep)

Run these in parallel (use subagents when the project is large):

| Signal file(s) | Stack |
|----------------|-------|
| `Cargo.toml` + `*.rs` | Rust |
| `pyproject.toml`, `requirements.txt`, `setup.py`, `setup.cfg`, `Pipfile`, `poetry.lock`, `uv.lock` | Python |
| `package.json` (check `devDependencies`: typescript? vitest? jest?) | JavaScript / TypeScript |
| `go.mod` + `*.go` | Go |
| `pom.xml`, `build.gradle`, `build.gradle.kts`, `*.java` | Java (Maven / Gradle) |
| `*.csproj`, `*.sln`, `*.cs` | C# / .NET |
| `CMakeLists.txt`, `Makefile`, `*.c`, `*.cpp`, `*.h` | C / C++ |
| `Gemfile`, `*.rb` | Ruby |
| `composer.json`, `*.php` | PHP |
| `mix.exs`, `*.ex`, `*.exs` | Elixir |
| `*.swift`, `Package.swift` | Swift |
| `go.work` | Go workspace |
| `Dockerfile`, `docker-compose.yml` | Containerized (still inspect the language files) |
| `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/` | CI — read to learn canonical build/test commands |
| `Makefile` (root) | Often the canonical entry point: `make test`, `make build` |

## 2. Multi-language projects

- A project may mix languages (e.g., Rust core + Python bindings, TS frontend + Go backend).
- Identify each component, its test command, and its relation to the business task.
- Keep the analysis per component: `frontend/` vs `backend/` vs `core/`.

## 3. Test / build / run commands per stack

| Stack | Install deps | Build | Run tests | Run app |
|-------|-------------|-------|-----------|---------|
| Rust | `cargo build` | `cargo build` | `cargo test` | `cargo run [-- args]` or the binary |
| Python | `pip install -e .` / `uv sync` / `poetry install` | — | `pytest` / `python -m pytest` | `python -m <package>` / entry script |
| Node/TS | `npm ci` / `pnpm install` / `yarn` | `npm run build` / `tsc` | `npm test` / `npx vitest run` / `npx jest` | `npm start` / `node dist/index.js` |
| Go | `go mod download` | `go build ./...` | `go test ./...` | `go run .` / built binary |
| Java/Maven | `mvn dependency:resolve` | `mvn compile` | `mvn test` | `mvn exec:java` / `java -jar target/*.jar` |
| Java/Gradle | `./gradlew build` | `./gradlew build` | `./gradlew test` | `./gradlew run` |
| C#/.NET | `dotnet restore` | `dotnet build` | `dotnet test` | `dotnet run` |
| C/C++ | `cmake -B build && cmake --build build` / `make` | same | `ctest` / custom | built binary |
| Ruby | `bundle install` | — | `bundle exec rspec` / `rake test` | `bundle exec ruby main.rb` |
| PHP | `composer install` | — | `vendor/bin/phpunit` | `php -S ...` / `php index.php` |
| Elixir | `mix deps.get` | `mix compile` | `mix test` | `mix run -e "..."` / `mix phx.server` |
| Swift | `swift package resolve` | `swift build` | `swift test` | `swift run` |

For anything unusual, read the CI workflow or README to find the canonical commands. If tests
cannot run in this environment (missing toolchain), say so explicitly and record it as a
constraint instead of guessing.

## 4. Baseline (regression reference)

Before any change:

1. Run the full test suite with the canonical command.
2. Save the result (pass/fail + summary) to `.code-factory/logs/baseline.md`.
3. Note the runtime/toolchain versions (e.g., `cargo --version`, `python --version`).

The baseline is the definition of "no regression" for the whole task.

## 6. Entry points and configs (needed for business tests)

- Identify how the program is launched and which configuration / input files it consumes
  (e.g., config.toml, CLI args, data files).
- List them — the business-test phase will ask the user which specific configs to run.

## 7. Scout pipeline (Phase 1) — AGENTS.md as Single Source of Truth

After the deterministic steps above, run the Scout pipeline to produce (or refresh) the durable
project model + AGENTS.md that every later phase relies on. AGENTS.md is the Single Source of
Truth about the project: the analyzer/planner/coder read it instead of re-deriving the project
structure from scratch.

### 7.1 Fingerprint gate (deterministic, zero LLM)

Compute BOTH levels of the project fingerprint:

```bash
python .agents/skills/code-factory/scripts/project_fingerprint.py --repo <project-root> --all
# structural: <structural-64-hex>
# content:    <content-64-hex>
```

`--content` prints only the content level, no flag prints only the structural one; `--all` prints
both (`structural: …` / `content: …`). The two levels are independent, and together they decide
whether re-analysis + AGENTS.md regeneration are skipped:

- **structural** — SHA-256 over the working-tree structural signals: stack manifests, CI configs,
  README and the sorted top-level directory listing. It is commit-stable, but **blind to an edit
  inside an existing file deeper than the signal list** (e.g. `src/a/b/c.py` changes while no root
  manifest, CI config, README or top-level entry does).
- **content** — SHA-256 over the tracked content, read from the git index (`git ls-files -s`:
  `mode SHA path` of every non-excluded entry, sorted), so ANY modification of a tracked file
  changes it, including changes level 1 cannot see. Without a usable git repository/index it falls
  back to hashing the working-tree contents (which also catches uncommitted edits). Reading the
  INDEX is deliberate — it is commit-stable, platform-neutral and lets AGENTS.md embed its own hash
  pair — so an UNSTAGED or untracked edit does not move the hash; that blind spot is reported
  instead of hidden: `--content`/`--all` print a stderr note with the count of such changes
  (`worktree_dirty`, the factory's own artifacts excluded), and `check_factory_model.py` raises a
  WARNING when the tree is dirty. Neither ever changes a printed hash or an exit code, and `git add`
  makes the edit visible to the fingerprint.

Both levels exclude the factory's own artifacts (`AGENTS.md`, `memory/`, `task.yaml`, the launchers
`start.sh`/`start.cmd` and the deployers `prepare_factory.sh`/`prepare_factory.cmd`/
`prepare_factory.ps1`), so committing them does not shift either hash (a git tree SHA would, which
would make the "skip when unchanged" branch unreachable). Both hashes are embedded in AGENTS.md on
the first line, so they travel with the commit and survive a clone:

```
<!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->
```

- **Match** (AGENTS.md exists AND **both** embedded hashes == the recomputed ones) → the project
  is unchanged: SKIP the analyzer's structural re-analysis and the AGENTS.md regeneration. Proceed
  directly to the repo-mismatch gate. A content-only change (invisible to level 1) still triggers a
  regeneration — that is exactly what the second level is for.
- **Either hash missing or mismatching / no AGENTS.md** → regenerate the model below.
- A **legacy single-hash line** (`<!-- code-factory-fingerprint: <64-hex> -->`, no `content:` part)
  is a **warning**, not a supported state: such a model cannot see content-only changes, so
  AGENTS.md is regenerated with both hashes. `check_factory_model.py` (§7.4) reports it as a
  warning while it validates both hashes.

### 7.2 Generate AGENTS.md (8 sections)

Generate `AGENTS.md` in the repo root with EXACTLY these 8 `##` sections, in this order:
`Project Overview`, `Technology Stack`, `Architecture Overview`, `Directory Structure`,
`Key Configuration Files`, `Build & Run Instructions`, `Dependencies & Integrations`,
`Known Constraints & Limitations`.

Rules:
- Copy build/test/run commands VERBATIM from config files; record observed bugs/debt in the
  8th section; keep sections self-contained.
- **Existing AGENTS.md is OVERWRITTEN entirely** — the factory owns the file and it always
  contains exactly these 8 sections. Hand-written project notes belong in `memory/summary.md`,
  not in AGENTS.md.
- Put the fingerprint comment with BOTH hashes on the first line
  (`<!-- code-factory-fingerprint: <structural-64-hex> content: <content-64-hex> -->`), then a
  `# <Project Name>` title line, then the 8 sections.
- There is **no init step** in the Scout flow. The factory's own AGENTS.md is already complete;
  the Kimi init slash command would overwrite it and erase the 8 sections, so it is never run.

### 7.3 Two update points

Both points compare BOTH hashes (`--all`) — the SKIP branch requires both to match:

1. **Start of task (Phase 1)** — catch EXTERNAL changes to the project (edited outside the
   factory, at any depth): compute both fingerprints; only if BOTH embedded hashes match, skip the
   regeneration; otherwise regenerate (a content-only difference is enough to regenerate).
2. **End of task (Phase 9)** — reflect the factory's OWN changes: after implementation +
   tests, recompute both fingerprints; if the structure/stack/entry points OR the tracked content
   changed, regenerate AGENTS.md and commit it (respecting `commit_exclude`).

### 7.4 Read the model, don't rebuild it

Every later role reads AGENTS.md as the source of truth:
- **analyzer** — reads AGENTS.md + `memory/summary.md` + recent `memory/change-log.md` entries of
  the CURRENT project (the task's `repo_path`) BEFORE exploring, to anchor on known history
  instead of re-reading git.
- **planner (main agent)** — reads AGENTS.md + the current project's memory at the start (Phase 0/1).
- **coder** — receives the relevant AGENTS.md sections + recent memory entries of the current
  project from the main agent.

`memory/` always belongs to the project at `repo_path` (one memory — one project; `project:`
declared in `memory/summary.md`), never to the factory's own development. A missing `memory/` is
created on first contact with the project via `scripts/memory_project.py init`, and ownership is
verified with `memory_project.py check`.

Verify the model with the deterministic checker:

```bash
python3 .agents/skills/code-factory/scripts/check_factory_model.py --repo <project-root>
```

It asserts: exactly 8 sections, BOTH fingerprints (structural + content) matching, memory format
correct — and it warns (does not fail) on a legacy single-hash fingerprint line. Run it in
`final_integration`: on the factory's own root the checker auto-detects that root itself (3-signal
detector) and SKIPs the AGENTS.md model checks, so no extra flag is needed.

Cache: keep the project model in `.code-factory/state/project-model.yaml`.

