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
  mode.

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
2. **Plan the audit** — map each present type to its checks and tools (section 3).
3. **Run the audit** — the `factory-security-auditor` subagent (read-only) inspects the code and
   configs, never modifying anything.
4. **Write reports + fix-task file** (section 4).
5. **Acceptance** — every present artifact type has a report section; the fix-task file is a valid
   factory task file; no vulnerability was auto-fixed.

## 6. Specialized agent

- `factory-security-auditor` — read-only audit agent. Analyzes the detected artifact types,
  applies the relevant checks, and returns structured findings + the generated fix-task file
  content. It never edits the repository.
