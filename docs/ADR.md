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
| [013](#adr-013-github-oidc-through-workload-identity-federation-one-service-account-per-environment) | GitHub OIDC through Workload Identity Federation, one service account per environment | Accepted | 2026-10-07 |
| [014](#adr-014-secrets-in-secret-manager-encrypted-with-our-kms-key-github-environment-secrets-only-for-ci) | Secrets in Secret Manager encrypted with our KMS key; GitHub environment secrets only for CI | Accepted | 2026-10-07 |
| [015](#adr-015-cicd-strategy-and-workflow-naming) | CI/CD strategy and workflow naming | Proposed | 2026-10-07 |
| [016](#adr-016-open-to-contributors-under-apache-20) | Open to contributors under Apache-2.0 | Accepted | 2026-10-07 |
| [017](#adr-017-environment-folders-and-the-environment-tag) | Environment folders and the environment tag | Accepted | 2026-10-07 |
| [018](#adr-018-dev-accepts-changes-only-by-pull-request-except-the-owner) | `dev` accepts changes only by pull request, except the owner | Accepted | 2026-10-07 |
| [019](#adr-019-every-taggable-resource-carries-both-the-name-and-environment-tags) | Every taggable resource carries both the name and environment tags | Accepted | 2026-10-07 |
| [020](#adr-020-gcp-output-is-a-vendored-fast-dataset-plus-overlay-templates) | GCP output is a vendored FAST dataset plus overlay templates | Accepted | 2026-10-07 |
| [021](#adr-021-lzctl-check-verifies-rendered-output-and-says-which-checks-did-not-run) | `lzctl check` verifies rendered output and says which checks did not run | Accepted | 2026-10-08 |
| [022](#adr-022-trivy-and-checkov-both-scan-rendered-hcl) | Trivy and Checkov both scan rendered HCL | Accepted | 2026-10-08 |

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
- The key is parented by the project, but it binds to other resources in the same organization too: the `dev`, `stage` and `prod` folders were tagged with it on 2026-10-07 (ADR-017). The earlier note that it worked only inside the project was wrong. Resources in a different organization (P3 sandboxes) need their own tag key.
- Terraform needs explicit binding resources for most services, which adds one resource per tagged resource.
- The deploying identities (`lz-bootstrap-sa`, `lz-dev-sa`; see ADR-013) need `roles/resourcemanager.tagUser` on the tag value and on the resources it binds to.
- The tag does not apply to landing zones the agent generates for users.

## ADR-013: GitHub OIDC through Workload Identity Federation, one service account per environment

**Status:** Accepted · 2026-10-07 · Built; see [runbook](runbooks/gcp-state-bucket-and-github-oidc.md)

**Context.** CI needs Terraform state and, later, deploy rights without service account keys. The owner asked for the GCP equivalent of an AWS OIDC role, and for GitHub environments `bootstrap` and `dev`. The repo is public, and its default branch is `dev`.

**Decision.**
- **Trust:** workload identity pool `github` with OIDC provider `github-actions`. The provider only accepts tokens whose `repository_owner_id` is `165821667` (`loriamichaelj`), so other skill repos from the same account can reuse the pool.
- **Roles:** one service account per GitHub environment (`lz-bootstrap-sa`, `lz-dev-sa`). Each can be impersonated only by the exact subject `repo:loriamichaelj@165821667/terraform-landing-zone-template-skill@1409542604:environment:<env>`, the same check an AWS trust policy makes on `sub`. The subject uses GitHub's immutable format (owner and repo IDs), so renaming or recreating the repo can't take over the trust. The first bindings used the name-only format and were refused; they were corrected on 2026-10-07.
- **State:** one bucket, `skills-mjl-27850-tlz-tfstate` (us-central1). It has versioning, keeps up to 10 noncurrent versions for at most 90 days, enforces uniform access and public access prevention, and uses one prefix per environment. Both service accounts have `roles/storage.objectUser` on it.
- **Tags:** the bucket and both service accounts carry the ADR-012 tag. The pool and provider are global resources that can't take tags.

This replaces the single `lz-ci-sa` in DESIGN.md with per-environment accounts. Service account impersonation was chosen over direct federated access because some Google APIs the agent's infrastructure will use don't accept federated principals.

**Consequences.**
- Jobs must declare `environment:` to authenticate. Jobs without one, and pull requests from forks (which get no OIDC token), can't reach GCP.
- Both accounts can read each other's state prefix. Split into one bucket per environment if that becomes a problem.
- The state bucket uses Google-managed encryption, not the CMEK required in DESIGN.md for agent data. Key ring `tlz` now exists (ADR-014), so a separate `tfstate` key there could close this gap.
- Neither account has any infrastructure permissions yet. Grant them per environment as `infra/` is written, and add required reviewers to an environment before giving its account write access.
- Verified 2026-10-07 by **Ops: OIDC check** in both environments. Each environment's job authenticated and ran Terraform against the bucket. A job with no environment, and a job asking for the other environment's account, were both refused.

## ADR-014: Secrets in Secret Manager encrypted with our KMS key; GitHub environment secrets only for CI

**Status:** Accepted · 2026-10-07 · Built; see [runbook](runbooks/secrets.md)

**Context.** The owner asked to store secrets "in KMS" and in GitHub's `dev` environment. KMS stores keys, not secrets, so the owner chose Secret Manager encrypted with a customer-managed KMS key (CMEK), which DESIGN.md already requires for stored data. The specific secrets are still to be listed.

**Decision.**
- **Key:** key ring `tlz` in us-central1, with key `secret-manager` (software protection, 90-day automatic rotation). Only the Secret Manager service agent can encrypt and decrypt with it.
- **Secret Manager:** secrets use user-managed replication pinned to us-central1 with that key, which meets the data-residency requirement.
- **Access:** set by name prefix through conditional IAM. `lz-dev-sa` can read `dev-*` secrets and `lz-bootstrap-sa` can read `bootstrap-*` secrets, matching the GitHub environment that can impersonate each account (ADR-013).
- **GitHub environment secrets** hold only what a CI job needs outside GCP. GCP credentials never go there, because CI authenticates with OIDC.

**Consequences.**
- CMEK is not enforced by policy. A secret created without `--kms-key-name` silently uses Google-managed encryption. Consider the `constraints/gcp.restrictNonCmekServices` org policy for Secret Manager once more secrets exist.
- The key ring can never be deleted, so its name is permanent. Keys can be disabled and destroyed (with a scheduled-destruction delay).
- KMS keys can't take tags; the key inherits the ADR-012 tag from the key ring.
- The terraform state bucket still uses Google-managed encryption (ADR-013). It could reuse this key ring with a separate key.

## ADR-015: CI/CD strategy and workflow naming

**Status:** Proposed · 2026-10-07 · Details in [CICD.md](CICD.md)

**Context.** The repo has its OIDC trust, the `bootstrap` and `dev` environments and a state bucket, but no workflows. DESIGN.md's pipeline assumed a `main` branch and a staging environment, neither of which exists; `dev` is the default branch. The owner asked for a test of OIDC in `dev` and a scoped pipeline with naming rules before more workflows are written.

**Decision.**
- **Branching:** `dev` is trunk and the only deploy target until production exists. Work happens in short-lived branches merged to `dev` by pull request. `main` and `prod` come later, with promotion by the same image digest.
- **Workflows:** plan on pull request, apply on merge; one identity per environment. A read-only `dev-plan` identity will be added for PR plans once `dev` is limited to deploying from its own branch.
- **Naming:** workflow files are `<category>-<subject>[-<environment>].yml`, with categories `ci`, `cd`, `ops`, `release` and `reusable`. Display names are `<Category>: <Subject>`. Job IDs are stable kebab-case, because they become required status checks.
- **Actions policy:** pin every action to a full commit SHA, with Dependabot updating pins weekly. Allow only GitHub, Google and HashiCorp actions plus named tools. Use pinned runner images, `permissions: {}` by default, and a timeout on every job.
- **First workflow:** `ops-oidc-check.yml` proves the trust works and is scoped. One job must authenticate in its own environment and use the state bucket through Terraform. Two jobs must be refused: one with no environment, and one asking for the other environment's account.

**Consequences.**
- Some repo settings in CICD.md are applied (ADR-016, ADR-018); selected actions, required SHA pinning, status checks and environment protections are still only proposed, so nothing enforces those conventions yet.
- Renaming a workflow or job later breaks any required status check that references it.
- Repo-level variables `GCP_PROJECT_ID` and `GCP_WORKLOAD_IDENTITY_PROVIDER` were added, so jobs without an environment can name the provider. They're identifiers, not secrets.

## ADR-016: Open to contributors under Apache-2.0

**Status:** Accepted · 2026-10-07

**Context.** The repo is public but had no license, so nobody could legally reuse or contribute to it. The owner asked to set it up for contributors and community engagement, and chose the license, the contact model, Discussions and the merge policy.

**Decision.**
- **License:** Apache-2.0, matching Fabric FAST, ADK and the Google GitHub actions. Contributions are licensed under the same terms (section 5); there's no CLA.
- **Community files:** CONTRIBUTING, Contributor Covenant 2.1 Code of Conduct, SECURITY, SUPPORT, CODEOWNERS (`@loriamichaelj`), a PR template, and issue forms (bug report, feature request, design proposal). Blank issues are off; questions are routed to Discussions.
- **Reporting:** security and conduct reports go through GitHub private vulnerability reporting. No email address is published.
- **Discussions** are on, with the default categories (Q&A, Ideas, Show and tell, Announcements, General, Polls).
- **Merging:** squash only, using the PR title (Conventional Commits) and body. Branches are deleted on merge.
- **Security settings:** Dependabot alerts and security updates, secret scanning and push protection are on. Workflows on PRs from all outside contributors need maintainer approval.
- **Labels:** `needs-triage`, `design`, `ci`, `security`, `area: skill|agent|infra` and `cloud: gcp|azure|aws|openstack`, alongside GitHub's defaults.

**Consequences.**
- Conduct reports use the security advisory form, which is a workaround: GitHub has no private channel dedicated to conduct reports.
- With one maintainer, the SECURITY.md response targets are best-effort.
- CODEOWNERS review became required for everyone except the owner when the `dev` ruleset was added (ADR-018).

## ADR-017: Environment folders and the environment tag

**Status:** Accepted · 2026-10-07

**Context.** The owner asked for `dev`, `stage` and `prod` folders in `mikejloria-org`, for project `skills-mjl-27850` to move into `dev`, and for an `environment:dev` tag. The org had no folders, and the owner had neither Folder Creator nor Tag Administrator. gcloud warned on every command that the project had no environment tag, which Google recognizes only from a tag key named `environment`, defined at the organization or folder level.

**Decision.**
- **Folders:** `dev` (`folders/943512507903`), `stage` (`folders/627589503607`) and `prod` (`folders/615332921566`), directly under the org (the owner's choice). They're shared by every skill in the org, so other skills put their projects in them rather than creating their own environment folders.
- **Project:** `skills-mjl-27850` moved from the org root into `dev`.
- **Environment tag:** org-level key `environment` (`tagKeys/281478650722081`) with values `dev`, `stage` and `prod`, which Google recognizes as Development, Staging and Production. Each folder carries its value, so projects inherit it. `skills-mjl-27850` is also bound directly to `environment:dev`; gcloud now reports `[environment: Development]`.
- **Name tag:** all three folders carry the ADR-012 name tag.
- **Permissions:** the owner (`mikejloria@gmail.com`) was granted `roles/resourcemanager.folderCreator`, `roles/resourcemanager.tagAdmin` and `roles/resourcemanager.tagUser` on the organization, at the owner's request.

**Consequences.**
- Folder names at the org root are unique, so no other top-level folder can be called `dev`, `stage` or `prod`.
- Org policies and IAM set on a folder now apply to the project. Today the folders have none, so the project's effective access didn't change.
- `stage` and `prod` stay empty for now (owner decision, 2026-10-07): no projects, GitHub environments, service accounts or state prefixes. They hold the place and the environment tag until those environments are needed. Whether stage joins the pipeline is decided when it's first populated (CICD.md).
- The ADR-012 name tag binding to folders showed that a project-parented tag key works across the organization; ADR-012 was corrected.

## ADR-018: `dev` accepts changes only by pull request, except the owner

**Status:** Accepted · 2026-10-07

**Context.** `dev` is the default branch and the only deploy target (ADR-015), but anyone with write access could push to it directly or force-push over history. The owner asked for branch protection on `dev` that blocks direct pushes for everyone except themselves. The repo is user-owned, and `@loriamichaelj` is its only collaborator and only admin.

**Decision.** Repository ruleset **dev: pull requests only** (id `24695181`), active on `refs/heads/dev`:

- Changes only through pull requests, merged by squash.
- 1 approving review, which must come from a code owner. Approvals are dismissed when new commits are pushed, and all review conversations must be resolved.
- Linear history; no force-pushes; the branch can't be deleted.
- **Bypass:** the repository Admin role, mode "always". Only the owner holds that role, so only the owner can push directly or merge without a review.

A ruleset was used rather than classic branch protection: rulesets are GitHub's current mechanism, they're visible to everyone who can read the repo, and they support bypass lists.

**Consequences.**
- The bypass is tied to the Admin role, not to a username. Anyone later given Admin on this repo can also bypass, so keep other collaborators at Write or Maintain.
- Anything acting with the owner's credentials (a local `gh` session, a personal access token, automation running as the owner) bypasses too. Bots such as Dependabot don't, and must go through pull requests.
- No required status checks yet, because no PR workflows exist. Add CI: Docs and CI: Workflows to this ruleset when they land (CICD.md).
- The owner can still force-push to `dev` through the bypass, as was done for the history rewrite earlier. That's deliberate but should stay rare; anyone else with a clone has to reset after a force-push.

## ADR-019: Every taggable resource carries both the name and environment tags

**Status:** Accepted · 2026-10-07 · Requested by the project owner · Extends ADR-012 and ADR-017

**Context.** ADR-012 requires the `name` tag on every resource this repo creates, and ADR-017 puts the `environment` tag on folders and projects only. A check on 2026-10-07 showed the project carried both, but the state bucket and the `tlz` key ring carried only `name`. They inherit `environment:dev` from the project, but an inherited tag doesn't show in a per-resource audit and is lost if the resource moves. The owner asked that resources be tagged with both `environment:dev` and `name:Terraform-Landing-Zone-Template-Skill`.

**Decision.**
- Bind both tags explicitly on every taggable resource this repo creates: `skills-mjl-27850/name/Terraform-Landing-Zone-Template-Skill` (`tagValues/281477778372023`) and `618554946741/environment/<env>` (`dev` is `tagValues/281477792549021`). The environment value matches the environment the resource is deployed to.
- Bound on 2026-10-07: `environment:dev` on `gs://skills-mjl-27850-tlz-tfstate` and on key ring `tlz`.
- The conftest rule on the `infra/` plan (ADR-012) checks for both bindings.
- Resource types that can't carry tags are exempt: service accounts (`lz-bootstrap-sa`, `lz-dev-sa`), the Workload Identity pool and provider, KMS keys, and enabled APIs. Their key ring, project and bindings carry the tags instead. Secrets created later must be tagged at creation.

**Consequences.**
- Terraform needs two binding resources per tagged resource, or two entries in a resource's own `tags` argument where the provider supports it.
- The deploying identities need `roles/resourcemanager.tagUser` on the `environment` value as well as on the `name` value.
- Which resource types accept tags depends on the service, so the exemption list is checked against Google's tag-supported-resources list when `infra/` is written.

## ADR-020: GCP output is a vendored FAST dataset plus overlay templates

**Status:** Accepted · 2026-10-07 · Refines ADR-007

**Context.** A FAST `0-org-setup` dataset is a whole tree of about 40 YAML files, and only a handful carry organization-specific values. Rendering has to be deterministic (ADR-002), the output has to validate against FAST's own JSON schemas, and an upstream bump must be reviewable. Fetching the dataset from GitHub at render time would break determinism and the no-network validator rule (ADR-008). Writing every file as a template would bury the few lines we change under hundreds we don't.

**Decision.**
- `tools/vendor_fast.py` copies the pinned dataset (`classic` for v59.0.0), the stage's JSON schemas and the upstream license, unmodified, into `templates/gcp/fast-<tag>/upstream/`. It pins by commit SHA and writes `MANIFEST.json` with a SHA-256 for every file.
- `lzctl render` refuses to run if any vendored file differs from the manifest. It copies the dataset and replaces only what the spec drives, using Jinja templates in `overlay/` (strict undefined variables, no model, no network): `defaults.yaml`, the log project's buckets, the `environment` tag values, and the per-environment and per-business-unit folders.
- Every value that reaches a template is pattern-restricted by the schemas, and control characters are rejected, so a spec can't inject YAML.
- Output is `datasets/landing-zone/**` plus `0-org-setup.auto.tfvars` and a `render-report.json` with per-file SHA-256, an `output_hash`, the baseline commit, and `not_rendered_yet`: the spec fields this slice doesn't turn into configuration. Nothing is dropped silently.
- The `regulated` profile is refused until the `hardened` dataset is vendored. A classic dataset must not be labeled regulated.
- The GCP spec schema constrains the whole spec, and `extensions.gcp` now requires `customer_id` (Cloud Identity) and `prefix` (project prefix, 2 to 8 characters), both of which `defaults.yaml` needs.

**Consequences.**
- Same spec plus same skill version gives byte-identical output; checked on Python 3.11, 3.12 and 3.13, and pinned by golden output hashes in `evals/gcp/golden/`.
- Bumping the baseline means running the vendor tool for the new tag, diffing `upstream/` against the old one, updating the overlays that changed, and a full eval run.
- The overlays duplicate the upstream files they derive from. The pristine copy is kept so a bump diff shows what upstream changed.
- `classic` defines only `development` and `production`. `stage` is supported by adding a `staging` tag value and stage folders in the overlay, which is our extension rather than upstream's.
- `classic` creates an organization tag key named `environment`. Applying a rendered landing zone to an organization that already has such a key (this repo's own org does, ADR-017) needs that key imported first. The agent never applies, so this only affects the team applying the PR.
- Not rendered yet: `2-networking`, `2-security`, `1-vpcsc`, the hardened dataset, and the extra regions, CIDR plan and network groups. They are listed in the report for every render.


---

## ADR-021: `lzctl check` verifies rendered output and says which checks did not run

**Status:** Accepted · 2026-10-08 · Implements the `lzctl check` row of DESIGN.md

**Context.** DESIGN.md promised that every render is checked with fmt, validate, tflint, trivy, conftest and the upstream schemas before a human sees it (F5). The GCP slice renders FAST YAML datasets and one tfvars file, so most of those tools have nothing to inspect. A check that reports "passed" for work it didn't do would give reviewers false confidence, which the design names as the largest risk. The rendered directory is also untrusted input to the validator: it may come from a PR branch or another host.

**Decision.**
- `lzctl check <dir>` takes a directory written by `lzctl render` and emits JSON `{ok, checks, findings}`. Each finding has the same `rule`, `path`, `message` shape as `spec validate`, with rules under `check.*`. Exit 0 is clean, 1 is findings, 2 is a directory that can't be checked.
- **Integrity.** Every file must match `render-report.json`: no missing, extra or modified files, a recomputed `output_hash`, and no symlinks (never followed). Rendered files are never edited by hand (SKILL.md); this makes a hand edit fail rather than slip through.
- **Upstream schemas.** Every YAML file that declares a FAST schema is validated against the vendored copy, and the vendored copy is first verified against `MANIFEST.json`. A file that declares a schema we don't vendor is a finding. The report's baseline tag must match the vendored one. This catches an edited file whose report was re-signed, which integrity alone can't.
- **`terraform fmt -check`** runs when `terraform` or `tofu` is installed, and is `skipped` otherwise.
- `terraform validate`, `tflint`, `trivy` and `conftest` are reported `not_applicable` with a reason: no HCL is rendered and there is no policy pack. They become real checks when the networking and security datasets and the Rego policies land, and the list lives in one constant (`NOT_APPLICABLE`).
- PyYAML becomes a runtime dependency of `lzctl` (it was test-only), and `lzctl doctor` checks for it.

**Consequences.**
- Reviewers and the hosted agent can tell "passed" from "did not run" from the `status` of each check. A skill or agent must not describe the output as fully validated while any check is `not_applicable` or `skipped`.
- The check needs no network and no model, so it can run in the validator job (ADR-008) and gives the same result on every host.
- Integrity detects change, not origin: someone who edits files and re-signs the report passes integrity, and is caught only if the edit breaks a schema. Provenance of the render (who ran it, which spec) belongs to the PR flow in P1.
- Findings point at rendered files, not spec fields. `lzctl explain` (next) will map them back.


---

## ADR-022: Trivy and Checkov both scan rendered HCL

**Status:** Accepted · 2026-10-08 · Refines ADR-021

**Context.** The design lists trivy as a static check (F5). The project owner also asked for Checkov. Both are misconfiguration scanners for Terraform with overlapping GCP coverage, and neither has anything to scan in today's output, which is FAST YAML datasets plus one tfvars file. ADR-021 requires that a check which did not run is never reported as passed.

**Decision.**
- `lzctl check` runs `trivy config` and `checkov` (terraform framework) over the rendered directory whenever it contains `.tf` files. With no `.tf` file, both are `not_applicable`; with the tool missing, `skipped`.
- Both run offline: `--skip-check-update` for trivy, `--skip-download` for Checkov, in the rendered directory, with a 120 s timeout. Neither tool's exit code is trusted alone: the JSON report is parsed. A crash, timeout, unparsable output or a Checkov parsing error is a finding, never a pass.
- Findings keep the tool in the rule (`check.trivy.GCP-0002`, `check.checkov.CKV_GCP_114`) and point at the rendered file. They are not deduplicated across tools: where both flag the same resource, the reviewer sees both IDs.
- Inline suppression comments (`checkov:skip`, `trivy:ignore`, `tfsec:ignore`) in rendered HCL are a finding (`check.hcl.suppression`). Output comes from templates, so a suppression there is either a template bug or an edit, and either way it must not silently opt out of the scans.
- Both tools are optional in `lzctl doctor` today. They become required in the validator image, with pinned versions.

**Consequences.**
- Nothing new runs on today's GCP output, and the report says so. The scanners start working when the networking and security slices emit HCL, or when an `infra/` render is added, with no further `lzctl` change.
- Two scanners mean two sets of false positives and two version pins in the validator image (ADR-008). If one proves redundant on real HCL, drop it by superseding this ADR, informed by the findings each one actually produced.
- Excluding a finding that is a known false positive needs a design decision (an allowlist in the spec or the policy pack, reviewed in the PR), not a code comment. No allowlist exists yet.

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

### 2026-10-07: Build-out and docs sweep

**Built after the first review** (each recorded in its ADR):

| What | ADR |
| --- | --- |
| Terraform state bucket, GitHub OIDC trust, per-environment service accounts | 013 |
| Secret Manager with KMS key ring `tlz`, prefix-scoped secret access | 014 |
| CI/CD strategy, naming conventions, **Ops: OIDC check** workflow (passing in `dev` and `bootstrap`) | 015 |
| License, community files, Discussions, merge and security settings | 016 |
| `dev`, `stage` and `prod` folders, org-level `environment` tag, project moved into `dev` | 017 |
| `dev` ruleset: pull requests only, code-owner approval, owner bypass | 018 |

**Corrections found along the way**

| # | Issue | Fix |
| --- | --- | --- |
| 16 | OIDC bindings used GitHub's name-only subject; this repo issues immutable subjects with owner and repo IDs | Rebound both service accounts (ADR-013) |
| 17 | ADR-012 said the name tag binds only inside the project | It binds across the org; corrected ADR-012 and DESIGN.md |
| 18 | CICD.md listed every repo setting as unapplied after ADR-016 applied several | Split into applied and proposed tables |
| 19 | ADR-013 waited for a key ring that ADR-014 had created | Updated the state-bucket CMEK note |
| 20 | DESIGN.md had no resource hierarchy, and its repo layout omitted `docs/` and `.github/` | Added both |
| 21 | The spec had no field for the Cloud Identity customer ID or the project prefix, both required by FAST `defaults.yaml` | Added to `extensions.gcp` (ADR-020) |
| 22 | The `classic` dataset has only development and production, but the spec allows `stage` | Overlay adds a `staging` tag value and stage folders (ADR-020) |
| 23 | DESIGN.md said the `minimal` dataset is TBD; v59.0.0 also ships `starter-gcd`, which we haven't evaluated | Noted; Starter stays `classic` trimmed to one environment |
| 24 | A pattern ending in `$` also matches before a trailing newline in Python, unlike ECMA-262 | Reject control characters in every spec string before rendering |
| 25 | README and CONTRIBUTING still said "design stage" and that `lzctl` didn't exist; the README counted 18 ADRs, not 20 | Updated both; added a Try it section and development notes |
| 26 | DESIGN.md's skill tree showed `templates/<cloud>/` and in-package `evals/`, and said the spec schema is generated | Tree now matches ADR-020 and the repo's `evals/`; the schema is described as handwritten for now |
