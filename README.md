# terraform-landing-zone-template-skill

A portable Agent Skill, plus a hosted ADK agent on Cloud Run, that turns landing zone requirements into a validated Terraform landing zone for GCP, Azure, AWS or OpenStack, delivered as a GitHub pull request.

The agent composes vetted baselines (Cloud Foundation Fabric FAST, Azure Verified Modules, AWS Control Tower with AFT) and fills in their configuration data. It never writes freeform HCL and never runs `terraform apply`.

## Status

**Design stage.** The skill, the `lzctl` CLI and the agent are not built yet. What exists today:

- The design, decision records (ADR-001 to ADR-017), the CI/CD strategy and runbooks in [docs/](docs/)
- GCP plumbing for CI: environment folders, the Terraform state bucket, OIDC trust per GitHub environment, and Secret Manager with a KMS key
- The **Ops: OIDC check** workflow, passing in `dev` and `bootstrap`
- Contributor setup: license, contributing guide, code of conduct, security policy, issue forms and Discussions

## Docs

| Doc | What it covers |
| --- | --- |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture, spec schema, cloud baselines, security, cost estimate, delivery plan |
| [docs/ADR.md](docs/ADR.md) | Architecture decision records and review log |
| [docs/CICD.md](docs/CICD.md) | CI/CD strategy: branches, environments, workflow inventory, naming conventions, actions policy |
| [docs/runbooks/gcp-state-bucket-and-github-oidc.md](docs/runbooks/gcp-state-bucket-and-github-oidc.md) | Terraform state bucket and GitHub Actions OIDC (the GCP equivalent of an AWS OIDC role) |
| [docs/runbooks/secrets.md](docs/runbooks/secrets.md) | Secret Manager with a KMS key, and GitHub environment secrets |

## How it works

1. **Intake:** a conversation fills a landing zone spec (JSON), checked against a schema derived from the baseline.
2. **Render:** `lzctl` turns the spec into configuration data (FAST YAML datasets, tfvars) using templates, with no model in the loop, so the same spec always gives the same output.
3. **Validate:** fmt, validate, tflint, trivy, OPA policy and schema checks run in an isolated job with no network access. Failures map back to spec fields and are fixed in the spec, up to 3 times.
4. **Publish:** after human approval, a pull request opens with the config, a README, the validation report and a decision log.

The same skill runs in Codex, Gemini CLI, Grok Build, DeepSeek-backed hosts and the hosted agent.

## GCP environment

| Item | Value |
| --- | --- |
| Organization | `mikejloria-org` |
| Folders | `dev`, `stage`, `prod` at the org root, tagged `environment:dev` / `stage` / `prod` |
| Project | `skills-mjl-27850`, in the `dev` folder, tagged `environment:dev` |
| Region | `us-central1` |
| Terraform state | `gs://skills-mjl-27850-tlz-tfstate`, one prefix per environment |
| OIDC provider | `projects/853750160087/locations/global/workloadIdentityPools/github/providers/github-actions` |
| CI service accounts | `lz-bootstrap-sa`, `lz-dev-sa` (one per GitHub environment) |
| Secrets | Secret Manager, encrypted with KMS key `tlz/secret-manager`; names prefixed `bootstrap-` or `dev-` |

## GitHub environments

| Environment | Service account | Can read secrets named |
| --- | --- | --- |
| `bootstrap` | `lz-bootstrap-sa` | `bootstrap-*` |
| `dev` | `lz-dev-sa` | `dev-*` |

Each environment has the variables `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `TF_STATE_BUCKET` and `TF_STATE_PREFIX`. A job must declare `environment:` to authenticate to GCP. No GCP keys are stored in GitHub.

To check the OIDC setup, run **Ops: OIDC check** (`.github/workflows/ops-oidc-check.yml`) from the Actions tab, or `gh workflow run ops-oidc-check.yml -f environment=dev`.

## Conventions

- **Resource tags:** every resource this repo creates is bound to `skills-mjl-27850/name/Terraform-Landing-Zone-Template-Skill` ([ADR-012](docs/ADR.md#adr-012-tag-every-resource-this-repo-creates)). Environment folders and projects also carry the org-level `environment` tag ([ADR-017](docs/ADR.md#adr-017-environment-folders-and-the-environment-tag)).
- **Decisions:** record every design decision and its context in [docs/ADR.md](docs/ADR.md).
- **Branching:** `dev` is the default branch. Pull requests are squash-merged, and the PR title becomes the commit message.

## Contributing

Contributions are welcome, especially design review and cloud expertise while the project is in the design stage. Read [CONTRIBUTING.md](CONTRIBUTING.md) to get started, and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

- Questions and ideas: [Discussions](https://github.com/loriamichaelj/terraform-landing-zone-template-skill/discussions)
- Bugs, features and design proposals: [Issues](https://github.com/loriamichaelj/terraform-landing-zone-template-skill/issues/new/choose)
- Security problems: report privately, as described in [SECURITY.md](SECURITY.md)
- Getting help: [SUPPORT.md](SUPPORT.md)

## License

[Apache License 2.0](LICENSE)
