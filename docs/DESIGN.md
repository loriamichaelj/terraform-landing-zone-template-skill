# Design Doc: Terraform Landing Zone Agent (ADK on Cloud Run)

Oct 7, 2026 · Author: M.L.

## Overview

We will build a portable Agent Skill, plus a hosted ADK agent on Cloud Run, that turns landing zone requirements into a validated Terraform landing zone for GCP, Azure, AWS or OpenStack, delivered as a GitHub pull request. The agent composes vetted modules and fills in their variables; it never writes freeform HCL and never runs `terraform apply`.

Domain knowledge (module catalog, naming standards, policy rules) ships as a portable Agent Skill (`SKILL.md` package), versioned separately from the agent runtime. The same skill runs in Codex, Grok Build and DeepSeek-backed hosts, as well as in the hosted agent.

| Field | Value |
| --- | --- |
| Status | Draft |
| Author | M.L. |
| Reviewers | Platform engineering, Cloud security, SRE (names TBD) |
| Target platform | Hosted agent on Google Cloud (Cloud Run, Gemini Enterprise Agent Platform); skill also runs locally in Codex, Grok Build and DeepSeek-backed hosts |
| MVP scope | GCP first, then Azure, AWS and OpenStack; Starter, Standard and Regulated profiles; PR output, validate-only (no plan, no apply) |

## Background and problem statement

Standing up a compliant GCP landing zone takes weeks of senior platform time, and most of it is translating requirements into module configuration. The reference foundations (Cloud Foundation Fabric FAST, `terraform-example-foundation`) are solid, but they expose hundreds of variables across stages, and teams misconfigure them in predictable ways.

The pain points this project targets:

- **Slow intake.** Requirements arrive as meeting notes and spreadsheets, not as a structured spec.
- **Inconsistent output.** Each engineer configures the foundation differently: naming, CIDR plans, log sinks, org policies.
- **Late feedback.** Policy and security violations surface in review or at apply time, after hours of work.
- **No audit trail** of why a configuration choice was made.

LLMs are good at intake and mapping intent to options, and bad at producing reviewable infrastructure code from scratch. The design leans on the first and guards against the second.

## Goals and non-goals

The MVP succeeds when a platform engineer can go from a requirements conversation to a review-ready landing zone PR in under one hour, with zero critical policy violations.

**Goals**

1. Convert conversational requirements into a schema-validated landing zone spec (JSON).
2. Render that spec into tfvars and stage configuration for one pinned baseline per target cloud: GCP, Azure, AWS or OpenStack.
3. Validate every output with static checks and policy-as-code before a human sees it.
4. Deliver a PR containing the config, a README, a validation report and a decision log.
5. Ship the domain knowledge as a reusable Agent Skill, versioned independently of the agent, that runs in Codex, Grok Build and DeepSeek-backed hosts.
6. Run the agent itself on infrastructure that meets the same standards it generates.

**Non-goals (MVP)**

- Running `terraform apply`, or holding any org-level write credentials.
- Running `terraform plan` against a real organization (phase 3, sandbox org only).
- Freeform HCL authoring or new module development.
- Mixing clouds in one run: one spec targets one cloud; a multi-cloud estate is several specs.
- Day-2 operations: drift detection, upgrades, or tenant onboarding.

## Requirements

Functional requirements define what the agent produces; non-functional requirements are the bar it must clear before any team relies on it.

**Functional**

| ID | Requirement |
| --- | --- |
| F1 | Collect requirements by conversation and ask follow-up questions for missing mandatory fields |
| F2 | Emit a landing zone spec that validates against a JSON schema derived from module variables |
| F3 | Let the user choose a target cloud (GCP, Azure, AWS, OpenStack) and a profile (Starter, Standard, Regulated); cover hierarchy, identity, network and CIDR plan, guardrails, logging and audit, keys and cost controls per the capability mapping |
| F4 | Render tfvars and stage config from templates only, through the bundled lzctl CLI, so every host produces identical output; no freeform HCL |
| F5 | Run fmt, validate, lint, security scan and OPA policy checks on every render |
| F6 | Self-correct failed validations up to a fixed retry limit, then stop and report |
| F7 | Open a PR through a GitHub App with config, README, validation report and decision log |
| F8 | Support resuming a session and revising a spec after review comments |

**Non-functional**

| Area | Requirement |
| --- | --- |
| Security | No org-level credentials in the agent; validator isolated from secrets; all access authenticated (IAP or IAM) |
| Auditability | Every run records spec, output hash, model version and skill version to an append-only log |
| Determinism | Same spec plus same skill version renders byte-identical output |
| Latency | p95 end-to-end under 5 minutes from confirmed spec to PR (target; validate in P1) |
| Cost | Token and compute cost per run tracked and reported per team |
| Data residency | All storage and model calls pinned to approved regions |
| Encryption | CMEK on storage holding specs, artifacts and logs |

## Proposed architecture

One Cloud Run service hosts the ADK agents; everything with side effects sits behind a narrow tool and its own identity.

&#91;embedded content: system architecture · agent service, backing services, review path\]

The validator runs as a separate job so untrusted generated code never shares an identity with the agent. The agent's reach ends at the pull request: merge needs CODEOWNERS approval, and apply runs only in the existing pipeline.

## Agent design

The agent is a root orchestrator with three sub-agents, each holding only the tools its step needs. The skill supplies the knowledge; the agent code supplies control flow and guardrails.

**Skill package (`skills/landing-zone/`)**

```
SKILL.md                  # when to use, workflow, hard rules (host-neutral)
references/
  common.md               # spec fields, profiles, naming standards
  gcp.md azure.md aws.md openstack.md   # baseline, module catalog, gotchas
schemas/
  lz-spec.core.schema.json
  lz-spec.<cloud>.schema.json
templates/<cloud>/        # Jinja templates per baseline stage -> tfvars
policies/<cloud>/         # Rego rules used by conftest
scripts/lzctl             # validate, render, check, explain, doctor
evals/<cloud>/            # golden scenarios and expected specs
```

**Sub-agents**

| Agent | Responsibility | Tools |
| --- | --- | --- |
| Root (orchestrator) | Loads the skill, routes the conversation, enforces stop conditions | Sub-agent calls only |
| Intake | Interviews the user, fills the spec, asks for missing mandatory fields | `validate_spec` (JSON schema) |
| Composer | Selects modules and renders the spec into tfvars via templates | `render_templates`, `lookup_module_catalog` |
| Reviewer | Reads validation findings, edits the spec (not the HCL), re-renders | `run_validation`, `diff_outputs` |

One tool sits outside the loop: `open_pull_request`, callable only after validation passes and the user confirms.

**Self-correction loop**

1. Composer renders the spec.
2. `run_validation` triggers the validator job and returns structured findings.
3. Reviewer maps each finding back to a spec field and proposes an edit.
4. Repeat up to 3 times. On the third failure, stop and hand the findings to the user.

The Reviewer edits the spec, never the rendered output. That keeps every fix traceable to a field and keeps rendering deterministic.

**Session state** uses the ADK session service backed by Firestore (or Cloud SQL), so a reviewer can return to a run days later and revise it.

## Template strategy and spec schema

The LLM decides values; templates decide structure. Generated output is limited to tfvars and stage config for one pinned baseline, so reviewers diff configuration, not code.

**Rules**

- One pinned baseline per cloud per skill version (see Landing zone template configurations).
- The spec schema is generated from the baseline's module `variables.tf`, so hallucinated inputs fail schema validation before rendering.
- Templates are plain Jinja with no LLM in the render path, which makes rendering deterministic and unit-testable.
- Bumping the baseline version requires a skill release and a full eval run.

**Spec shape (abridged)**

```json
{
  "spec_version": "2.0",
  "target": { "cloud": "gcp | azure | aws | openstack", "profile": "starter | standard | regulated", "baseline_version": "string" },
  "organization": { "org_id": "string", "billing_account": "string", "domain": "string" },
  "hierarchy": { "environments": ["dev", "stage", "prod"], "business_units": ["string"] },
  "network": {
    "topology": "hub_spoke | shared_vpc_per_env",
    "regions": ["us-east4"],
    "cidr_supernet": "10.0.0.0/8",
    "private_service_connect": true
  },
  "security": {
    "vpc_sc": false,
    "cmek": true,
    "org_policy_profile": "baseline | regulated",
    "compliance": ["soc2", "pci"]
  },
  "logging": { "audit_sink": "bigquery | gcs | both", "retention_days": 400 },
  "iam": { "groups": { "org_admins": "email", "network_admins": "email", "security_admins": "email" } },
  "decisions": [{ "field": "string", "value": "any", "rationale": "string", "source": "user | default" }]
}
```

The `decisions` array becomes the PR's decision log: every non-default value records who chose it and why.

## Landing zone template configurations

The user picks a target cloud and a profile; the skill maps one cloud-agnostic spec onto a pinned baseline for that cloud. GCP, Azure and AWS ride vendor-maintained baselines; OpenStack has none, so we own its module set.

**Target clouds and baselines**

| Cloud | Baseline (pinned) | Terraform provider | Hierarchy | Notes |
| --- | --- | --- | --- | --- |
| GCP | Cloud Foundation Fabric FAST (alt: `terraform-example-foundation`) | `google` | Organization > folders > projects | Mature vendor reference |
| Azure | AVM for Platform Landing Zones: `avm-ptn-alz`, `avm-ptn-alz-management`, hub-and-spoke or Virtual WAN connectivity modules | `azurerm` / `azapi` | Tenant root > management groups > subscriptions | Do not target the classic `caf-enterprise-scale` module: archived August 1, 2026 |
| AWS | Control Tower landing zone + Account Factory for Terraform (AFT) + Organizations SCPs | `aws` | Organization > OUs > accounts | Landing Zone Accelerator is CDK/config-driven, not Terraform; we generate AFT account requests and SCPs |
| OpenStack | Our own module set on `terraform-provider-openstack` | `openstack` | Domain > projects (Keystone) | No vendor reference; capabilities vary by deployment (Octavia, Barbican, Designate may be absent) |

**Profiles**

| Profile | Use case | What it adds |
| --- | --- | --- |
| Starter | Sandbox, proof of concept | Hierarchy, one environment, single network, central logging, budgets |
| Standard (default) | Most enterprise workloads | dev/stage/prod, hub-and-spoke network, baseline guardrails, IAM groups, cost labels, audit log retention 1 year |
| Regulated | SOC 2, PCI-DSS, HIPAA scope | Standard plus customer-managed keys, private-only service access, service perimeter or preventive SCPs, stricter policy pack, break-glass accounts, longer log retention |

**Capability mapping**

Every spec field maps to one construct per cloud. A capability a cloud cannot provide is rejected at spec validation, not discovered at apply.

| Capability | GCP | Azure | AWS | OpenStack |
| --- | --- | --- | --- | --- |
| Hierarchy | Folders, projects | Management groups, subscriptions | OUs, accounts | Domains, projects |
| Identity and access | Cloud Identity groups, IAM | Entra ID groups, Azure RBAC | IAM Identity Center, permission sets | Keystone roles, groups |
| Network topology | Shared VPC, hub-and-spoke or NCC | Hub-and-spoke VNet or Virtual WAN | Transit Gateway, shared VPCs via RAM | Neutron networks, routers |
| Private service access | Private Service Connect | Private Endpoints | VPC endpoints (PrivateLink) | Provider networks (deployment-specific) |
| Central logging and audit | Org log sinks to BigQuery/GCS | Log Analytics, diagnostic settings | CloudTrail org trail, log archive account | Deployment-specific; usually external SIEM |
| Guardrails | Org policies, VPC-SC | Azure Policy (ALZ archetypes) | SCPs, Control Tower controls | Quotas, policy.yaml (operator-managed) |
| Key management | Cloud KMS (CMEK) | Key Vault, managed HSM | AWS KMS | Barbican (if deployed) |
| Cost controls | Budgets, labels | Budgets, tags | Budgets, tags, cost categories | Quotas only |

**Spec change:** the spec gains a `target` block (`cloud`, `profile`, `baseline_version`). Core fields stay cloud-agnostic; a per-cloud `extensions` block holds settings with no cross-cloud equivalent.

## Skill portability across agent hosts

One skill directory runs unchanged in Codex and Grok Build, because both read the open Agent Skills (`SKILL.md`) format. DeepSeek had no official coding harness as of mid-2026, so it runs through a `SKILL.md`-compatible host.

**Design change: deterministic work moves into a bundled CLI.** Every host model is different, so anything that must behave identically lives in `scripts/lzctl` (Python), not in model reasoning. The model's job shrinks to intake, field selection and explaining findings.

| Command | Does |
| --- | --- |
| `lzctl spec validate` | Checks the spec against the per-cloud JSON schema |
| `lzctl render --cloud <c>` | Renders templates to tfvars and stage config |
| `lzctl check` | Runs fmt, validate, tflint, trivy and conftest; emits JSON findings |
| `lzctl explain <finding>` | Maps a finding back to the spec field that caused it |

The Cloud Run ADK agent becomes one more host: it calls the same `lzctl`, so hosted and local runs produce byte-identical output for the same spec.

**Host support**

| Host | Model | Skill location | Status |
| --- | --- | --- | --- |
| Codex | OpenAI | `~/.codex/skills/` | Native Agent Skills |
| Grok Build | Grok | Reads ``  ~/.grok/skills/ ` | Beta since May 2026 |
| DeepSeek | DeepSeek V4 | Community hosts (DeepSeek-TUI, Deep Code CLI) read `.agents/skills/`; or point OpenCode at a DeepSeek endpoint | No official harness yet; re-check before P2 |
| Hosted agent | Gemini | Bundled in the container image | Governed path with audit log and PR flow |

**Portability rules**

- No host-specific tool names in `SKILL.md`; refer to "run `lzctl check`", not a vendor tool.
- Keep `SKILL.md` short and load `references/<cloud>.md` on demand, so small-context models still fit.
- Runtime dependencies: Python 3.11, Terraform or OpenTofu, tflint, trivy, conftest. `lzctl doctor` checks them.
- Ship one canonical copy in `.agents/skills/`, so hosts never read divergent copies.
- Evals run per host x model, because spec quality differs by model even when rendering is identical.

**Data governance gotcha:** in a local host, requirements text (org IDs, CIDR plans, group emails) goes to that host's model provider. Classify specs as internal-confidential, and confirm each provider is approved before allowing it. Third-party DeepSeek API endpoints will fail many enterprise data policies; a self-hosted open-weights endpoint is the usual workaround.

## Security and compliance

The agent's blast radius is a pull request: it can propose changes, never make them. Every control below protects that boundary.

| Threat | Control |
| --- | --- |
| Agent compromise leads to org changes | No org-level IAM on any agent identity; apply happens only in the existing human-approved pipeline |
| Prompt injection via requirements text | Model Armor screening on input and output; tools take typed arguments, not free text |
| Generated code exfiltrates data during validation | Validator runs as a separate Cloud Run Job with its own service account, no secrets, and egress limited to the Terraform registry mirror |
| Malicious or drifted upstream modules | Modules mirrored and pinned by version and checksum; provider lock file committed |
| Unauthorized use of the agent | Cloud Run ingress internal plus IAP or IAM invoker; no public endpoint |
| Leaked credentials | GitHub App private key in Secret Manager; Workload Identity Federation for CI; no service account keys |
| Unreviewed merges | Branch protection and CODEOWNERS on the target repo; agent cannot approve its own PR |
| Missing audit evidence | Append-only audit log to BigQuery with spec, output hash, model and skill versions per run |

**Service accounts (least privilege)**

- `lz-agent-sa`: invoke Gemini, run the validator job, read and write its own Firestore and GCS bucket, read the GitHub App secret.
- `lz-validator-sa`: read the artifact bucket prefix for its run, write findings. Nothing else.
- `lz-ci-sa`: deploy the service and job via Workload Identity Federation from GitHub Actions.

**Compliance mapping** (SOC 2, PCI-DSS where in scope): change management through PRs, separation of duties between the agent and approvers, audit logging, encryption with CMEK, and access control through IAP. Confirm with the compliance team which controls this system inherits versus owns.

## Infrastructure, deployment and CI/CD

The agent's own infrastructure is defined in Terraform in the same repo and deployed by GitHub Actions; nothing is created by hand.

| Component | GCP service | Notes |
| --- | --- | --- |
| Agent service | Cloud Run service | ADK app container; min instances 1 to avoid cold starts mid-conversation |
| Validator | Cloud Run Job | Image with terraform, tflint, trivy, conftest; one execution per validation |
| Images | Artifact Registry | Vulnerability scanning on; images signed and enforced with Binary Authorization |
| Session state | Firestore (native mode) | ADK session store |
| Artifacts | Cloud Storage | Rendered output and findings per run; CMEK; lifecycle delete after retention period |
| Secrets | Secret Manager | GitHub App private key |
| Audit log | BigQuery | Log sink plus explicit run records |
| Model | Gemini via Gemini Enterprise Agent Platform | Regional endpoint; model version pinned in config |
| Prompt security | Model Armor | Template applied to agent input and output |

**Repository layout**

```
agent/            # ADK app: agents, tools, callbacks
skills/           # landing-zone skill package, all clouds, lzctl
validator/        # job image and entrypoint
infra/            # Terraform for the agent's own platform
evals/            # golden scenarios and expected specs
.github/workflows/
```

**Pipeline**

1. On PR: unit tests, template render tests, ADK evals against the golden set, Terraform plan for `infra/`.
2. On merge to main: build and sign images, apply `infra/` to staging, deploy to staging, smoke test.
3. Promote to production by manual approval, deploying the same image digest.

Skill releases follow the same flow, because a skill change can alter output as much as a code change.

## Reliability, observability and evals

Quality is measured by evals before release and by SLOs in production; a model or skill change that drops eval scores does not ship.

**SLIs and initial SLO targets** (provisional; set real targets after 4 weeks of P2 data)

| SLI | Definition | Initial target |
| --- | --- | --- |
| Run success rate | Confirmed specs that end in an opened PR | 95% over 28 days |
| First-pass validation rate | Renders that pass validation with no Reviewer loop | Track only in MVP |
| Critical policy findings in PRs | Critical findings present in opened PRs | 0 |
| End-to-end latency | Confirmed spec to PR opened, p95 | Under 5 minutes |
| Cost per run | Model tokens plus Cloud Run compute | Track and report per team |

**Telemetry**

- OpenTelemetry traces from ADK into Cloud Trace, with model version, skill version and run ID on every span.
- Structured logs to Cloud Logging, sunk to BigQuery for analysis.
- Burn-rate alerts on run success rate (fast and slow windows) routed to the owning team's on-call.

**Evals**

- Golden set of 15 to 25 scenarios: small org, regulated (PCI), multi-region, VPC-SC on, conflicting requirements, adversarial input.
- Each scenario checks the spec against an expected spec (field-level match) and asserts zero critical findings after render.
- Runs in CI on every agent, skill, template or model-version change.

**Failure handling**

- Gemini errors or quota exhaustion: retry with backoff, then fail the run cleanly with session state preserved.
- Validator job failure: surfaced to the user as an infrastructure error, not a configuration error.
- GitHub API failure: output stays in GCS; PR creation can be retried without re-rendering.

## Alternatives considered

The chosen design trades some flexibility for reviewability and auditability, which are the two properties enterprise adopters will test first.

| Option | Why not chosen |
| --- | --- |
| LLM generates freeform HCL | Unreviewable diffs, non-deterministic output, fails audit and change review |
| Agent runs plan and apply directly | Requires org-level credentials in an LLM-driven system; unacceptable blast radius |
| Agent Runtime (managed, formerly Agent Engine) instead of Cloud Run | Less control over networking, container contents and validator isolation; revisit if managed sessions and identity features reduce our infrastructure burden |
| GKE instead of Cloud Run | Operational overhead not justified at expected request volume |
| Static questionnaire plus templates, no LLM | Deterministic, but rigid intake and no reasoning over conflicting requirements; remains the fallback if eval quality stalls |
| Knowledge in agent prompts instead of a skill | Couples knowledge to one runtime; blocks reuse across Codex, Grok Build and DeepSeek-backed hosts |
| MCP server only, no skill | Works in more hosts, but carries tools without workflow knowledge; we keep the skill and add an optional MCP wrapper around lzctl |
| One abstract multi-cloud Terraform module | Hides each cloud's native constructs and lags vendor baselines; per-cloud baselines behind one spec keep the vendor-supported path |

## Delivery plan and milestones

The GCP-first MVP (P0 and P1) is 9 to 12 engineer-weeks; all four clouds and three hosts take 21 to 29 engineer-weeks in total (see Cost estimate).

&#91;embedded content: delivery roadmap · 4 phases, 3 gates, 21 to 29 engineer-weeks\]

Phases are gated rather than dated: a phase starts only when the previous gate's criteria pass. Each new cloud adds references, schema, templates, policies and evals to the same skill; the agent and `lzctl` stay unchanged.

## Cost estimate

Running the hosted agent costs about $110 to $370 a month for dev plus prod, and model tokens are most of it. Building all four clouds costs about $100K to $140K in engineer time, and maintenance, not cloud spend, is the long-run cost driver.

**Assumptions:** us-central1 (Tier 1), 200 prod runs and 50 dev runs a month, Gemini 3 Flash for intake and Gemini 3.1 Pro for composing and reviewing, list prices in USD. Agent Platform prices can differ from Gemini API list prices; confirm in the pricing calculator before budgeting.

**Cost per run (hosted agent)**

| Step | Model | Tokens per run | Cost |
| --- | --- | --- | --- |
| Intake | Gemini 3 Flash ($0.50 in / $3 out per 1M) | \~150K in, \~10K out | \~$0.11 |
| Compose and review loop | Gemini 3.1 Pro ($2 in / $12 out per 1M; $0.20 cached in) | \~250K in (60% cached), \~25K out | \~$0.53 |
| **Total** |  |  | **\~$0.65 (range $0.30 to $1.20)** |

**Monthly run cost, prod environment**

| Component | Basis | $/month |
| --- | --- | --- |
| Gemini tokens | 200 runs x \~$0.65 | 60 to 240 |
| Cloud Run service | 1 warm min instance, 1 vCPU / 2 GiB at idle rates (\~$19); active time mostly in free tier | 20 to 25 |
| Validator job | \~600 executions x \~2 min, 2 vCPU / 4 GiB | 3 to 5 |
| Model Armor | Screening on all prompts and responses | Verify; budget 0 to 20 |
| Logging, Monitoring, Trace | Mostly inside free allotments | 0 to 10 |
| KMS, Secret Manager, Firestore, GCS, Artifact Registry, BigQuery | Small volumes | 3 to 8 |
| **Prod total** |  | **\~90 to 310** |

**Monthly totals by scenario**

| Scenario | $/month |
| --- | --- |
| Dev only (min instances 0, \~50 runs) | 20 to 60 |
| Dev plus prod (table above) | 110 to 370 |
| Add hardening: HTTPS load balancer with IAP, Cloud NAT for validator egress | +25 to 60 |
| Eval spend during active development (weekly full suite plus PR smoke tests) | +300 to 600 |
| Local hosts (Codex, Grok Build, DeepSeek) | $0 on our bill; tokens charged to each user's own plan or API key |

**Eval cost gotcha:** a full suite is 25 scenarios x 4 clouds = 100 runs, about $65. Run it nightly and it costs about $2,000 a month. Run an 8-scenario smoke subset on PRs and the full suite weekly and at release.

**One-time build cost**

Estimated at a $120/hour fully loaded rate ($4,800 per engineer-week); scale linearly to your rate.

| Workstream | Engineer-weeks | Cost |
| --- | --- | --- |
| Core: spec schema, `lzctl`, validator image, eval harness | 4 to 5 | $19K to $24K |
| GCP baseline: templates, policies, evals | 2 to 3 | $10K to $14K |
| Hosted agent: ADK on Cloud Run, infra, CI/CD, PR flow | 3 to 4 | $14K to $19K |
| Azure baseline (AVM ALZ) | 2 to 3 | $10K to $14K |
| AWS baseline (Control Tower, AFT, SCPs) | 3 to 4 | $14K to $19K |
| OpenStack module set (built and owned by us) | 4 to 6 | $19K to $29K |
| Host compatibility testing (3 hosts) | 1 to 2 | $5K to $10K |
| Security review, documentation, pilot | 2 | $10K |
| **Total** | **21 to 29** | **\~$100K to $140K** |

A GCP-first MVP (core, GCP, hosted agent) is 9 to 12 engineer-weeks, about $43K to $58K.

**Ongoing maintenance** is roughly 0.25 to 0.5 FTE ($60K to $125K a year): baseline and provider upgrades across four clouds, eval upkeep, and host changes. It is more than ten times the annual cloud run cost, so budget headcount before infrastructure.

## Risks and mitigations

The largest risk is false confidence: a PR that passes static checks but fails at plan or apply because of org-specific constraints the MVP cannot see.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Validate-only misses org policy conflicts that appear at plan or apply | High | State the limitation in every PR body; add sandbox plan per cloud in P3 |
| Requirements data sent to unapproved model providers from local hosts | High | Classify specs as internal-confidential; publish an approved host and model list; self-hosted endpoint for DeepSeek |
| OpenStack deployments differ (missing Octavia, Barbican, Designate) | High | Capability discovery in `lzctl doctor`; reject unsupported spec fields up front |
| Upstream baseline drift (provider majors such as AzureRM 5.0, FAST releases) | Medium | Pin by tag per cloud; schema regenerated and evals rerun on every bump |
| AWS landing zone is only partly Terraform-native (Control Tower, AFT) | Medium | Generate AFT requests and SCPs only; leave Control Tower enablement to a one-time, documented step |
| Host behavior drift (new Codex, Grok Build releases) | Medium | Host x model eval matrix; pin skill compatibility notes per host version |
| Eval token spend runs away | Medium | PR smoke subset, weekly full suite, budget alert on the eval project |
| Hallucinated module inputs | Medium | Schema generated from module variables; validation before render |
| Prompt injection through pasted requirements | Medium | Model Armor in the hosted agent; typed `lzctl` arguments; no write credentials in reach |
| Product and API renames (Vertex AI to Gemini Enterprise Agent Platform; Agent Engine to Agent Runtime) | Low | Verify current names at build time; isolate model calls behind one client module |
| Low adoption because platform engineers distrust generated config | High | Decision log, deterministic rendering and small diffs make review fast; pilot with one team per cloud |

## Open questions and decisions needed

The baseline choice blocks P0 and should be decided first; the rest can be settled during P1.

- [ ] **GCP baseline:** Fabric FAST (modular, easier to compose; recommended) or `terraform-example-foundation` (closer to Google's official reference)?
- [ ] **AWS approach:** Control Tower plus AFT (recommended), or Organizations and SCPs only for teams without Control Tower?
- [ ] **OpenStack target:** which distribution and which optional services (Octavia, Barbican, Designate) must the first version support?
- [ ] **Cloud order after GCP:** Azure then AWS, or driven by the first pilot team?
- [ ] **Approved hosts and models:** which of Codex, Grok Build and DeepSeek are cleared by security and data governance?
- [ ] **Loaded rate:** confirm the $120/hour assumption used in the build estimate.
- [ ] **Interface for the hosted agent:** CLI, Slack, or Gemini Enterprise?
- [ ] **Target repo model:** one PR to a shared foundation repo, or a new repo per landing zone?
- [ ] **Sandbox environments for P3:** a test org, tenant, AWS organization and OpenStack project, and who funds them?
- [ ] **Compliance:** which SOC 2 and PCI controls does this system own versus inherit?

## Sources

- [Google unveils Gemini Enterprise Agent Platform (HPCwire, April 2026)](https://www.hpcwire.com/aiwire/2026/04/23/google-unveils-gemini-enterprise-agent-platform/): Vertex AI rebrand and platform scope.
- [google-agents-cli-deploy skill](https://skillselion.com/skills/google/agents-cli/google-agents-cli-deploy): ADK deployment targets and Cloud Run auth limits.
- [adk-skill (GitHub)](https://github.com/miticojo/adk-skill): ADK and the open Agent Skills specification; Codex skill path.
- [Deep Code CLI review (Verdent)](https://www.verdent.ai/guides/deep-code-cli-review): DeepSeek hosts and SKILL.md support; no official harness as of May 2026.
- [Azure landing zones Terraform module (GitHub)](https://github.com/Azure/terraform-azurerm-caf-enterprise-scale): archive date and AVM recommendation.
- [AzureRM 5.0 and classic ALZ (eCorpIT)](https://ecorpit.com/ecorpit-azure-landing-zone-terraform-iac-modernization-service-india-2026/): AVM pattern modules for ALZ.
- [Gemini API pricing (BenchLM, July 2026)](https://benchlm.ai/google/api-pricing): Gemini 3.1 Pro and Gemini 3 Flash rates.
- [Gemini 3.1 Pro pricing calculator](https://trevorfox.com/tools/calculators/llm-cost/google-gemini/gemini-3.1-pro/): cached input rate.
- [Cloud Run pricing (Google Cloud)](https://cloud.google.com/run/pricing): free tier and billing modes.
- [Cloud Run Functions pricing (nOps)](https://www.nops.io/blog/cloud-run-functions-pricing/): Tier 1 active and idle min-instance rates.
