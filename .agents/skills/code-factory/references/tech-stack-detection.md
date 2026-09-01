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

Compute the structural fingerprint of the project's working tree:

```bash
python3 .agents/skills/code-factory/scripts/project_fingerprint.py --repo <project-root>
```

The fingerprint is a SHA-256 over the project's structural working-tree signals: stack
manifests, CI configs, README, and the sorted top-level directory listing. The factory's own
artifacts (`AGENTS.md`, `memory/`, `task.yaml`, `start.sh`) are excluded from the signals, so
committing them does not shift the fingerprint (a git tree SHA would, which would make the
"skip when unchanged" branch unreachable). It is embedded in AGENTS.md on the first line
(`<!-- code-factory-fingerprint: <sha> -->`), so it travels with the commit and survives a
clone.

- **Match** (AGENTS.md exists AND its embedded fingerprint == the recomputed fingerprint) →
  the project is unchanged: SKIP the analyzer's structural re-analysis and the AGENTS.md
  regeneration. Proceed directly to the repo-mismatch gate.
- **Mismatch / no AGENTS.md** → regenerate the model below.

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
- Put the fingerprint comment on the first line: `<!-- code-factory-fingerprint: <sha> -->`,
  then a `# <Project Name>` title line, then the 8 sections.
- There is **no init step** in the Scout flow. The factory's own AGENTS.md is already complete;
  the Kimi init slash command would overwrite it and erase the 8 sections, so it is never run.

### 7.3 Two update points

1. **Start of task (Phase 1)** — catch EXTERNAL changes to the project (edited outside the
   factory): compute the fingerprint; if it matches the embedded one, skip the regeneration;
   otherwise regenerate.
2. **End of task (Phase 9)** — reflect the factory's OWN changes: after implementation +
   tests, recompute the fingerprint; if the structure/stack/entry points changed, regenerate
   AGENTS.md and commit it (respecting `commit_exclude`).

### 7.4 Read the model, don't rebuild it

Every later role reads AGENTS.md as the source of truth:
- **analyzer** — reads AGENTS.md + `memory/summary.md` + recent `memory/change-log.md` entries
  BEFORE exploring, to anchor on known history instead of re-reading git.
- **planner (main agent)** — reads AGENTS.md + memory at the start (Phase 0/1).
- **coder** — receives the relevant AGENTS.md sections + recent memory entries from the main
  agent.

Verify the model with the deterministic checker:

```bash
python3 .agents/skills/code-factory/scripts/check_factory_model.py --repo <project-root>
```

It asserts: exactly 8 sections, fingerprint matches, memory format correct. Run it in
`final_integration` (and use `--memory-only` for the factory's own root, whose AGENTS.md is a
hand-authored manual).

Cache: keep the project model in `.code-factory/state/project-model.yaml`.

