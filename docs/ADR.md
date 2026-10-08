# Architecture Decision Records: Terraform Landing Zone Agent

This file records the decisions behind [DESIGN.md](DESIGN.md), the context that led to each one, and a log of reviews. Add new decisions at the end; never rewrite an accepted one. To change a decision, add a new ADR that supersedes it and update the old one's status.

Statuses: **Proposed** (in the design, awaiting reviewer sign-off) · **Accepted** · **Superseded by ADR-NNN** · **Rejected**.

## Index

| ADR | Title | Status | Date |
| --- | --- | --- | --- |
| [001](#adr-001-compose-vetted-baselines-never-freeform-hcl-never-apply) | Compose vetted baselines; never freeform HCL, never apply | Accepted | 2026-10-07 |
| [002](#adr-002-domain-knowledge-ships-as-a-portable-agent-skill-deterministic-work-lives-in-lzctl) | Domain knowledge ships as a portable Agent Skill; deterministic work lives in `lzctl` | Accepted | 2026-10-07 |
| [003](#adr-003-host-the-agent-on-cloud-run-not-agent-runtime) | Host the agent on Cloud Run, not Agent Runtime | Accepted | 2026-10-07 |
| [004](#adr-004-cloud-agnostic-spec-core-with-per-cloud-extensions) | Cloud-agnostic spec core with per-cloud extensions | Accepted | 2026-10-07 |
| [005](#adr-005-firestore-is-the-only-session-store) | Firestore is the only session store | Accepted | 2026-10-07 |
| [006](#adr-006-adk-20-graph-workflow-instead-of-an-llm-routed-orchestrator) | ADK 2.0 graph workflow instead of an LLM-routed orchestrator | Proposed | 2026-10-07 |
| [007](#adr-007-gcp-output-is-fabric-fast-yaml-datasets-profiles-map-to-fast-datasets) | GCP output is Fabric FAST YAML datasets; profiles map to FAST datasets | Proposed | 2026-10-07 |
| [008](#adr-008-validator-runs-with-no-network-egress) | Validator runs with no network egress | Proposed | 2026-10-07 |
| [009](#adr-009-iap-directly-on-cloud-run-no-load-balancer) | IAP directly on Cloud Run, no load balancer | Proposed | 2026-10-07 |
| [010](#adr-010-canonical-skill-location-is-agentsskills) | Canonical skill location is `.agents/skills/` | Proposed | 2026-10-07 |
| [011](#adr-011-terraform-mcp-server-is-a-development-aid-not-part-of-rendering) | Terraform MCP server is a development aid, not part of rendering | Proposed | 2026-10-07 |
| [012](#adr-012-tag-every-resource-this-repo-creates) | Tag every resource this repo creates | Accepted | 2026-10-07 |

---

## ADR-001: Compose vetted baselines; never freeform HCL, never apply

**Status:** Accepted · 2026-10-07

**Context.** LLMs are good at intake and mapping intent to options, but freeform HCL is non-deterministic, hard to review and fails change audit. Running plan or apply would put org-level credentials inside an LLM-driven system.

**Decision.** The agent fills configuration data for one pinned vendor baseline per cloud (our own module set for OpenStack). Its reach ends at a pull request; apply happens only in the existing human-approved pipeline.

**Consequences.** Reviewers diff configuration, not code. The agent cannot express anything the baseline can't, and validate-only output can still fail at plan or apply (top risk in DESIGN.md; sandbox plan in P3).

## ADR-002: Domain knowledge ships as a portable Agent Skill; deterministic work lives in `lzctl`

**Status:** Accepted · 2026-10-07

**Context.** The same knowledge must run in several local hosts and the hosted agent. Host models differ, so anything left to model reasoning will drift between hosts. The Agent Skills (`SKILL.md`) format is an open standard (agentskills.io, published December 2025) with roughly 40 adopting clients by late 2026.

**Decision.** Package catalog, naming standards, schemas, templates and policies as one skill. Put validation, rendering, checking and finding-to-field mapping in the bundled `lzctl` CLI. The hosted agent is one more host calling the same `lzctl`.

**Consequences.** Byte-identical output across hosts for the same spec. Evals must run per host x model, because intake quality still differs. Requirements text reaches each local host's model provider, so hosts need data-governance approval.

## ADR-003: Host the agent on Cloud Run, not Agent Runtime

**Status:** Accepted · 2026-10-07 · Revisit at G2

**Context.** Agent Runtime (formerly Agent Engine, now part of Gemini Enterprise Agent Platform) provides managed sessions and Agent Identity, but offers less control over networking and container contents, and ties the endpoint to Agent Platform. The validator must be isolated from the agent's identity and network.

**Decision.** Run the ADK app as a Cloud Run service and the validator as a separate Cloud Run Job.

**Consequences.** We own session storage (ADR-005) and identity wiring. Revisit if Agent Runtime gains equivalent network isolation, or if Gemini Enterprise becomes the main interface (open question in DESIGN.md).

## ADR-004: Cloud-agnostic spec core with per-cloud extensions

**Status:** Accepted · 2026-10-07

**Context.** The draft claimed core spec fields were cloud-agnostic, but its example used GCP-only fields (`private_service_connect`, `vpc_sc`, `audit_sink: bigquery | gcs`, `org_policy_profile`) and had no `extensions` block.

**Decision.** Core fields use neutral names (`private_service_access`, `service_perimeter`, `customer_managed_keys`, `audit_destination`). Cloud-only settings go under `extensions.<cloud>`, and only the block matching `target.cloud` is allowed. The guardrail set follows from `target.profile`, so there is no separate `org_policy_profile` field.

**Consequences.** One spec schema core, plus one extension schema per cloud. Capabilities a cloud lacks are rejected at spec validation.

## ADR-005: Firestore is the only session store

**Status:** Accepted · 2026-10-07

**Context.** The draft said "Firestore (or Cloud SQL)" in Agent design but listed only Firestore in the infrastructure table. ADK on Cloud Run needs an explicit session service; the default is in-memory. Agent Platform Sessions is another option, but it ties state to Agent Platform (see ADR-003).

**Decision.** Use the ADK session service backed by Firestore (native mode), with CMEK.

**Consequences.** ADK 2.0 changed the session schema; sessions written by 2.0 are readable by ADK 1.28+, but older 1.x versions can't read them. Pin ADK 2.x and do not share the store with 1.x agents.

## ADR-006: ADK 2.0 graph workflow instead of an LLM-routed orchestrator

**Status:** Proposed · 2026-10-07

**Context.** The draft used a root LLM orchestrator routing to Intake, Composer and Reviewer sub-agents, so the retry limit and the "validate and confirm before PR" rule lived in prompts. ADK 2.0 (Python GA May 19, 2026; Go GA June 30, 2026) adds a graph-based Workflow Runtime with deterministic routing, loops, retries and native human-in-the-loop checkpoints.

**Decision.** Model the agent as a workflow: Intake (LLM) → Render (deterministic) → Validate (deterministic) → Review (LLM, loop edge capped at 3) → Approve (human) → Publish (deterministic). The Composer's work becomes the deterministic Render node.

**Consequences.** Guardrails are enforced in code, which strengthens the prompt-injection story. Only two nodes call a model, so costs map cleanly to steps. Requires ADK 2.x and its migration guide.

## ADR-007: GCP output is Fabric FAST YAML datasets; profiles map to FAST datasets

**Status:** Proposed · 2026-10-07 · Depends on the open "GCP baseline" question

**Context.** The draft assumed the agent renders tfvars. Current Fabric FAST (v59.0.0, Sept 2026) is factory-driven: `0-org-setup`, `2-networking` and `2-project-factory` take YAML datasets, tfvars mostly point `factories_config` at them, and FAST ships JSON schemas for every factory file. `0-org-setup` provides `classic` and `hardened` datasets (`minimal` and `tenants` are TBD), and `2-networking` provides hub-and-spoke designs over peering (default), NCC, NVA or HA VPN.

**Decision.** For GCP, render FAST YAML datasets plus small tfvars. Map profiles: Starter → trimmed `classic`; Standard → `classic`; Regulated → `hardened` plus `1-vpcsc` and `2-security`. Map `extensions.gcp.hub_connectivity` to the networking dataset. Derive the spec schema from FAST's factory schemas and validate rendered output against them.

**Consequences.** Much less templating than tfvars for every module, and an upstream schema catches template bugs. FAST majors carry breaking changes (v53 changed `factories_config`; v59 renamed modules), so baseline bumps need a skill release and a full eval run. The `hardened` dataset's detective controls require SCC Premium or Enterprise.

## ADR-008: Validator runs with no network egress

**Status:** Proposed · 2026-10-07

**Context.** The draft limited validator egress to "the Terraform registry mirror" in the threat model, but listed Cloud NAT only as optional hardening, so the control had no implementation. `terraform init` can install providers from a local filesystem mirror.

**Decision.** Bake pinned providers (filesystem mirror) and vendored modules into the validator image. Run the job with Direct VPC egress into a subnet whose firewall denies all egress.

**Consequences.** Closes the exfiltration path and removes Cloud NAT cost. Every provider or module bump needs a validator image rebuild, which already happens through the release pipeline.

## ADR-009: IAP directly on Cloud Run, no load balancer

**Status:** Proposed · 2026-10-07

**Context.** Direct IAP on Cloud Run went GA on March 13, 2026, with no added charge. The draft budgeted an HTTPS load balancer for IAP as hardening.

**Decision.** Enable IAP on the Cloud Run service itself, with internal ingress.

**Consequences.** Removes the $25–60/month hardening line. If we later run multi-region behind one global load balancer, IAP must move to the load balancer, because the two can't be combined.

## ADR-010: Canonical skill location is `.agents/skills/`

**Status:** Proposed · 2026-10-07

**Context.** The draft's repository layout used `skills/`, while its portability rules said `.agents/skills/`. Codex's current docs read `.agents/skills/` (repo) and `~/.agents/skills/` (user); `~/.codex/skills/` is superseded. Gemini CLI reads `.gemini/skills/` and accepts `~/.agents/skills/` as an alias.

**Decision.** Keep the canonical copy at `.agents/skills/landing-zone/`, and symlink `.gemini/skills/landing-zone` to it.

**Consequences.** One source of truth. Windows checkouts need symlink support (`core.symlinks=true`), or a sync step in CI.

## ADR-011: Terraform MCP server is a development aid, not part of rendering

**Status:** Proposed · 2026-10-07

**Context.** HashiCorp's Terraform MCP server went GA on June 11, 2026. It gives agents version-accurate provider and module docs, and can wire registry modules into root modules.

**Decision.** Allow it in local hosts for skill authors and for explaining findings. Keep it out of the render path and the hosted agent.

**Consequences.** Rendering stays deterministic. Wiring modules through MCP is recorded as a rejected alternative in DESIGN.md.

## ADR-012: Tag every resource this repo creates

**Status:** Accepted · 2026-10-07 · Requested by the project owner

**Context.** Project `skills-mjl-27850` ("Skills", under org `mikejloria-org`) hosts more than one skill, so this repo's resources need to be identifiable for cost and ownership. The tag key `name` (`tagKeys/281478640749113`) and value `Terraform-Landing-Zone-Template-Skill` (`tagValues/281477778372023`) already exist, and the value is already bound to the project itself (checked with gcloud on 2026-10-07).

**Decision.** Bind `skills-mjl-27850/name/Terraform-Landing-Zone-Template-Skill` explicitly on every resource this repository creates, not just through inheritance from the project. Enforce it with a conftest rule on the `infra/` plan. Details and a Terraform example are in DESIGN.md under Resource tagging.

**Consequences.**
- The key is parented by the project, so it can only be bound to resources in `skills-mjl-27850`. Resources in other projects or orgs (P3 sandboxes) need their own tag key.
- Terraform needs explicit binding resources for most services, which adds one resource per tagged resource.
- The deploying identity (`lz-ci-sa`) needs `roles/resourcemanager.tagUser` on the tag value and on the resources it binds to.
- The tag does not apply to landing zones the agent generates for users.

---

## Review log

### 2026-10-07: First review and verification of DESIGN.md

**Issues found and fixed**

| # | Issue | Fix |
| --- | --- | --- |
| 1 | Spec example was GCP-specific despite claiming cloud-agnostic core fields; no `extensions` block | ADR-004 |
| 2 | Leftover "spec gains a `target` block" sentence after `target` was already in the spec | Removed; replaced with the extensions rule |
| 3 | Broken markdown in the Grok Build skill-path cell | Rewritten |
| 4 | `[embedded content: …]` placeholders for the architecture diagram and roadmap | Replaced with a Mermaid diagram and a phase/gate table |
| 5 | Session store "Firestore (or Cloud SQL)" vs Firestore only | ADR-005 |
| 6 | CMEK required but no Cloud KMS in the infrastructure table | Added a Keys row |
| 7 | Validator egress control had no implementation (Cloud NAT optional) | ADR-008 |
| 8 | Repository layout `skills/` vs portability rule `.agents/skills/` | ADR-010 |
| 9 | Codex skill path `~/.codex/skills/` is outdated | Updated to `.agents/skills/` |
| 10 | Gemini CLI, Google's own host, was missing from supported hosts | Added; host count 3 → 4 |
| 11 | Grok Build's skill-folder support stated as fact; only third-party reports support it | Marked unverified, with how to check |
| 12 | Hardening cost line assumed a load balancer for IAP | ADR-009; line removed |
| 13 | Gemini 3.1 Pro preview status and the >200K-token price tier not mentioned | Added to cost assumptions and risks |
| 14 | P3 sandbox orgs not costed | Flagged in Cost estimate and Open questions |
| 15 | Weak sources (skill marketplaces, a single-author blog) for key claims | Replaced with vendor docs where available |

**Verified claims**

| Claim in the draft | Result | Source |
| --- | --- | --- |
| Azure `caf-enterprise-scale` archived August 1, 2026; use AVM | Confirmed | [GitHub](https://github.com/Azure/terraform-azurerm-caf-enterprise-scale) |
| Vertex AI rebranded to Gemini Enterprise Agent Platform; Agent Engine now Agent Runtime | Confirmed | [Google Cloud blog](https://cloud.google.com/blog/products/ai-machine-learning/introducing-gemini-enterprise-agent-platform) |
| Gemini 3 Flash $0.50/$3; Gemini 3.1 Pro $2/$12, $0.20 cached input | Confirmed by third-party trackers; 3.1 Pro is still preview | [LLM Reference](https://www.llmreference.com/model/gemini-3.1-pro-preview/gcp-vertex-ai) |
| Grok Build in beta since May 2026 | Confirmed (May 25, 2026) | [xAI](https://x.ai/news/grok-build-cli) |
| No official DeepSeek coding harness | Confirmed as of the latest sources (harness team hiring in May 2026) | [Verdent](https://www.verdent.ai/guides/deepseek-coding-plan-2026) |
| AWS Landing Zone Accelerator is CDK-based, not Terraform | Confirmed | [AWS docs](https://docs.aws.amazon.com/controltower/latest/userguide/about-lza.html) |
| Cost arithmetic (per run, monthly, eval suite, build, maintenance) | All figures recomputed and consistent | DESIGN.md |

**Not yet verified (check before budgeting or P1)**

- Model Armor pricing at our volume.
- Cloud Run idle min-instance rate (about $19/month) against the official pricing page.
- Whether Gemini 3.5 Flash is GA in our region (third-party sources list it at $1.50/$9 per 1M tokens); Gemini 3.5 Pro was unreleased as of early October 2026.
- Whether Agent Identity (SPIFFE-based) can be used by a Cloud Run-hosted agent, or only by Agent Runtime.
- Grok Build's project skill folder: run `grok inspect` in this repo to confirm it finds the skill.
- Roadmap phases and gates were reconstructed from the draft's text, because the original embedded roadmap was not in the file. The engineer-week totals match the cost table; confirm the phase boundaries with the author.
