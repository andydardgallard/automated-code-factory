---
name: kaggle-agents-course
description: Distillation of the Kaggle 5-Day AI Agents Intensive (Google x Kaggle): agent architecture, model routing, tool design and output contracts, agent quality evaluation (trajectory is the truth), and the move to production. A reference for the subagents of the autonomous code factory.
---

# Kaggle Agents Course

> Source: transcripts of the Kaggle 5-Day AI Agents Intensive Course (whitepaper companion podcasts +
> daily livestreams, days 1–5), the `../materials` directory (14 directories, .md/.txt transcripts).
> This is a distillation of ideas, not lecture notes; the full transcripts are in the source.

## Contents

- [Overview](#overview)
- [Key concepts](#key-concepts)
  - [Day 1 — Agent anatomy and model routing](#day-1--agent-anatomy-and-model-routing)
  - [Day 2 — Tools and the concise output contract](#day-2--tools-and-the-concise-output-contract)
  - [Day 3 — Context, sessions, memory](#day-3--context-sessions-memory)
  - [Day 4 — Agent quality: trajectory is the truth](#day-4--agent-quality-trajectory-is-the-truth)
  - [Day 5 — Production: generator ≠ judge and model diversity](#day-5--production-generator--judge-and-model-diversity)
- [How to apply in the code factory](#how-to-apply-in-the-code-factory)
- [Business criteria](#business-criteria)
- [Limitations and anti-patterns](#limitations-and-anti-patterns)

## Overview

An agent is not a model in a static workflow but an application: **model (the brain) + tools (the hands) +
orchestration layer (the conductor)**, working in a **think → act → observe** loop until the goal is reached.
The course goes from agent anatomy (Day 1) through tools (Day 2), context/memory (Day 3), quality
evaluation (Day 4), to production multi-agent systems (Day 5). The main thesis: the success of an agentic system
is determined not by the "smartest model" but by the engineering discipline around it — architecture,
contracts, evaluation, observability, and governance.

## Key concepts

### Day 1 — Agent anatomy and model routing

- **Agency taxonomy L0–L4**: L0 — a bare LLM without tools; L1 — a connected problem-solver
  (tools, real time); L2 — a strategic problem-solver (context engineering: the output of one
  step shapes the input of the next); L3 — a multi-agent system (agents call agents as
  tools, delegating goals); L4 — a self-evolving system (creates missing
  tools/agents). Complexity is chosen to fit the task, not "maximal by default".
- **Choose the model by task, not by benchmarks**: the criteria are reasoning quality and
  tool-use reliability on *specific* tasks, not the model's overall rating.
- **Model routing**: an expensive, strong model — for planning and
  high-stakes decisions (low "density" of simple decisions); a fast, cheap one — for mass simple
  steps (summarization, field extraction, greetings). If a user says "hi", you don't need a
  trillion-parameter model to reply. Cost and quality optimized simultaneously.
- **Decomposition instead of a monolith**: don't stuff 50+ tools into one agent — decompose into
  specialists with 5–10 tools each and route to the right one. More steps and tools =
  higher context cost, latency, and regression risk.
- **Agent Ops**: you cannot test with `assert output == expected` (non-determinism); instead —
  rubric-based quality evaluation (LM-as-judge) on a golden dataset, OpenTelemetry traces of the whole trajectory
  as a "black box" for debugging, and turning every recorded failure into a new permanent
  test case ("vaccinating" the system).

### Day 2 — Tools and the concise output contract

- **Tool types**: function tools (explicit functions; docstring = input/output contract),
  built-in (search, code execution — provided by the vendor), agent tools (calling another agent as
  a tool: delegating a subtask with a result returned; control stays with the caller).
- **Tool documentation is the main interface**: the model knows a tool only from its name,
  description, and parameter schema. The name `create_critical_bug_with_priority` is better than `update_jira`.
- **Describe the action, not the implementation**: "create a bug describing the problem", not "call
  function X". The LLM reasons; the tool executes.
- **Publish tasks, not raw APIs**: a tool = one high-level task
  ("book a meeting room"), not a thin wrapper over an endpoint with 15 flags.
- **The concise output contract (key for subagents)**: a tool/subagent does NOT return raw
  arrays of data into the context. It returns: (a) a brief digest, (b) a confirmation of completion, or
  (c) a reference (URI/path to an artifact) where the full data lives. Context bloat = higher cost
  and latency + degraded reasoning of the calling model.
- **Instructive errors**: not "error 500" but "rate limit exceeded, retry in 15 seconds" —
  an error must give the agent context and a recovery path. Silent failures are forbidden: calling
  agents must understand the cause and adapt.
- **Scaling tools**: with hundreds of tools, their definitions are not loaded into the context —
  first a semantic search (tool retrieval, RAG over the tool registry) picks the top 3–5
  relevant ones, and only they go into the prompt.

### Day 3 — Context, sessions, memory

- **Context engineering**: answer quality is determined not by the prompt itself but by the structure
  of the context the model sees at each step.
- **Short-term memory** — the working notepad of the current task (the history of action–observation pairs in
  the loop). **Long-term** — across sessions, persistent (preferences, past interactions);
  architecturally, an ordinary tool (RAG over a store).
- **Window management**: filtering, compaction, and caching of context are mandatory mechanisms for
  long tasks; prompt caching of recurring prefixes reduces cost, latency, and
  non-determinism.

### Day 4 — Agent quality: trajectory is the truth

- **Three pillars**: (1) trajectory is the truth — quality is determined by the agent's entire path, not
  only the final answer: a correct answer reached by a "crooked" path (25 steps instead of 3, near-miss
  blunders) is still a quality defect; (2) observability is the foundation (logs, traces, metrics);
  (3) evaluation is a continuous cycle (quality flywheel), not a one-off QA gate before launch.
- **Insidious failures**: an agent may return "200 OK" with an actually wrong/dishonest result.
  Typical failure modes: algorithmic bias, hallucinations, concept drift (the world changed,
  the agent did not), emergent undesirable behaviors (exploiting rule loopholes to reach the goal).
- **Four quality dimensions**: effectiveness (whether the user's goal was achieved, not just
  "ticket closed"), efficiency (latency, token cost, directness of the path), robustness
  (behavior under API errors and unclear instructions: retry, clarification, not a crash or guessing),
  safety & alignment (boundaries, refusal of dangerous actions, resilience to prompt injection — without this
  the rest is meaningless).
- **Outside-in evaluation hierarchy**: first end-to-end (black box: success/failure, satisfaction);
  on a problem, open the "glass box" and analyze the trajectory: where it broke — planning
  (looping, context loss), the tool call (a hallucinated tool, wrong
  parameters), or interpretation of the tool's response (an ignored 404).
- **LLM-as-judge done right**: pairwise comparison (A vs B on a rubric, forced
  winner choice → win rate), not absolute 1–5 scores (central tendency bias — everything "average").
  Beyond that — agent-as-judge: a specialized agent evaluates another agent's reasoning trace.
- **Regression via trajectories**: a successful run is saved as an eval case (the whole sequence
  of thoughts and tool calls); deviation from it in later runs = a regression signal.
- **Observability**: structured logs (JSON: chain-of-thought, tool inputs/outputs), traces
  (OpenTelemetry; spans link the cause-and-effect thread), metrics of two kinds — system
  (P50/P99 latency, error rate, cost per task — for ops) and quality (trajectory adherence,
  helpfulness — for DS/PM). Dynamic sampling: trace 100% of errors and ~10% of successful requests.
- **Human-in-the-loop**: humans create the golden set and are the final arbiter of quality; the reviewer's UI
  shows the dialogue and the internal reasoning trace side by side; for critical actions
  (a payment, a sensitive email) — mandatory human approve/reject.

### Day 5 — Production: generator ≠ judge and model diversity

- **Generator ≠ judge**: the checker must not be the same as the generator. Patterns: supervisor
  (a central agent watches the flow, breaks loops) and an independent critic agent (deep-dives and
  verifies facts, up to code execution). This protects against "echo chambers" where agents mutually
  confirm a wrong assumption.
- **Model diversity**: critical checking steps are performed by a different (usually stronger) model
  than the worker agents (e.g., workers — Flash, supervisor — Pro). Otherwise the checker "blindly
  agrees" with the workers because of the shared biases of one model.
- **Agent teams as organizations**: planner → executors → reviewer (checks that the plan
  was executed correctly) → optimizer (improves the plan for the future). Hierarchy, per-role KPIs, and mandatory
  human-in-the-loop for critical decisions — a human remains accountable.
- **Graceful degradation**: retry with exponential backoff; when a specialized
  agent is unavailable — rerouting to a generalist (partial task completion is better than refusal); for critical
  actions — a transparent UX ("I can't book right now; here is the route and instructions") instead of
  a silent substitution. Errors must be descriptive so the other agents can adapt.
- **Cost and latency under control**: prompt caching (recurring prompt prefixes),
  model routing by task complexity, constraint sampling (generating only from the allowed
  output space instead of free text), early termination by guardrails callbacks.
- **Evaluation over time, not a snapshot**: quality metrics are monitored continuously; performance
  drift on new data/scenarios is caught.

## How to apply in the code factory

- **Analyzer / Planner** (strong model): these are the "planning and high-stakes decisions" steps in the
  Day 1 classification — a primary model is justified for them; their output (the plan) is the input for the cheap executors.
- **Coder / Documenter** (routine steps): candidates for the secondary model per the model routing principle —
  simple, high-frequency tasks do not need the top model.
- **Subagents = tools**: when designing subagent prompts, apply the Day 2 contracts —
  a clear role name, an action description (not implementation), one high-level task, **concise output**:
  return a digest/confirmation/file path, not a content dump.
- **Tester / Code-reviewer are the judge**: per Day 5 they must be independent of the code generator
  and, where possible, rely on a different model (model diversity) — this separates the biases of the coder and
  the checker.
- **Evaluating factory runs**: per Day 4, look not only at "tests passed" but at the run's
  trajectory (how many retries, where error routing fired, deviation from the reference plan); reference
  successful runs are the regression base.
- **HITL**: the factory's critical actions (commit, rollback, public API change) go through
  user confirmation; business criteria are set by a human.

## Business criteria

Verifiable rules derived from the course (for tester/reviewer):

1. Subagent/tool output is compact: a digest, a confirmation, or a link to an artifact — not the raw
   data in full (concise output contract, Day 2).
2. Errors are descriptive and instructive: the message explains the cause and the recovery path; there are no silent
   failures (Day 2, Day 5).
3. Generator and checker are separated: code is checked by a different agent (and preferably a different model)
   than the one that wrote it (generator ≠ judge, model diversity, Day 5).
4. Quality is evaluated by trajectory, not only by the final result: redundant
   steps, loops, and ignored tool errors are recorded (Day 4).
5. Critical actions require human confirmation (HITL, Day 4–5).
6. Complex tasks are routed to the strong model; simple mass tasks — to the cheap one; a monolithic
   agent with dozens of tools is decomposed (Day 1, Day 5).
7. Every recorded failure is turned into a permanent test case; quality metrics are tracked
   over time, not once (Day 1, Day 4).

## Limitations and anti-patterns

- Do not pick a model "by benchmark" and do not use the top model for every step — that wastes
  budget with no quality gain (Day 1).
- Do not test agents like classic software (`assert output == expected`): the output is non-deterministic;
  rubrics, pairwise comparisons, and a golden dataset are needed (Day 1, Day 4).
- Do not take "200 OK" as success: agent failures are insidious (hallucinations, drift, loopholes) and require
  observability (Day 4).
- Do not return raw arrays of data into the calling model's context — window bloat degrades
  reasoning and inflates cost (Day 2).
- Do not give an agent 50+ tools: decompose into specialists or use tool retrieval (Day 1–2).
- Do not build a "mesh of agents that worked in a demo" without evaluation: stochasticity demands
  principled design; otherwise the responsibility for correctness is shifted onto the user
  (Day 5).
- Do not rely on one model or on generation = checking: echo chambers and shared biases (Day 5).
- Do not remove the human from critical decisions: autonomy does not cancel accountability (Day 4–5).
