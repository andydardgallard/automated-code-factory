# Security Audit Task Type

Goal: a universal security audit of ANY project — automatically detect the artifact types
present, run only the relevant checks, and produce (a) a set of reports and (b) a generated
fix-task file in the factory's own task format. The factory does **not** fix vulnerabilities by
itself — the user reviews/edits the generated file and runs it as a separate `implement` task.

## 1. Scope and limits

- The factory analyzes **code and configuration inside the repository** only.
- It does NOT scan live networks, perform penetration testing, or attack running systems.
  Anything that cannot be expressed as code/config in the project is out of scope.
- Audit is **full-audit only** — every run covers the whole repository. There is no incremental
  mode. Above the size budget the coverage is achieved by sharding rather than by shrinking the
  scope: the union of the shards is still the whole repository (section 5.1).

## 2. Adaptive artifact detection (deterministic, no LLM for the detection)

Detect which artifact types are actually present and run only the relevant checks:

| Artifact type | Detection signals (examples) | Checks run |
|---------------|------------------------------|------------|
| Application code | `*.rs` `*.py` `*.js` `*.ts` `*.go` `*.java` `*.cs` `*.rb` `*.php` `*.swift` `*.c` `*.cpp` | code vulnerabilities, dependency security, hardcoded secrets, dangerous business logic |
| Infrastructure as Code | `*.tf` `*.tfvars` `*.yaml`/`*.yml` (K8s/Helm), `CloudFormation` templates, `pulumi` | insecure resource configs, open permissions, unencrypted storage, weak IAM |
| Containers / orchestration | `Dockerfile` `docker-compose*.yml` `*.k8s.yaml` `*.helm.yaml` `deployment.yaml` | base-image risks, running as root, exposed ports, missing resource limits, privileged mode |
| Network config | `nginx*.conf` `*.conf` (server), `iptables`/`ufw` rules, `*.rules`, firewall/policy files | weak TLS, open ports, missing auth, permissive policies |
| Secrets & configs | `.env*` (non-example), `*.pem`, `*.key`, config files with tokens | secret leakage, weak defaults, secrets committed to git |
| Dependencies | `Cargo.lock` `package-lock.json` `go.sum` `poetry.lock` `requirements.txt` `pom.xml` `build.gradle` | known-vulnerable dependency ranges, outdated pinned versions |

If a type is absent, its checks are skipped — the audit is focused on what is real, never on a
generic checklist.

## 3. Autonomous tool selection

The factory chooses the analysis techniques itself, based on artifact types and content. It may:
- use the project's own build/dependency tools to resolve and inspect the dependency graph;
- run static-analysis / linting tools already present in the environment (grep/ripgrep-based
  patterns, `semgrep`, `bandit`, `trivy`, `npm audit`, `cargo audit`, `govulncheck`, etc.);
- fall back to deterministic regex/heuristic checks when a dedicated scanner is unavailable.

The user never specifies the tools. The factory records which tools/techniques it used in the
audit report.

## 4. Deliverables

Run under `.code-factory/audit/` (and a human-readable summary at the repo root if the user asks):

1. `report.md` — findings grouped by artifact type, each with severity (critical/high/medium/low),
   the affected file:line, and a one-line explanation.
2. `fix-tasks.yaml` (or `fix-tasks.md`) — a generated file in the **factory task format**
   (`title`, `description`, `task_type: implement`, `acceptance_criteria`, optional `models`,
   `commit_exclude`). Each finding (or a grouped cluster of related findings) becomes one
   acceptance criterion / task so the user can run it as a separate `implement` flow.

The factory must NOT start fixing after the audit. The user edits the generated file if needed
and launches the fixes themselves.

## 5. Flow

1. **Detect artifact types** (section 2).
2. **Plan the audit** — map each present type to its checks and tools (section 3); measure the
   repository (`repo_inventory.py inventory`) and shard it when it exceeds the size budget
   (section 5.1).
3. **Run the audit** — the `factory-security-auditor` subagent (read-only) inspects the code and
   configs, never modifying anything. On a sharded run there is one auditor per shard, in parallel.
4. **Merge the shard findings** with `merge_findings.py` (section 5.1) — the merged report is the
   audit's finding set.
5. **Write reports + fix-task file** (section 4).
6. **Acceptance** — every present artifact type has a report section; the fix-task file is a valid
   factory task file; no vulnerability was auto-fixed.

## 5.1 Shard protocol for large repositories

The security audit covers the whole repository, which does not fit into one auditor context. Above
the size budget (**N = 20 000 lines by default**) the audit is sharded with the same deterministic
protocol the whole-repo review uses (`references/code-review.md` §1.1) — inventory, parallel
subagents, zero-LLM merge:

1. **Inventory / shards (deterministic, zero LLM)** — `repo_inventory.py` walks the tree (VCS and
   build dirs excluded, symlinks not followed, binaries skipped) and packs the sorted file list
   into shards of at most N lines; a file longer than N lines becomes its own shard flagged
   `oversized`:

   ```bash
   python .agents/skills/code-factory/scripts/repo_inventory.py inventory --repo <project-root>
   python .agents/skills/code-factory/scripts/repo_inventory.py shards --repo <project-root> --max-lines 20000
   ```

   The shard list defines the audit's work packages; shards never overlap and their union is the
   whole repository.
2. **Parallel auditor subagents** — one `factory-security-auditor` per shard; each receives only
   its shard's file list, the detected artifact types (section 2) and the checks/tools mapped to
   them (section 3), plus the shard ID it must report under. No auditor gets whole-repo context and
   no auditor edits anything.
3. **One findings file per shard**, written to `.code-factory/audit/shards/<shard-id>.json`, in the
   same machine contract as the review shards — because `merge_findings.py` validates it exactly:

   ```json
   {"shard": "<id>",
    "verdict": "approve | request_changes",
    "findings": [{"severity": "critical | major | minor | nit",
                  "file": "<path>", "line": 42,
                  "title": "short one-line statement",
                  "detail": "what is wrong, the affected construction and the fix (§5.1 mapping)"}]}
   ```

   The `severity` values are the factory contract (`critical | major | minor | nit`), which map to
   the human-facing audit scale of section 4 as `critical → critical`, `major → high`,
   `minor → medium`, `nit → low`. `line` is an integer or `null`. `verdict` is
   `request_changes` when the shard found any critical or major issue, else `approve`.
4. **Deterministic merge (zero LLM)** — the main agent merges the shard files with the script:

   ```bash
   python .agents/skills/code-factory/scripts/merge_findings.py \
     --inputs .code-factory/audit/shards/*.json \
     --report .code-factory/audit/findings-merged.json \
     --md .code-factory/audit/report.md
   ```

   Deduplication by `(file, line, normalized title)`, sorting by severity then file/line/title, and
   a merged `request_changes` verdict when any shard asked for it or any critical finding exists
   (exit `0` = `approve`, `1` = `request_changes`, `2` = broken input). Because the merge is not
   LLM-written, a finding found by two shards appears once and cannot be edited away between the
   shards and the report.
5. **Feed the merged findings into the deliverables** — the human-readable `report.md` (section 4,
   item 1) is written from the merged JSON (grouped by artifact type, severities mapped as above),
   and `fix-tasks.yaml` (section 4, item 2) is generated from the same merged list, so every
   finding turns into a fix task exactly once. `verify_quotes.py` re-checks the quotes behind the
   merged findings before they are published, and the shard files stay as the audit trail.

Below the size budget the audit runs single-agent as before: one auditor, one findings file, no
sharding ceremony.

## 6. Specialized agent

- `factory-security-auditor` — read-only audit agent. Analyzes the detected artifact types,
  applies the relevant checks, and returns structured findings + the generated fix-task file
  content. It never edits the repository. In a sharded audit several instances run in parallel,
  one per shard (section 5.1), each bound to its own shard ID.
