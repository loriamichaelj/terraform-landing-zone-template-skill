# CI/CD Strategy: Terraform Landing Zone Agent

Oct 7, 2026 · Status: **Proposed** ([ADR-015](ADR.md#adr-015-cicd-strategy-and-workflow-naming)) · Built so far: the OIDC check workflow (passing in `dev` and `bootstrap`)

This covers how code in this repo is tested, released and deployed: branches, environments, the workflow inventory, naming conventions and the actions policy. It's the detail behind the Pipeline section of [DESIGN.md](DESIGN.md).

## Principles

1. **No long-lived cloud credentials.** Every GCP call from CI uses OIDC through Workload Identity Federation ([ADR-013](ADR.md#adr-013-github-oidc-through-workload-identity-federation-one-service-account-per-environment)). No service account keys exist.
2. **One identity per environment.** A job gets cloud access only by declaring a GitHub environment, and each environment can impersonate only its own service account.
3. **Plan on pull request, apply on merge.** Nothing changes in GCP from an unmerged branch.
4. **Build once, promote the same artifact.** Images and skill packages are built once, signed, and promoted by digest, never rebuilt per environment.
5. **Least privilege by default.** Workflows start with `permissions: {}`, and each job asks only for what it needs.
6. **Pinned and reproducible.** Actions are pinned to a commit SHA, and tool versions (Terraform, tflint, trivy, conftest) are pinned in the workflow.
7. **Same checks locally and in CI.** CI calls `lzctl check` and `make` targets rather than duplicating logic in YAML, so a developer can reproduce any failure.

## Branches

| Branch | Role | Deploys to |
| --- | --- | --- |
| `dev` (default) | Integration branch; every change lands here by pull request with a code-owner approval, enforced by the **dev: pull requests only** ruleset (only the repo admin can bypass, [ADR-018](ADR.md#adr-018-dev-accepts-changes-only-by-pull-request-except-the-owner)) | `dev` environment, on merge |
| `feature/*`, `fix/*`, `docs/*`, `ci/*` | Short-lived work branches | Nothing; plan-only |
| `main` (later) | Release branch, created when a production environment exists | `prod`, by promotion |

Until `main` exists, `dev` is both trunk and the only deploy target. Promotion to production will be a pull request from `dev` to `main` (or a signed tag), deploying the same image digest that passed in `dev`.

## Environments

| GitHub environment | Service account | Purpose | Trigger | Protection (proposed) |
| --- | --- | --- | --- | --- |
| `bootstrap` | `lz-bootstrap-sa` | Foundational infra for the agent's own platform: APIs, KMS, Artifact Registry, networking | Manual dispatch only | Required reviewer; deploy from `dev` only |
| `dev` | `lz-dev-sa` | The agent platform's dev deployment (`infra/`, Cloud Run, evals) | Push to `dev`; manual dispatch | Deploy from `dev` only |
| `dev-plan` (later) | `lz-dev-plan-sa`, read-only | Terraform plan on pull requests | Pull request | None; read-only identity |
| `prod` (later) | `lz-prod-sa` | Production | Promotion from `main` | Required reviewers, wait timer, `main` only |

**GCP placement:** `bootstrap` and `dev` both run in project `skills-mjl-27850`, which sits in the `dev` folder. The `stage` and `prod` folders exist (tagged `environment:stage` and `environment:prod`) but stay empty until those environments are needed ([ADR-017](ADR.md#adr-017-environment-folders-and-the-environment-tag)).

**Why `dev-plan` is needed later:** once `dev` is restricted to deploy from the `dev` branch only, pull-request jobs can't use it, but they still need to read state to plan. A separate read-only identity keeps planning possible without giving unmerged code write access. This mirrors FAST's read-only/read-write split for CI service accounts.

## Workflow inventory

| File | Display name | Category | Trigger | Environment | Phase | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `ops-oidc-check.yml` | Ops: OIDC check | ops | Manual; push to the file | `dev` or `bootstrap` | Now | **Built, passing** |
| `ci-docs.yml` | CI: Docs | ci | Pull request touching `**.md` | none | Now | Planned |
| `ci-workflows.yml` | CI: Workflows | ci | Pull request touching `.github/**` | none | Now | Planned |
| `ci-terraform.yml` | CI: Terraform | ci | Pull request touching `infra/**` | `dev-plan` | P0 | Planned |
| `ci-skill.yml` | CI: Skill | ci | Pull request touching `.agents/skills/**` | none | P0 | Planned |
| `ci-evals.yml` | CI: Evals smoke | ci | Pull request touching skill, agent or templates | `dev` | P0 | Planned |
| `ops-evals-full.yml` | Ops: Evals full suite | ops | Weekly schedule; manual | `dev` | P0 | Planned |
| `cd-infra-bootstrap.yml` | CD: Infra (bootstrap) | cd | Manual | `bootstrap` | P1 | Planned |
| `cd-infra-dev.yml` | CD: Infra (dev) | cd | Push to `dev` touching `infra/**` | `dev` | P1 | Planned |
| `cd-agent-dev.yml` | CD: Agent (dev) | cd | Push to `dev` touching `agent/**`, `validator/**` | `dev` | P1 | Planned |
| `release-skill.yml` | Release: Skill | release | Tag `skill-v*` | none | P1 | Planned |
| `reusable-terraform.yml` | Reusable: Terraform | reusable | `workflow_call` | caller's | P0 | Planned |
| `reusable-gcp-auth.yml` | Reusable: GCP auth | reusable | `workflow_call` | caller's | P0 | Planned |

**What each check runs**

- **CI: Docs:** markdown lint, link check, and the repo's content rules.
- **CI: Workflows:** actionlint, zizmor (workflow security audit) and the SHA-pinning check.
- **CI: Terraform:** `terraform fmt -check`, `validate`, tflint, trivy, conftest (including the ADR-012 tag rule), then `plan`, posted as a PR comment.
- **CI: Skill:** `pip install -r tests/requirements.txt && python -m pytest tests`: `lzctl` unit tests, golden render hashes (byte-identical output), rendered YAML checked against FAST's factory schemas, `lzctl check` on every golden render, and the vendored-upstream manifest check. Run it on Python 3.11 and 3.13, because output must not depend on the interpreter.
- **CI: Evals smoke:** the 8-scenario subset from DESIGN.md. **Ops: Evals full** runs all 25 scenarios x 4 clouds weekly, about $65 per run.

## Naming conventions

### Workflow files

`<category>-<subject>[-<environment>].yml`, lowercase kebab-case.

| Category | Meaning | Can touch cloud resources? |
| --- | --- | --- |
| `ci-` | Checks on pull requests and pushes; no deployment | Read-only at most |
| `cd-` | Deploys to one environment | Yes, that environment only |
| `ops-` | Manual or scheduled operations: smoke tests, drift checks, full eval runs | As scoped by its environment |
| `release-` | Builds and publishes versioned artifacts | No (publishes to registries) |
| `reusable-` | `workflow_call` only; never triggered directly | Inherits the caller's environment |

Add an `-<environment>` suffix only when the trigger differs by environment (for example, `cd-infra-bootstrap` is manual while `cd-infra-dev` runs on push). Otherwise, pass the environment as an input to one file.

### Inside a workflow

| Item | Convention | Example |
| --- | --- | --- |
| `name:` | `<Category>: <Subject>`, title case for the category | `CD: Infra (dev)` |
| `run-name:` | Subject plus the main input or ref | `OIDC check (dev)` |
| Job IDs | kebab-case verb-noun, stable (they become required status checks) | `allow-environment`, `plan`, `apply` |
| Job `name:` | Short sentence case | `Allow own environment` |
| Step `name:` | Imperative sentence case | `Authenticate to GCP` |
| Concurrency group | `<file-stem>-<environment>` | `cd-infra-dev` |
| Artifact names | `<subject>-<run_id>` | `tfplan-dev-123456` |

Required status checks are named `<workflow name> / <job name>`, so renaming a workflow or job breaks branch protection. Treat both as stable identifiers.

### Variables, secrets and state

| Item | Convention | Example |
| --- | --- | --- |
| Variables and secrets | `UPPER_SNAKE`, prefixed by system | `GCP_SERVICE_ACCOUNT`, `TF_STATE_BUCKET`, `GITHUB_APP_ID` |
| Repo-level variables | Values identical in every environment | `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER` |
| Environment variables | Values that differ by environment | `GCP_SERVICE_ACCOUNT`, `TF_STATE_PREFIX` |
| Secret Manager secrets | `<environment>-<name>` (the prefix is the access boundary, [ADR-014](ADR.md#adr-014-secrets-in-secret-manager-encrypted-with-our-kms-key-github-environment-secrets-only-for-ci)) | `dev-github-app-private-key` |
| Terraform state prefix | `<environment>/<stack>` | `dev/infra`, `bootstrap/foundation` |
| Service accounts | `lz-<environment>[-<role>]-sa` | `lz-dev-sa`, `lz-dev-plan-sa` |

## Actions policy

- **Pin every action to a full commit SHA**, with the version in a trailing comment: `uses: actions/checkout@3d3c42e… # v7.0.1`. Tags can be moved; SHAs can't.
- **Dependabot** updates the pins weekly in one grouped PR against `dev` (`.github/dependabot.yml`).
- **Allowed publishers:** GitHub (`actions/*`), Google (`google-github-actions/*`), HashiCorp (`hashicorp/*`), and named tools as added (`terraform-linters/*`, `aquasecurity/*`). Anything else needs a decision recorded in ADR.md.
- **Runners:** GitHub-hosted, pinned image (`ubuntu-24.04`, not `ubuntu-latest`). Self-hosted runners are out of scope; never use them on a public repo.
- **Permissions:** the repo's default workflow token is read-only (already set). Every workflow declares `permissions: {}` at the top and grants per job.
- **Timeouts:** every job sets `timeout-minutes`.
- **Untrusted input:** never put `${{ github.event.* }}` text (PR titles, branch names) directly into `run:`; pass it through `env:`. Never use `pull_request_target` with a checkout of the PR's code.

| Action | Pinned version |
| --- | --- |
| `actions/checkout` | v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `google-github-actions/auth` | v3.0.0 `7c6bc770dae815cd3e89ee6cdf493a5fab2cc093` |
| `google-github-actions/setup-gcloud` | v3.0.1 `aa5489c8933f4cc7a4f7d45035b3b1440c9c10db` |
| `hashicorp/setup-terraform` | v4.0.1 `dfe3c3f87815947d99a8997f908cb6525fc44e9e` |
| Terraform CLI | 1.16.5 |

## Repository settings

**Applied** (ADR-016, 2026-10-07)

| Setting | Value |
| --- | --- |
| Default workflow token | Read-only |
| Actions can approve PRs | No |
| Workflows on PRs from outside contributors | Need maintainer approval (all external contributors) |
| Merge methods | Squash only; commit title = PR title, message = PR body |
| Delete branch on merge | On |
| Secret scanning and push protection | On |
| Dependabot alerts and security updates | On |
| Private vulnerability reporting | On |
| `dev` ruleset **dev: pull requests only** (ADR-018) | Changes by PR only, 1 approval with code owner review, stale approvals dismissed, conversations resolved, squash only, linear history, no force-push, no deletion. Bypass: Admin role (only `@loriamichaelj`) |

**Proposed, not yet applied**

| Setting | Current | Proposed |
| --- | --- | --- |
| Allowed actions | All | Selected: the publishers above |
| Require SHA pinning | Off | On |
| `dev` required status checks | None | Add CI: Docs and CI: Workflows to the `dev` ruleset once they exist, then Terraform and Skill |
| `bootstrap` environment | No rules | Required reviewer: repo owner; deploy from `dev` only |
| `dev` environment | No rules | Deploy from `dev` only (after `dev-plan` exists) |

## Open questions

- [x] **Branch protection timing:** the `dev` ruleset was added on 2026-10-07, before any CI checks exist; status checks get added to it as workflows land (ADR-018).
- [ ] **`dev-plan` identity:** create it in P0 with `infra/`, or plan with `lz-dev-sa` until the first real deploy?
- [ ] **Production:** when to create `main` and `prod`, and who approves promotions? The GCP `stage` and `prod` folders exist but stay empty until then ([ADR-017](ADR.md#adr-017-environment-folders-and-the-environment-tag)).
- [ ] **Stage:** add a `stage` environment to the pipeline between `dev` and `prod`, or keep promoting straight from `dev`? Decide when the `stage` folder is first populated.
- [ ] **Eval spend:** is $65 per weekly full run (about $280 a month) acceptable for CI, separate from the run cost in DESIGN.md?
