# Cascade — Production Systems RL Environment

| Field | Value |
|-------|--------|
| **Document** | Product & Systems Design |
| **Author** | TBD (engineering owner) |
| **Date** | 2026-07-10 |
| **Status** | Draft (rev 2 — review issues addressed) |
| **Workspace** | `C:\Dev\grok-rl-env` |
| **Python package** | `cascade_env` (stable import path; product marketing name may rename) |
| **Product codename** | Cascade (trademark TBD — rename-ready) |
| **Primary buyers** | Frontier AI lab post-training / agent eval teams |
| **Revision** | 2 |

---

## Overview

Frontier labs need RL environments that train **long-horizon tool-using agents** on work that maps to real products: diagnosing production failures, shipping safe changes, and restoring service health. Existing benchmarks either freeze the problem into static repo diffs (**SWE-bench**), browser UI chores (**WebArena**), or full desktop control (**OSWorld**). None of these give labs a **sandbox of live multi-service systems** with **automatic multi-verifier rewards**, **parameterized task generation**, and a runtime **designed for large-scale parallel episodes on Linux clusters**.

**Cascade** (package: `cascade_env`) is a commercial-grade RL environment in which agents operate against sandboxed production-like stacks (API + database + queue + worker + logs). Each episode injects a concrete task—incident remediation, feature change, config repair, data repair, or similar. The agent observes structured state and tool results; acts via a constrained tool API; and receives a **deterministic terminal composite reward** from multi-verifier checks. No human labeling enters the training loop.

This document specifies product thesis, architecture, task packs, APIs, security, commercial packaging, phased MVP scope (Slice 0 → MVP-alpha → MVP-complete), and an incremental PR plan.

> **Safety banner (product terms):** Cascade is a **sandbox-only** training/eval environment. Never attach agent tools to real production credentials, networks, or customer data. Community tasks that exercise “disable bad config / restore auth” skills must not be run against live systems.

---

## Background & Motivation

### Why labs buy environments

Post-training (RLHF successors, GRPO/PPO, process reward models, agent RL) needs **environments**, not just static preference data. Procurement criteria:

1. **Automatic reward** — scalable to millions of rollouts  
2. **Headroom** — SOTA still fails often enough that gradient signal exists  
3. **Contamination resistance** — public static sets get memorized  
4. **Throughput** — many parallel sandboxed episodes on training clusters  
5. **Integration** — Gymnasium / tool-calling trajectory format  
6. **Anti-hacking** — hard to game the scorer without solving the task  
7. **Product relevance** — coding agents, production ops, enterprise automation  

### Current landscape gaps

| Benchmark / env | Strength | Gap for lab RL |
|-----------------|----------|----------------|
| SWE-bench / SWE-bench Verified | Strong coding oracle (tests) | Static PR patches; no runtime multi-service diagnosis |
| SWE-bench + kubectl / internal prod sandboxes | Realistic if lab already built it | Not a buyable, productized multi-verifier env with packs |
| WebArena / VisualWebArena / AppWorld | Multi-app web/workflow | Flaky UI oracles; heavy browser; less “prod systems” skill |
| The Agent Company | Enterprise workflow outcomes | Adjacent; less ops/incident + multi-service runtime focus |
| OSWorld | Full computer use | High variance; hard reward; expensive sandboxes |
| InterCode / ML-Bench | Interactive code | Narrow domain |
| Chaos Mesh / Litmus + toy apps | Infra chaos | Not packaged for LLM agent RL + clean Gym APIs |
| Lab-internal “staging gyms” | Highest realism | Non-transferable; no shared holdout market |

**Why not just SWE-bench + kubectl?** Static repo oracles miss runtime cascades (queue poison, bad retries, partial migrations, mis-set flags visible only under load/async workers). kubectl-on-shared-staging is non-isolable for RL (noisy neighbor, unsafe, non-reproducible). Cascade sells **ephemeral isolated stacks + multi-verifier rewards + packs**.

**The gap Cascade fills:** *live multi-service production reasoning* with *test + health + invariant oracles*, packaged for **agent RL and sealed holdout eval**.

### Pain points Cascade solves

- Labs overfit coding agents to “edit file → run pytest” and still fail on bad migrations, poisoned queues, cascading timeouts, or mis-set feature flags.  
- Eval suites are static and leak into pretraining corpora.  
- Spinning up realistic stacks per episode is operationally hard; Cascade owns that as the product.  
- Single-metric rewards invite reward hacking; Cascade multi-verifies with an immutable verifier plane.

---

## Product Thesis (Decision)

### Chosen product

**Cascade** — *Production multi-service incident & change RL environment.*

**One-line pitch:**  
> Train agents that keep software systems alive: diagnose incidents, fix code/config/data, and restore service health—with automatic multi-verifier rewards in Docker sandboxes.

### Why this thesis (vs alternatives)

| Candidate | Sellability | Verifiable reward | Headroom | Small-team MVP | Differentiation | Score |
|-----------|-------------|-------------------|----------|----------------|-----------------|-------|
| **A. SRE / production systems (Cascade)** | Very high — maps to coding *and* ops agents | Excellent (tests + health + invariants) | High (multi-hop diagnosis) | Strong (Compose stacks, seeded faults) | Distinct from SWE/Web/OS | **Best** |
| B. Enterprise multi-app workflow | High | Medium (UI/state flaky) | High | Weak (many fake apps) | Crowded | Good later pack |
| C. Data platform agent | Medium | Excellent (SQL oracles) | Medium | Medium | Niche vs coding race | Strong secondary pack |
| D. Secure code / appsec | Medium–high (ethics friction) | Excellent if harnesses | High | Medium | Dual-use risk | Defer / gated pack |
| E. Pure K8s chaos-only | Medium | Medium | High | Weak for small team | Ops-only | Subsumed by A |

**Decision rationale:** Option A maximizes capability signal + clean reward + scale while remaining buildable: one canonical Compose app, fault injection library, verifier suite, Gymnasium + optional rollout server. B and C become **task packs** later.

### ICP (Ideal Customer Profile)

| Role | Relationship |
|------|----------------|
| **Buyer** | Lab leadership / agent post-training lead; eval platform owner |
| **Champion** | Research engineer building RL loops for tool-using agents |
| **User** | Training jobs; eval harnesses; capability reports |
| **Not primary** | Hobbyists (community only); traditional SRE tool vendors |

### What “sold” looks like (v1 commercial wedge)

**Primary wedge (first revenue):** **sealed holdout evaluation** + reliability of scores across model versions—not “replace our entire training stack on day one.”

1. Lab runs community pack for open baselines / papers.  
2. Lab licenses **private holdout packs** (or hosted scoring) for gated model selection.  
3. Same runtime later used for **training-scale** rollouts once provision latency and GC are proven.  
4. **Enterprise SKU:** port customer’s internal app shape (custom CAUT)—explicit services motion, not MVP.

### Naming & rename readiness

- **Python package / import path:** `cascade_env` — treat as stable for code.  
- **Product/marketing name “Cascade”:** trademark clearance open; modules must not hardcode marketing strings beyond display names in docs. Renaming product ≠ renaming package if trademark fails (or both rename together via single alias module).

---

## Goals & Non-Goals

### Goals (phased)

| Phase | Goal |
|-------|------|
| **All phases** | Production-shaped multi-service env with automatic rewards; anti-reward-hacking via multi-verifier + immutable infra plane |
| **Slice 0** | Prove inject → verify → teardown → JSONL without full agent tool surface |
| **MVP-alpha** | Gymnasium tool-agent loop; task families **T1–T3**; security defaults on; Windows Desktop dev viable |
| **MVP-complete** | Task families **T1–T5**; denser community pack; concurrent-episode isolation tests |
| **v1** | Parameterized composition rules; HTTP rollout server; warm pools; ≥8 parallel/node on Linux; enterprise holdout distribution |

1. Deliver a **production-shaped** multi-service environment with **automatic rewards** and **seed-stable task materialization**.  
2. **MVP-alpha:** ≥3 task families (T1–T3). **MVP-complete:** ≥5 families (T1–T5). Roadmap **10+**.  
3. **Contamination resistance:** parameterized templates + seeds (MVP); composition rules (v1); **paid/sealed holdouts are the real long-term defense**.  
4. **Gymnasium-compatible** tool-calling agent API; optional HTTP rollout server (**post-MVP**).  
5. **Docker Desktop (Windows + WSL2)** for local dev; **Linux** for CI and training clusters.  
6. **Commercial packaging:** free community pack; paid sealed holdouts; services for custom CAUT.  
7. **Anti-reward-hacking:** primary + hidden verifiers, cheat catalog acceptance tests from first verifier PR.  
8. **Timeline:** Slice 0 in ~1–2 engineer-weeks; MVP-alpha in ~6–8 engineer-weeks (2 engineers); MVP-complete +~3–4 engineer-weeks—not “one person one week.”

### Non-Goals (MVP and near-term)

- Full Kubernetes multi-tenant cluster simulation (v2 `runtime: k8s` interface only stubbed).  
- Real browser/desktop computer-use.  
- Training foundation models or shipping a proprietary LLM.  
- Human-in-the-loop reward labeling.  
- Replacing customer’s entire eval platform.  
- Live internet tools for agents (egress denied).  
- Continuous-control / numeric-vector RL baselines (Atari-style).  
- Cryptographically unbreakable local license enforcement on open source (see Commercial).  
- Guaranteeing zero escapes on hostile host misconfiguration.

---

## Competitive Landscape

| Product / Bench | Domain | Reward | Parallelism | Commercial? | Cascade vs |
|-----------------|--------|--------|-------------|-------------|------------|
| SWE-bench | Repo bugfix | Tests | Per-instance containers | Research / hosted | Adds **runtime services, incidents, multi-verifier** |
| SWE-agent / OpenHands | Coding agents | Depends | Varies | Open source | We sell **env+tasks**, not agent framework |
| WebArena / AppWorld | Web / multi-app | Rubrics / state | Browser heavy | Research | APIs/DB/health oracles; no DOM |
| OSWorld | Desktop | Mixed | Expensive VMs | Research | Lighter Docker services |
| The Agent Company | Enterprise tasks | Outcome checks | Moderate | Research-ish | We prioritize SRE/prod multi-service |
| InterCode | Interactive code | Execution | Moderate | Research | Narrower |
| Chaos Mesh / Litmus | Infra chaos | Ops metrics | Cluster | OSS tools | Not LLM-agent RL packaged |
| Lab-internal staging gyms | Custom prod shape | Custom | High | Internal | Cascade is **buyable + shared holdouts** |

**Positioning:** *“SWE-bench for live production systems.”*  
**v1 sales motion:** holdout eval reliability first; training-scale second.

---

## Core Task Taxonomy

### Scope labels (normative)

| Label | Families | When |
|-------|----------|------|
| **MVP-alpha (DoD for “working product”)** | **T1, T2, T3** | Required for MVP ship |
| **MVP-complete** | **T1–T5** | Required before “full MVP” marketing / community v0.2 |
| **Roadmap** | **T6–T15** | Post-MVP |

Shipping without T4/T5 does **not** fail MVP-alpha. Shipping without T1–T3 **does**.

### Task families

| ID | Family | Phase | Agent goal | Primary oracle | Example |
|----|--------|-------|------------|----------------|---------|
| **T1** | Incident diagnosis & repair | alpha | Restore health after injected fault | Health + golden HTTP + family hidden invariant | Worker retry storm |
| **T2** | Bugfix (runtime-evident) | alpha | Fix code; behavior via live services | Pytest public **in success_requires** + health + hidden | Pagination off-by-one |
| **T3** | Config / feature-flag remediation | alpha | Correct misconfig | Behavioral tests + config invariant | Wrong `MAX_RETRIES` |
| **T4** | Schema / data repair | complete | Fix migration or corrupt rows | Task-specific DB invariants + API tests | Partial migration null FKs |
| **T5** | Safe change / feature ship | complete | Implement small feature under constraints | Feature tests + regression + auth invariant | Add discount field/endpoint |

### Roadmap families (T6–T15)

| ID | Family | Notes |
|----|--------|-------|
| **T6** | Rolling deploy / rollback | Bad deploy; roll back or hotfix |
| **T7** | Dependency / version pin failure | Lib/image mismatch |
| **T8** | Observability-only root cause | Metrics/logs; code fine (**needs metrics stack**) |
| **T9** | Multi-service contract break | API rename without consumer update |
| **T10** | Queue backlog / poison pill | Isolate bad messages |
| **T11** | Security misconfig (non-exploit) | Debug mode left on — policy-safe |
| **T12** | Cost/SLO tradeoff | Latency under load (**post-alpha; partial credit first**) |
| **T13** | Data pipeline pack | Option C skills |
| **T14** | Multi-tenant isolation bug | Cross-tenant hidden probes |
| **T15** | Long-horizon runbook | Ordered multi-step maintenance |

### Difficulty tiers

- **L1:** Single service, explicit log error, one-file/config fix.  
- **L2:** Cross-service, needs logs + code/config.  
- **L3:** Cascading failure, red herrings, strong hidden invariants.  
- **L4:** Partial observability, tight step budget, multi-fix coordination.

---

## Proposed Design

### High-level architecture

```mermaid
flowchart TB
  subgraph Client["Training / Eval Client"]
    Trainer["RL Trainer / Agent Harness"]
    GymAPI["cascade_env.Gymnasium Env"]
    HTTPClient["HTTP Rollout Client post-MVP"]
  end

  subgraph ControlPlane["Cascade Control Plane host process"]
    EpisodeMgr["Episode Manager"]
    TaskGen["Task Loader / Sampler"]
    Verifier["Multi-Verifier Orchestrator"]
    Traj["Trajectory Logger JSONL"]
    GC["Episode GC / Reaper"]
    Courtesy["Pack allowlist courtesy check"]
  end

  subgraph Sandbox["Per-Episode Compose Project"]
    Compose["compose -p cascade_ep_xxx"]
    API["api"]
    DB["postgres"]
    Q["redis"]
    W["worker"]
    GW["tool-gateway"]
    VR["verifier runner"]
  end

  Trainer --> GymAPI
  Trainer --> HTTPClient
  GymAPI --> EpisodeMgr
  HTTPClient --> EpisodeMgr
  EpisodeMgr --> TaskGen
  EpisodeMgr --> Compose
  EpisodeMgr --> GW
  EpisodeMgr --> Verifier
  EpisodeMgr --> Traj
  EpisodeMgr --> Courtesy
  GC --> Compose
  GW --> API
  GW --> DB
  GW --> Q
  Verifier --> VR
  VR --> API
  VR --> DB
```

**Note:** License/entitlement is a **courtesy client check + distribution control**, not a security boundary for local open-core installs (see Commercial).

### Canonical application under test (CAUT): Shopstack

MVP ships **one** multi-service app: **Shopstack** (minimal commerce: catalog + orders + async fulfillment).

| Service | DNS name | Role | Tech (MVP-alpha) |
|---------|----------|------|------------------|
| `api` | `api` | REST API | FastAPI + SQLAlchemy + Uvicorn |
| `postgres` | `postgres` | System of record | Postgres 16 |
| `redis` | `redis` | Queue (Redis lists) | Redis 7 |
| `worker` | `worker` | Order fulfillment consumer | Python process |
| `tool-gateway` | `tool-gateway` | Agent tool execution | Python FastAPI sidecar |
| `verifier` | (one-shot `compose run`) | Hidden tests + golden paths | Python + pytest + httpx |

**Deferred from MVP-alpha:** `proxy`/nginx, Prometheus/Vector stack, metrics UI, `metrics.query` tool, hard SLO success gates.  
**MVP-alpha logs:** `docker compose logs` via `logs.tail` tool only (no full obs mesh).

#### Shopstack realism bar (MVP-alpha minimum)

Must include—not a toy counter:

1. **Authn:** API key or JWT header on mutating routes; seed user/service key in workspace `configs/`.  
2. **Idempotent order create** via `Idempotency-Key` header.  
3. **At-least-once worker:** Redis list `BRPOP` + ack; safe double-process (order state machine).  
4. **Schema migrations:** SQL files applied on api/worker startup (or migrate init container).  
5. **Structured JSON logs** with `request_id` / `order_id`.  
6. **Stable compose DNS names** (`api`, `postgres`, `redis`, `worker`) — part of the agent-facing API.

See **Appendix A** for routes, ERD, golden path, worker FSM, compose sketch.

### Code change propagation (normative — Issue 1)

**MVP decision: bind-mount workspace + process restart (no image rebuild mid-episode).**

| Mechanism | MVP? | Detail |
|-----------|------|--------|
| Host materializes episode workspace dir | Yes | From scenario template + mutators |
| Bind-mount `/workspace` → `api` and `worker` code paths | Yes | Same files agent edits via `files.*` |
| `services.restart` after code/config edit | Yes | **Required contract** for agents; scripted agent always restarts |
| Optional `uvicorn --reload` on `api` | Yes (api only) | Speeds T2/T5; worker still restart |
| Worker file auto-reload | No | Explicit `services.restart` only for worker |
| `docker compose build` / image rebuild mid-episode | **Forbidden** | Blows step budget; Desktop latency |
| Dockerfiles `COPY` code | Build-time only | Images ship deps; **runtime code from mount** |

**Acceptance criteria (PR3/PR4):**

1. Edit `app/api/...` handler → `services.restart(["api"])` or reload → `http.request` reflects change within **10s** Linux / **20s** Docker Desktop.  
2. Edit worker handler → `services.restart(["worker"])` → next dequeued job uses new code within **15s** / **30s** Desktop.  
3. No test or task requires rebuild.

```mermaid
sequenceDiagram
  participant A as Agent
  participant GW as Tool Gateway
  participant FS as Bind-mounted /workspace
  participant API as api container

  A->>GW: files.write(path, content)
  GW->>FS: write jailed path
  A->>GW: services.restart(api)
  GW->>API: compose restart api
  API->>FS: re-import code from mount
  A->>GW: http.request(GET /health or business route)
  GW->>API: internal DNS
  API-->>A: response reflecting edit
```

### Episode lifecycle

```mermaid
sequenceDiagram
  participant A as Agent/Trainer
  participant E as Episode Manager
  participant D as Docker Compose
  participant T as Tool Gateway
  participant V as Verifiers

  A->>E: reset(task_id | sample())
  E->>E: load task spec + seed; materialize workspace
  E->>D: up project (unique name, labels, no host ports)
  E->>D: wait healthy (timeout)
  E->>E: inject fault / apply mutators; restart affected services
  E-->>A: observation_0, info (reward=0)
  loop until term
    A->>E: step(action)
    E->>T: execute tool call
    T-->>E: tool result
    E->>E: update obs, budget; step_reward = -cost only
    E-->>A: obs, reward, terminated, truncated, info
  end
  E->>V: run primary + secondary verifiers
  E->>E: compute terminal reward / success
  E->>D: down -v (finally block)
  E-->>A: final reward + trajectory path
```

**States:** `PROVISIONING → HEALTHY_BASELINE → TASK_INJECTED → AGENT_CONTROL → VERIFYING → TEARDOWN → DONE`.

**Timeouts (defaults):**

| Phase | Default |
|-------|---------|
| Provision | 120s (Desktop: 180s) |
| Inject | 30s |
| Agent wall clock | 15–30 min |
| Max tool steps | 40–80 (tier-dependent) |
| Verify | 120s |
| Teardown | 60s |

### Observation space

Structured JSON for **tool-calling LLM agents** (not pixel, not classic numeric RL).

```python
class Observation(BaseModel):
    episode_id: str
    step: int
    task: TaskBrief
    budget: Budget  # steps_remaining, wall_time_remaining_s
    services: list[ServiceStatus]
    hints: list[str]  # curriculum only; off for hard eval
    last_tool_result: ToolResult | None
    recent_events: list[Event]
```

**TaskBrief** never includes hidden verifier details or private test names.  
Large artifacts fetched via tools only.

### Action space (tool API)

**MVP: exactly one tool call per `env.step`.**  
Harnesses that emit parallel multi-tool turns must **serialize** into sequential steps (shared state; each step gets updated `last_tool_result`). Optional batch actions are post-MVP.

```python
class Action(BaseModel):
    tool: str
    args: dict[str, Any]
```

#### ToolResult & error taxonomy (frozen before PR5)

```python
class ToolResult(BaseModel):
    ok: bool
    tool: str
    exit_code: int | None = None
    stdout: str = ""          # truncated
    stderr: str = ""          # truncated
    data: dict[str, Any] | None = None  # structured payloads (http status, json body snippet)
    error_code: str | None = None
    truncated: bool = False
    duration_ms: int

# error_code enum (normative):
# OK, TIMEOUT, PATH_JAIL, ARG_DENIED, BINARY_DENIED, NETWORK_DENIED,
# SERVICE_UNKNOWN, NOT_FOUND, DB_ERROR, INTERNAL, BUDGET_EXCEEDED
```

**Payload limits (Key Decision):**

| Field | Limit |
|-------|-------|
| `stdout` + `stderr` combined | **48 KiB** max returned (truncate with `truncated=true`) |
| `files.read` | **64 KiB** per call |
| `files.write` | **256 KiB** per call |
| `db.query` rows | **100** rows max |
| `logs.tail` | **2000** lines or 48 KiB |
| `shell.exec` wall time | **30s** default (task may raise to 60s) |

#### MVP tool surface

| Tool | MVP phase | Purpose | Constraints |
|------|-----------|---------|-------------|
| `files.read` / `write` / `list` | alpha | Edit workspace | Jail: `/workspace/**` only; **not** `/infra/**` |
| `http.request` | alpha | Call services | Internal compose DNS only; allowlist hostnames |
| `logs.tail` | alpha | Service logs | Via compose logs API; max lines/bytes |
| `services.restart` / `services.ps` | alpha | Lifecycle | Named services only; **no** arbitrary compose |
| `db.query` | alpha | Read-only SQL | Timeout; row limit |
| `db.exec` | alpha (restricted) | Writes when task allows | Audited; disabled on tasks that forbid; never drops verifier state |
| `shell.exec` | alpha | Allowlisted argv only | See allowlist table below |
| `tests.run` | alpha | Public pytest subset | Never hidden; results may inform agent but **not** mid-episode reward |
| `submit.done` | alpha | End → verify | Terminal |
| `metrics.query` | **post-alpha** | PromQL | Requires obs stack |
| `db.exec` unrestricted | never | — | Always policy-gated |

**Non-tools:** host Docker socket to agent, host networking, mid-episode image pull/build, editing compose/healthcheck infra.

#### Shell allowlist (MVP — deny by default)

`shell.exec` accepts **argv array only** (no `shell=True` string). Binary must be on allowlist; first path args restricted.

| Binary | Allowed | Notes |
|--------|---------|-------|
| `python` / `python3` | Yes | Only under `/workspace` scripts or `-m pytest` public |
| `pytest` | Yes | Public tests path only |
| `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `find` | Yes | Path args must stay in `/workspace` |
| `sed`, `awk` | Yes | Workspace paths only |
| `pip` / `pip install` | **No** | Reproducibility + supply chain |
| `docker`, `docker-compose`, `podman`, `kubectl` | **No** | Lifecycle via `services.*` only |
| `curl`, `wget` | **No** | Use `http.request` |
| `ssh`, `nc`, `nmap` | **No** | |
| `sudo`, `su`, `mount`, `chmod` on system paths | **No** | |
| `bash` / `sh` -c | **No** | Prevents string smuggling; use argv binaries |

L1 tasks may set `shell.exec` **disabled** when tools cover the path (`tools.allow: [files.*, http.*, ...]`).

### Reward function

**MVP contract (sparse):**

- **Per-step reward:** \(R_t = -c_{\text{step}}\) only (default \(c_{\text{step}}=0.001\)), plus immediate \(R_{\text{violation}}\) if a safety policy fires.  
- **No mid-episode partial credit from verifiers** (public or hidden).  
- **`tests.run` is observational** for the agent; does not change reward until terminal.  
- **Terminal reward** on `submit.done`, max-steps truncate (still run verify), or safety terminate:

\[
R_{\text{terminal}} = \mathbb{1}_{\text{success}} \cdot 1.0 + R_{\text{partial}} - R_{\text{cost accrued}} - R_{\text{violation accrued}}
\]

| Component | Definition |
|-----------|------------|
| Success | All `success_requires` pass and no `not_fail` fires |
| \(R_{\text{partial}}\) | Weighted public verifiers only (terminal) |
| Dense mode (optional flag) | Re-run **public** checks every K steps for shaping — **off by default**; never runs hidden |

**Default success_requires (family-aware):**

```yaml
# T2/T5 example — pytest.public is IN success_requires (not only partial)
success_requires:
  all_of:
    - health.all_healthy
    - http.golden_paths
    - pytest.public
    - invariants.db          # task-specific SQL package
    - invariants.family      # per-family hidden check
  not_fail:
    - process.no_cheat
    - security.auth_still_enforced
```

**T1/T3** may omit `pytest.public` from `all_of` only when behavioral golden paths + family invariants fully encode success; prefer including public tests when they exist.

**SLO:** `slo.latency_error_rate` is **partial credit only** in MVP-complete+; **not** a hard success gate in MVP-alpha (timing flaky).

### Termination

| Condition | `terminated` | `truncated` | Verify? |
|-----------|--------------|------------|---------|
| `submit.done` | yes | no | yes |
| Max steps | no | yes | yes (score what we can) |
| Wall clock | no | yes | yes |
| Sandbox crash | no | yes | best-effort |
| Critical safety violation | yes (fail) | no | yes (`not_fail`) |

---

## Procedural Task Generation & Anti-Contamination

### Phasing (honest)

| Phase | What exists |
|-------|-------------|
| **MVP-alpha** | Hand-authored YAML tasks + **parameterized mutators** + `episode_seed` → deterministic materialization |
| **MVP-complete** | More templates; `sample(split, tier, seed)` over fixed catalog |
| **v1** | Composition of 1–3 mutators with **YAML banlist** of incompatible pairs (not a general constraint solver) |
| **Long-term contamination defense** | **Sealed private holdouts** + canaries; public pack **will** contaminate over time |

### Pipeline

```mermaid
flowchart LR
  Catalog["Mutator Catalog"] --> Sampler["Seeded Sampler"]
  Templates["Task Templates YAML"] --> Sampler
  Sampler --> Materialize["Materialize workspace"]
  Materialize --> CodeMut["Code/config/data mutations"]
  Materialize --> PublicT["Public tests"]
  Materialize --> HiddenT["Hidden tests on verifier volume"]
```

### Components

1. **Base snapshot:** image digests + workspace template tree.  
2. **Mutator catalog:** `config.set`, `code.patch`, `postgres.corrupt_rows`, `redis.enqueue_poison`, etc.  
3. **MVP composition:** one primary mutator per task YAML (optionally one secondary). Incompatible pairs listed in `faults/banlist.yaml`.  
4. **Briefs:** templates + slot filling (no online LLM authoring).  
5. **Splits:** `public` / `private_dev` / `private_holdout` (holdout not in public repo).

### Seeded determinism

```text
episode_seed = hash(pack_id, task_id, user_seed, cascade_version)
```

**Same seed ⇒ same task materialization** (files, config, DB seed rows, injected patches).  

**Verification is not claimed 100% timing-deterministic.** Verifiers use retries, backoff, and steady-state windows. Success/fail labels target **≥99%** replay agreement (Linux) after flaky budget—not “100% across 10 replays” absolute.

---

## Verifier Design

### Principles

1. Primary verifiers define customer-visible success.  
2. Secondary/hidden catch reward hacking and unsafe fixes.  
3. Verifier code, hidden tests, compose files, and healthcheck scripts live on an **immutable plane** outside the agent path jail.  
4. Offline only (compose network).

### Immutable vs agent-writable mounts

| Path | Mounted in | Writable by agent? |
|------|------------|--------------------|
| `/workspace/app`, `/workspace/configs` (non-infra) | api, worker, gateway | Yes |
| `/workspace/tests/public` | gateway, verifier | Yes (but cheat-detect + hidden still catch) |
| `/infra/compose`, healthcheck scripts | compose engine / host only | **No** |
| `/verifier/hidden`, `/verifier/invariants` | verifier only | **No** |
| Image-defined HEALTHCHECK | engine | **No** (not in workspace) |

Compose file and healthchecks are **not** in `/workspace`. Agents cannot make health “always green” by editing compose. `process.no_cheat` still detects stubbing `/health` in app code via hidden probes that hit **business** routes and checksum app health handler against known-bad patterns where feasible.

### Primary verifiers (MVP-alpha)

| Verifier | Checks |
|----------|--------|
| `health.all_healthy` | Compose healthchecks green (engine-level) |
| `http.golden_paths` | Scripted API scenarios from verifier container |
| `pytest.public` | Public integration tests |
| `invariants.db` | Task-specific SQL (FKs, counts, forbidden truncations) |

### Secondary / hidden

| Verifier | Purpose |
|----------|---------|
| `invariants.family` | Per-family hidden check (required: ≥1 per task) |
| `pytest.hidden` | Edge cases not in public suite |
| `security.auth_still_enforced` | Mutating routes still require auth |
| `process.no_cheat` | Initial cheat catalog (below) |
| `regression.core` | Core paths for T5 feature tasks |

### Initial cheat catalog (acceptance tests in PR6)

| Hack ID | Attack | Expected |
|---------|--------|----------|
| C1 | Delete or empty public tests | `process.no_cheat` or hidden still fail; success false |
| C2 | Stub `/health` to always 200; business broken | golden_paths / family invariant fail |
| C3 | `DROP` or truncate `orders` to clear bad state | `invariants.db` fail |
| C4 | Disable auth middleware | `security.auth_still_enforced` fail |
| C5 | Worker infinite no-op success ack without fulfilling | golden_paths / family fail |
| C6 | Rewrite public tests to `assert True` | hidden + cheat fingerprint fail |
| C7 | Point code at empty in-memory fake DB | invariants / golden fail |

**MVP-alpha cheat-catch target:** 100% of C1–C7 on Linux CI. Broader red-team expansion is PR15 (not first introduction of defaults).

### Scoring example

```yaml
success_requires:
  all_of: [health.all_healthy, http.golden_paths, pytest.public, invariants.db, invariants.family]
  not_fail: [process.no_cheat, security.auth_still_enforced]
partial_credit:  # terminal only
  - { id: pytest.public, weight: 0.0 }  # already in all_of; weight unused if required
  - { id: slo.latency_error_rate, weight: 0.2 }  # MVP-complete+ only; not hard gate
```

### Reliability targets

- Materialization determinism: **100%** same seed → same files/DB seed.  
- Verifier label agreement under replay: **≥99%** Linux after ≤1 provision retry.  
- Flaky episode rate: **<1%** Linux CI; **<2%** Docker Desktop.  
- Do not publish leaderboard until empirical flaky rate measured.

---

## Environment Architecture (Runtime Detail)

### Sandbox isolation model

| Boundary | Implementation |
|----------|----------------|
| Per-episode project | `docker compose -p cascade_{episode_id}` |
| Labels | `com.cascade.episode_id`, `com.cascade.created_at`, `com.cascade.version` |
| Network | **Internal attachable network; egress denied**; **no host `ports:` in episode compose** |
| Service DNS | Fixed names: `api`, `postgres`, `redis`, `worker`, `tool-gateway` |
| Filesystem | Ephemeral workspace volume/dir; wiped on teardown |
| Privileges | `no-new-privileges`; no privileged; drop caps |
| Tool gateway | Container on compose network; **no Docker CLI** to agent; lifecycle via gateway→compose API **from host control plane** |
| Resource caps | mem/cpu per service; Desktop default `max_parallel_episodes=1` |

#### No host ports (normative — parallel safety)

Episode compose **MUST NOT** publish fixed host ports (`8000:8000`, `5432:5432`, etc.). All agent and verifier traffic uses **compose DNS** on the internal network.

- **Debug profile** (`docker-compose.debug.yml`): optional host ports; **single-episode only**; refuse start if another `cascade_*` project is active.  
- **Acceptance test:** two concurrent episodes; neither can reach the other’s network/volumes; both verify independently.

### Tool gateway design (locked MVP decisions)

| Decision | Choice |
|----------|--------|
| Transport | **HTTP** on compose network (`http://tool-gateway:8080`); control plane on host calls published-**internal** path via `docker compose exec` or join network—**not** host-network mode for gateway |
| Agent access to Docker | **None**. No socket mount into api/worker/workspace. Host control plane owns compose SDK/CLI |
| Lifecycle | Only `services.restart` / `services.ps` implemented by **host Episode Manager** (or gateway calling a tiny rootless helper)—never `docker` binary in `shell.exec` |
| Shell | Argv allowlist (table above) |
| Gateway network | Compose project network only |

Flow: `Env.step` → Episode Manager (host) → HTTP to gateway container **or** direct host-side tool implementations that `docker exec` into services. **Preferred MVP:** host-side tool adapters using Docker SDK (simpler on Desktop) *emulating* the same tool schema; gateway container optional until HTTP server multi-tenant. Schema remains identical.

**Pragmatic MVP split:**

1. **Slice 0 / early alpha:** tools executed from **host control plane** via Docker SDK (`exec`, `logs`)—same `ToolResult` schema.  
2. **Hardening:** move execution into `tool-gateway` container for clearer blast radius.

Either way, agent never sees Docker socket.

### Orphan recovery & GC (normative)

| Mechanism | Behavior |
|-----------|----------|
| Labels | Every resource labeled with episode id + created_at |
| `env.close()` | `try/finally` teardown; `atexit` + SIGINT/SIGTERM handlers call close |
| Best-effort | Document that kill -9 skips close |
| `cascade gc` | CLI: list/remove `com.cascade.*` projects older than TTL (default 2h) or all stale |
| Startup sweep | Optional on `gym.make`: warn/count orphans; refuse if disk < threshold |
| CI | Disk guard; fail job if leftover projects after tests |
| Trainers | **Must** run `cascade gc` periodically; document in quickstart |

### Runtime interface (future k8s)

```python
class RuntimeBackend(Protocol):
    def provision(self, episode: EpisodeSpec) -> EpisodeHandle: ...
    def exec(self, handle, req: ToolRequest) -> ToolResult: ...
    def teardown(self, handle) -> None: ...
```

MVP implements `ComposeRuntimeBackend` only. K8s later.

---

## Windows Support Matrix

| Configuration | Support |
|---------------|---------|
| Windows 10/11 + **Docker Desktop + WSL2 backend** | **Supported** for dev |
| Docker Desktop + Hyper-V legacy (no WSL2) | **Unsupported** |
| Native Linux + Docker Engine | **Supported** (CI + training) |
| macOS Docker Desktop | Best-effort (not primary) |

### Engineering constraints

| Topic | Guidance |
|-------|----------|
| Control plane | Prefer run from **WSL2 distro** or Linux CI; if native Windows Python, use Docker SDK and avoid bash-only scripts |
| Bind mounts | Prefer **named volumes** populated from image/`docker cp` for CI reliability; agent workspace may be volume or WSL-path bind |
| Paths | Normalize to POSIX inside containers; never pass `C:\...` into Linux containers |
| CRLF | `.gitattributes`: `* text=auto eol=lf` for `*.sh`, `*.yml`, Dockerfiles |
| File watch / reload | Less reliable on Desktop binds → **restart is the contract**, reload is optimization |
| I/O & OOM | Desktop default `max_parallel_episodes=1` (config `2` max recommended); document RAM ≥8GB for Shopstack |
| Images | Digest-pinned; `scripts/pull_images.sh` **before** first episode (PR4 companion, not late perf PR) |
| Quickstart time | **Cold** first run (pull+build) may exceed 15 min; **warm** <15 min is the metric |
| Docs | `docs/windows.md` known issues |

---

## Public Python Package Layout

```text
C:\Dev\grok-rl-env\
  pyproject.toml
  README.md
  LICENSE
  AGENTS.md
  .gitattributes
  src\cascade_env\
    __init__.py              # register_envs()
    version.py
    types.py                 # Observation, Action, ToolResult, error codes
    env.py
    episode.py
    registry.py
    config.py
    cli.py                   # cascade doctor | gc | pull
    runtime\
      base.py                # RuntimeBackend protocol
      compose.py
    docker\
      compose.py
      health.py
      resources.py
      gc.py
    tools\
      base.py
      files.py
      http.py
      db.py
      logs.py
      services.py
      shell.py
      submit.py
      tests_run.py
    tasks\
      loader.py
      generator.py
      mutators.py
      schemas.py
      task_schema.json
    verifiers\
      ...
    reward.py
    trajectory.py
    server\                  # post-MVP
    licensing\               # courtesy checks only; post-MVP
  scenarios\shopstack\
    docker-compose.yml       # NO host ports
    docker-compose.debug.yml # optional ports; single-episode
    docker-compose.slice0.yml
    services\api\...
    services\worker\...
    infra\                   # not mounted to agent
      healthcheck.sh
    tests\public\...
    tests\hidden\...
    faults\catalog.yaml
    faults\banlist.yaml
  packs\community\
  examples\
  tests\
  docs\
    quickstart.md
    windows.md
    security.md
    task_authoring.md
    commercial.md
  scripts\
    pull_images.sh
    smoke_episode.py
```

### Dependencies

Python **3.11+**; `gymnasium`, `pydantic`, `pydantic-settings`, `httpx`, `pyyaml`, `docker`, `fastapi`/`uvicorn` (post-MVP server), `structlog`, `pytest`, `tenacity`.  
System: Docker Engine + Compose v2.

### pyproject entry points (PR8)

```toml
[project.entry-points."gymnasium.envs"]
Cascade-v0 = "cascade_env.registry:register_cascade_v0"

[project.scripts]
cascade = "cascade_env.cli:main"
```

```python
# registry.py
def register_cascade_v0():
    from gymnasium.envs.registration import register
    register(id="Cascade-v0", entry_point="cascade_env.env:CascadeEnv")
```

---

## Training / Eval APIs

### Audience & spaces

**Cascade-v0 is a tool-calling agent environment.** It is **not** intended for classic continuous-control baselines.

| Space | MVP definition |
|-------|----------------|
| `observation_space` | `gymnasium.spaces.Text(max_length=…)` containing JSON serialization of `Observation` **or** `spaces.Dict` with Text fields—implementer picks Text-JSON for simplicity |
| `action_space` | `spaces.Text` JSON for `Action` **or** document that trainers use the typed Python API and ignore classic spaces |
| Info dict | Always includes parsed structures: `obs_dict`, `tool_result`, `episode_id` |

Numeric vectorized RL libraries that require `Box` actions are **out of scope**.

### Gymnasium usage

```python
import cascade_env
import gymnasium as gym

cascade_env.register_envs()
env = gym.make("Cascade-v0", pack="community", task_id=None, seed=42)
obs, info = env.reset(seed=42)
# obs is JSON str or dict depending on make kwargs; info["obs"] always structured
terminated = truncated = False
while not (terminated or truncated):
    action = {"tool": "logs.tail", "args": {"service": "api", "lines": 100}}
    obs, reward, terminated, truncated, info = env.step(action)
env.close()  # always
```

### Multi-tool harness adapter

```text
for tool_call in model_turn.tool_calls:  # parallel fan-out from LLM
    obs, r, term, trunc, info = env.step(to_action(tool_call))
    if term or trunc: break
# accumulate tool results into next chat messages (role=tool)
```

### Trajectory schema (tool/chat aligned)

```json
{
  "episode_id": "ep_...",
  "type": "step",
  "step": 3,
  "messages_delta": [
    {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "files.write", "arguments": "{...}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "{...ToolResult...}"}
  ],
  "action": {"tool": "files.write", "args": {"path": "...", "content_hash": "sha256:..."}},
  "reward": -0.001,
  "info": {"tool_latency_ms": 120}
}
```

### Batch / scale cost model

| Item | Estimate (Shopstack MVP-alpha) |
|------|--------------------------------|
| RAM / episode | **1.5–2.5 GB** (api+pg+redis+worker) |
| Disk / episode (volumes) | **0.5–1 GB** ephemeral + shared image layers |
| Image set (shared) | **~2–3 GB** digests |
| Parallel / 16-core 64GB Linux | **8–12** target with GC; Desktop **1–2** |
| Episodes / hour / node | Roughly `60 / (provision_min + agent_min)`; provision-dominated early (~1–2 min cold, <45s warm target) |
| Multi-node | **N machines × M local compose projects**; no shared cluster scheduler in MVP |

Overview claim: **designed for large-scale parallel episodes on Linux clusters**, not “thousands on one laptop.”

### HTTP rollout server

**Post-MVP (PR11).** Same step semantics; API key for hosted multi-tenant.

---

## Dataset / Task Pack Format

### Pack manifest

```yaml
api_version: cascade/v1
pack:
  id: community
  name: Cascade Community Pack
  version: 0.1.0
  min_runtime_version: "0.1.0"
  schema_version: 1
  license: Apache-2.0
  scenario: shopstack
  default_budgets:
    max_steps: 50
    max_wall_time_s: 1200
  splits:
    train: { filter: "tier in [L1, L2]" }
    test: { filter: "tier in [L1, L2, L3]" }
```

**Schema negotiation:** runtime supports `schema_version` N and N-1; refuse packs newer than runtime with clear error.

### Task instance (alpha example)

```yaml
api_version: cascade/v1
task:
  id: community.T1.worker_retry_storm.v1
  family: incident_repair
  tier: L2
  scenario: shopstack
  seed_policy: required
  tools:
    allow: [files.*, http.*, logs.*, services.*, db.query, shell.exec, tests.run, submit.done]
  brief:
    title: Elevated order latency and fulfillment failures
    description: |
      Customers report orders stuck in pending.
      Restore healthy fulfillment and pass golden path checks.
    public_success_criteria:
      - All services healthy
      - Golden path HTTP suite green
      - Public integration tests green
    constraints:
      - Do not drop the orders table
      - Do not disable authentication
  mutations:
    - type: config.set
      path: configs/worker.yaml
      key: max_retries
      value: 10000
    - type: code.patch
      file: app/worker/handler.py
      template: infinite_retry_no_jitter
  verifiers:
    success_requires:
      all_of: [health.all_healthy, http.golden_paths, pytest.public, invariants.db, invariants.family]
      not_fail: [process.no_cheat, security.auth_still_enforced]
  metadata:
    tags: [worker, retries, queue]
```

---

## Security Model

### Threat model

| Threat | Sev | Mitigation |
|--------|-----|------------|
| Container escape | Critical | no-privileged; no-new-privileges; no agent docker socket; CI checks |
| Network exfil | High | Egress deny; no host ports; internal DNS only |
| Cross-episode leak | High | Unique projects; no shared volumes; concurrent isolation test |
| Reward hacking | High | Immutable verifier plane; cheat catalog C1–C7; hidden invariants |
| Orphan disk fill | High | GC/reaper; CI disk guards |
| License bypass local | Medium | Expected for open-core; sealed packs for real enforcement |
| Prompt injection via logs | Medium | Untrusted tool outputs |
| Misuse on real prod | Medium | Docs/terms sandbox banner |

### Secure defaults (from first compose PR—not deferred)

1. No host `ports:` in episode compose  
2. Egress denied / internal network  
3. `security_opt: [no-new-privileges:true]`  
4. Hidden tests only on verifier mounts  
5. Shell deny-by-default allowlist  
6. Secrets ephemeral per episode  

### Ethics & misuse

- Appsec exploit packs: gated, not MVP.  
- Quickstart + license sketch: **sandbox only; never real prod credentials.**  
- Tasks may teach remediating bad security *config inside the sandbox*; not exploitation of third-party systems.

---

## Commercial Model Sketch

| Tier | Contents | Notes |
|------|----------|-------|
| **Community (Free)** | Runtime + Shopstack + public pack + docs | Apache-2.0 runtime |
| **Pro** | Larger catalog, support | Annual |
| **Lab / Enterprise** | Sealed holdouts, on-prem distribution, SLA for **hosted** scoring, custom CAUT porting | ACV varies; six-figure only with services + holdouts—not assumed from free package alone |
| **Services** | Port customer CAUT; joint eval reports | Explicit SKU |

### Enforcement honesty

| Layer | What it is |
|-------|------------|
| **Distribution** | Enterprise YAML/images **not in public repo**; sealed bundles; optional hosted scoring | **Real** control |
| **Courtesy client allowlist** | Warn/refuse known enterprise pack ids without key | **Not** a security boundary; bypassable |
| **Legal** | License terms for pack use | Contractual |

**Do not block MVP engineering on licensing.** Diagram “entitlement” = optional courtesy + hosted auth.

**v1 wedge:** sell **holdout eval + reliability**, not only unlimited training env seats.

---

## Observability & Operability

| Signal | Implementation |
|--------|----------------|
| Structured logs | JSON: episode_id, phase, latency, error_code |
| Metrics | counters/histograms for provision/step/verify |
| Failure artifacts | On provision/verify fail: write `trajectory_dir/failure/` with `compose ps`, `compose logs` (tail), health snapshot |
| Retention | Default keep last **20** failed episode artifact dirs; configurable |
| `cascade doctor` | docker version, compose version, disk free, WSL detection, image digests present, orphan count |
| `cascade gc` | Reap stale episodes |
| Alerting (hosted) | provision_fail rate, disk |

### Rollback

- Pin pack version + image digests  
- Runtime accepts pack `schema_version` N and N-1  
- Hosted kill switch for pack ids  

### Feature flags

```toml
[cascade]
enable_http_server = false
allow_network_egress = false
max_parallel_episodes = 1          # Desktop default; Linux trainers raise
pack_allowlist = ["community"]
license_key = ""                   # courtesy only
dense_public_shaping = false
```

---

## Delivery Phases & Effort

### Slice 0 — vertical reward proof (before full tools)

**Goal:** prove fault → verify → teardown without agent tool surface.

1. Compose Shopstack healthy (minimal routes).  
2. Host-side inject one fault (e.g. bad config file in volume).  
3. Host-side scripted patch (or leave broken) → run verifiers → JSONL.  
4. No Gym tools yet; `scripts/smoke_episode.py`.  

**Effort:** ~1–2 engineer-weeks.

### MVP-alpha (~6–8 engineer-weeks, 2 engineers)

- T1–T3 tasks, Gym loop, tools (no metrics), multi-verifier + C1–C7, trajectories, scripted + LLM stub, Linux CI smoke, Windows docs.  
- Shopstack minimal (Appendix A); no Prometheus mesh; no hard SLO gate.  

### MVP-complete (~+3–4 engineer-weeks)

- T4–T5; concurrent episode test; sampling API; optional partial SLO.  

### Explicitly deferred post-MVP

HTTP server, k8s, licensing UI, metrics.query, rich obs, vectorized env, T6–T15, enterprise packs.

---

## Success Metrics

| Metric | MVP-alpha | v1 Lab |
|--------|-----------|--------|
| SOTA pass rate (hard public) | 20–50% headroom | <70% on sealed L3+ |
| Materialization seed stability | 100% | 100% |
| Verifier replay agreement | ≥99% Linux | ≥99.5% |
| Flaky episode rate | <2% Desktop / <1% Linux | <0.5% |
| Provision P50/P95 warm | <45s / <90s | <20s / <40s |
| Parallel / 64GB Linux node | ≥4 measured; design for ≥8 | ≥32 with pooling |
| Cheat catalog C1–C7 catch | 100% | + expanded suite ≥95% |
| Time-to-first **warm** episode | <15 min | <10 min |

---

## Alternatives Considered

### Alt 1: Single-container “ops lite” / SWE-only

Reject as **core product**. Keep as **onboarding tier** micro-tasks inside Cascade later.

### Alt 2: Browser enterprise suite

Defer—flaky, crowded, heavy.

### Alt 3: Full Kubernetes + Chaos Mesh day one

Defer—ops burden; Windows poor.

### Alt 4: Appsec flagship

Reject as flagship—ethics/procurement.

### Alt 5: Holdout-eval-as-a-service only (thin wedge)

- **Pros:** Faster revenue story; less need for training-scale GC day one.  
- **Cons:** Still need reliable env to score holdouts; without open runtime, weak adoption.  
- **Adopt as GTM wedge**, not instead of building the env—**sell sealed scoring first**, open-source runtime + community pack for distribution.

### Alt 6: Research-quality thin harness around existing compose demos

- **Pros:** Fastest demo.  
- **Cons:** Not sellable packaging; no multi-verifier product; no holdout business.  
- **Reject** as company core; Slice 0 reuses the *idea* (thin harness) inside a productized repo.

### Why build CAUT in-repo vs customer apps day one

Customer production apps are non-portable, secret-laden, and non-reproducible for a shared benchmark market. In-repo Shopstack gives **identical holdouts**, clean licensing, and fast iteration. **Custom CAUT porting** is an enterprise services SKU once the runtime is proven.

---

## Risks and Mitigations

| Risk | Sev | Likelihood | Mitigation |
|------|-----|------------|------------|
| Edit→runtime propagation broken | Critical | Med if unspecified | Bind-mount + restart contract + acceptance tests |
| Orphan compose disk outage | High | Med at scale | GC, labels, CI guards, trainer docs |
| Reward hacking | High | Med | Immutable plane + C1–C7 + hidden family invariants |
| Docker Desktop flaky | Medium | High | Linux CI truth; windows.md; parallel=1 |
| Provision too slow for RL | High | Med | Digest pull early; warm caches; pools v1 |
| Shopstack too toy | Medium | Med | Realism bar (auth, idempotency, migrations, worker FSM) |
| Public pack contamination | Medium | High over time | Sealed holdouts primary defense |
| Scope creep k8s/obs | High | High | Slice/MVP phases; RuntimeBackend stub only |
| Trademark “Cascade” | Low–Med | Med | Package stable; rename-ready product string |
| Local license bypass | Low | Certain | Honesty: distribution enforcement only |

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Product thesis | Production multi-service incident & change env | Best sellability × oracle × headroom × buildability |
| Package name | `cascade_env` stable; product name rename-ready | Trademark uncertainty |
| Flagship CAUT | Shopstack minimal multi-service | One compose; rich faults |
| Code propagation | **Bind-mount + restart; no mid-episode rebuild**; api reload optional | Makes T2/T5 feasible on Desktop |
| MVP-alpha families | **T1–T3 only** | Weeks-scale realism |
| MVP-complete families | **T1–T5** | Full taxonomy |
| Slice 0 | Inject→verify without tools first | De-risk reward before gateway |
| Gym spaces | Tool-calling / Text-JSON; not Box RL | Dual-audience honesty |
| Step reward | **Cost only until terminal verify** | Clear sparse contract |
| Success gates | health + golden + **pytest.public** + task DB + family hidden | Stop shallow stubs |
| SLO | Partial only; not hard gate in alpha | Reduce flaky success |
| Gateway | HTTP schema; host-SDK tools OK early; **no agent Docker CLI** | Security + Desktop pragmatism |
| Shell | Argv **allowlist deny-default** | SRE power vs escape |
| Host ports | **Forbidden** in episode compose | Parallel isolation |
| Security defaults | In **first compose/lifecycle PRs** | Not PR15 |
| PR15 role | Expanded red-team only | Defaults already present |
| Verifier plane | Immutable; outside `/workspace` jail | Anti-hack |
| Procedural gen | Parameterized templates MVP; banlist composition v1 | Honest phasing |
| Contamination | Holdouts real defense | Public will leak |
| Runtime abstraction | `RuntimeBackend` protocol; Compose only MVP | Future k8s |
| GC | Labels + `cascade gc` + atexit | Scale operability |
| Commercial enforcement | Distribution + legal; client check courtesy | Open-core reality |
| v1 sales wedge | Holdout eval reliability first | Procurement realism |
| Tool payload | 48 KiB tool I/O cap | Context + DoS |
| Multi-tool | Serialize to sequential steps | Harness compatibility |
| Obs/metrics mesh | **Deferred** post-alpha | Cut scope |
| Effort | 2 eng × ~6–8 w alpha | Not mythical “weeks” alone |
| Primary CI | Linux; Windows matrix documented | Training on Linux |

---

## Open Questions (user / business)

1. **Legal entity & pack license form** for enterprise sealed packs.  
2. **Pricing & beachhead design partner.**  
3. **Trademark** on “Cascade” vs alternate marketing name (package can stay `cascade_env`).  
4. **Hosted scoring vs pure on-prem** first revenue.  
5. **Public leaderboard** free tier—yes/no cost appetite.  

Technical forks above are **closed** for implementation.

---

## References

- Gymnasium: https://gymnasium.farama.org/  
- SWE-bench, WebArena, OSWorld, InterCode, The Agent Company, AppWorld  
- Docker Compose specification  
- Chaos Mesh / Litmus (infra prior art)  

---

## Appendix A — Shopstack implementer spec (MVP-alpha)

### A.1 ERD (minimal)

```text
users(id PK, api_key_hash, name)
products(id PK, sku UNIQUE, name, price_cents, stock)
orders(id PK, user_id FK, status, idempotency_key UNIQUE, total_cents, created_at)
order_items(id PK, order_id FK, product_id FK, qty, unit_price_cents)
fulfillment_events(id PK, order_id FK, event_type, payload_json, created_at)
```

**Order status FSM:** `pending → paid → fulfilling → fulfilled | failed`  
(Worker drives `fulfilling → fulfilled/failed`; API creates `pending/paid`.)

### A.2 API routes (freeze DNS `api:8000` internal)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | No | Liveness (not sole success signal) |
| GET | `/ready` | No | DB+redis ready |
| GET | `/v1/products` | Optional | List catalog |
| GET | `/v1/products/{id}` | Optional | Get product |
| POST | `/v1/orders` | **Yes** | Create order (`Idempotency-Key` required) |
| GET | `/v1/orders/{id}` | **Yes** | Get order + status |
| POST | `/v1/orders/{id}/cancel` | **Yes** | Cancel if not fulfilled |
| GET | `/v1/admin/metrics_stub` | **Yes** | Counters JSON (no Prometheus required) |

**Payments-ish stub:** create order marks `paid` immediately if stock available; no external PSP. Stock decrement transactional.

### A.3 Golden-path sequence (verifier)

1. `GET /ready` → 200  
2. `GET /v1/products` → ≥1 product  
3. `POST /v1/orders` with auth + idempotency key → 201, status `paid` or `fulfilling`  
4. Poll `GET /v1/orders/{id}` until `fulfilled` (timeout 30s)  
5. Repeat idempotent POST same key → same order id  
6. Unauth POST → 401  

### A.4 Worker state machine

```text
loop:
  job = BRPOP orders:queue
  mark order fulfilling
  try: decrement already done at API; write fulfillment_events; mark fulfilled
  except: mark failed; optional retry with jitter (config max_retries)
  # poison: bad payload → dead-letter list after max_retries
```

Queue protocol: **Redis lists** (`orders:queue`, `orders:dead`).

### A.5 Verifier load recipe (when SLO partial enabled later)

From verifier container: `httpx` loop **N=50** sequential requests to golden path; compute error rate; **no k6 in alpha**. Not a hard gate in alpha.

### A.6 Compose sketch (normative properties)

```yaml
# scenarios/shopstack/docker-compose.yml — sketch, not final
name: shopstack  # overridden by -p cascade_{episode_id}
services:
  api:
    image: cascade/shopstack-api@sha256:DIGEST
    networks: [cascade_net]
    volumes: ["workspace_data:/workspace"]
    environment:
      DATABASE_URL: postgresql://shop:shop@postgres:5432/shop
      REDIS_URL: redis://redis:6379/0
    depends_on: { postgres: { condition: service_healthy }, redis: { condition: service_healthy } }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 10
    security_opt: ["no-new-privileges:true"]
    # NO ports: mapping
  worker:
    image: cascade/shopstack-worker@sha256:DIGEST
    networks: [cascade_net]
    volumes: ["workspace_data:/workspace"]
    # ... same DB/redis env; healthcheck: process or redis ping script
  postgres:
    image: postgres:16-alpine@sha256:DIGEST
    networks: [cascade_net]
    # NO ports
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U shop"], interval: 5s, retries: 10 }
  redis:
    image: redis:7-alpine@sha256:DIGEST
    networks: [cascade_net]
    healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 5s, retries: 10 }

networks:
  cascade_net:
    internal: true   # egress deny

volumes:
  workspace_data:
```

Debug compose may add ports; episode runner rejects debug profile when `max_parallel_episodes > 1` or existing projects present.

---

## Appendix B — Chat/tool message adapter

Map Cascade steps to OpenAI-style tool loops: each `env.step` ↔ one `tool_call`; `ToolResult` JSON → `role=tool` content; episode_end → final user/system score message in trajectory sidecar.

---

## PR Plan

Incremental merge order for `C:\Dev\grok-rl-env`. **MVP-alpha = PR1–PR10.** **Post-MVP = PR11+.**

### PR1 — Repository skeleton & packaging

- **Title:** `chore: initialize cascade_env package skeleton`  
- **Files:** `pyproject.toml`, `README.md`, `LICENSE`, `AGENTS.md`, `.gitattributes`, `src/cascade_env/*` stubs, `tests/test_import.py`  
- **Deps:** none  
- **Description:** `uv sync --extra dev`; sandbox safety banner in README; Docker Desktop+WSL2 prerequisite.

### PR2 — Core types, ToolResult freeze, task schema

- **Title:** `feat: Pydantic models, ToolResult/error codes, task pack schema`  
- **Files:** `types.py`, `tasks/*`, `task_schema.json`, example YAML, unit tests  
- **Deps:** PR1  
- **Description:** Freeze ToolResult, error taxonomy, payload limits; validate packs.

### PR3a — Shopstack images & healthy compose (no host ports)

- **Title:** `feat(shopstack): api/worker Dockerfiles + internal-only compose`  
- **Files:** `scenarios/shopstack/services/**`, `docker-compose.yml`, infra healthchecks, digest pins  
- **Deps:** PR1  
- **Description:** Network `internal: true`; security_opt; bind/volume workspace; **no ports**; realism bar routes skeleton; `scripts/pull_images.sh` companion.

### PR3b — Seed data + public tests + golden path script

- **Title:** `feat(shopstack): SQL seed, public pytest, golden path runner`  
- **Files:** seed SQL, `tests/public`, verifier scripts  
- **Deps:** PR3a  
- **Description:** Golden path passes on clean stack.

### PR3c — Hidden tests volume layout + family invariant stubs

- **Title:** `feat(shopstack): hidden verifier mounts and invariant SQL`  
- **Files:** `tests/hidden`, mount docs  
- **Deps:** PR3b  
- **Description:** Hidden not visible in agent jail layout.

### PR4 — Episode lifecycle + labels + teardown

- **Title:** `feat: compose lifecycle provision/health/teardown`  
- **Files:** `runtime/compose.py`, `docker/*`, `episode.py` (no tools), smoke script  
- **Deps:** PR3a–c  
- **Description:** Unique `-p`; labels; finally teardown; Desktop timeouts.

### PR4b — Image pull digests & doctor image checks

- **Title:** `chore: pin digests and cascade pull/doctor image probes`  
- **Files:** `scripts/pull_images.sh`, `cli.py` doctor subset, pin file  
- **Deps:** PR3a, PR4  
- **Description:** Warm cache path; fail fast missing images.

### PR4c — GC / reaper / orphan sweep

- **Title:** `feat: cascade gc and stale episode reaper`  
- **Files:** `docker/gc.py`, `cli.py`, atexit hooks  
- **Deps:** PR4  
- **Description:** TTL reap; CI leftover detection.

### PR4d — Slice 0 smoke (inject → verify → JSONL, no agent tools)

- **Title:** `feat: slice0 host-side inject/verify smoke episode`  
- **Files:** `scripts/smoke_episode.py`, `docker-compose.slice0.yml` if needed, trajectory writer MVP  
- **Deps:** PR4, PR3b, early verifier module or shell script  
- **Description:** Vertical reward proof before tool API.

### PR5 — Tool adapters (host SDK) + allowlists

- **Title:** `feat: agent tools files/http/logs/services/db/shell/tests/submit`  
- **Files:** `tools/**`, path jail tests, allowlist tables  
- **Deps:** PR4, PR2  
- **Description:** Same ToolResult schema; restart propagation acceptance test; no docker binary.

### PR6 — Verifiers, reward sparse contract, cheat catalog C1–C7

- **Title:** `feat: multi-verifier orchestrator, terminal reward, cheat tests`  
- **Files:** `verifiers/**`, `reward.py`, `tests/test_cheat_catalog.py`  
- **Deps:** PR4d, PR2, PR3c  
- **Description:** success_requires includes pytest.public; step reward cost-only; C1–C7 green on Linux.

### PR7 — Mutators + community tasks T1–T3

- **Title:** `feat: mutators and community tasks T1–T3`  
- **Files:** `tasks/mutators.py`, packs tasks, inject in episode  
- **Deps:** PR5, PR6  
- **Description:** Three families; code-edit→restart→HTTP acceptance for T2.

### PR8 — Gymnasium Cascade-v0 + trajectories + registration

- **Title:** `feat: Cascade-v0 env, spaces contract, JSONL trajectories`  
- **Files:** `env.py`, `registry.py`, `trajectory.py`, entry points, smoke test  
- **Deps:** PR5–PR7  
- **Description:** Text/JSON spaces; multi-tool serialize docs; `close()` GC-safe.

### PR9 — Example agents

- **Title:** `feat(examples): scripted baseline + LLM tool stub`  
- **Files:** `examples/*`  
- **Deps:** PR8  
- **Description:** Scripted solves T1; stub shows tool schema.

### PR10 — CI Linux + docs (quickstart, windows, security)

- **Title:** `ci: linux docker smoke + operability docs`  
- **Files:** workflows, `docs/quickstart.md`, `windows.md`, `security.md`, concurrent episode test if stable  
- **Deps:** PR8  
- **Description:** Unit always; docker smoke Linux; flaky budget; sandbox banner.

### PR11 — HTTP rollout server (**post-MVP**)

- **Title:** `feat(server): FastAPI rollout API`  
- **Deps:** PR8  
- **Description:** Remote trainers; feature-flagged.

### PR12 — Concurrency guards & provision metrics (**post-MVP / late alpha ok**)

- **Title:** `perf: max_parallel enforcement and provision histograms`  
- **Deps:** PR4, PR8  
- **Description:** Desktop default 1; Linux raise carefully.

### PR13 — T4–T5 + sampling (**MVP-complete**)

- **Title:** `feat(packs): T4–T5 tasks and seeded sampling API`  
- **Deps:** PR7, PR8  
- **Description:** Completes five families; task-specific DB invariants for T4.

### PR14 — Courtesy pack allowlist + commercial docs (**post-MVP**)

- **Title:** `feat: pack allowlist courtesy checks + commercial.md`  
- **Deps:** PR2  
- **Description:** Document non-security; sealed distribution process.

### PR15 — Expanded red-team cheat suite (**post-MVP**)

- **Title:** `security: expanded cheat-detect beyond C1–C7`  
- **Deps:** PR6  
- **Description:** Defaults already shipped; this expands coverage only.

### PR16 — Windows path harness notes + optional WSL CI job (**alpha-hardening**)

- **Title:** `docs/ci: windows support matrix verification checklist`  
- **Deps:** PR10  
- **Description:** Manual Desktop checklist; optional CI.

---

*End of design document (rev 2).*
