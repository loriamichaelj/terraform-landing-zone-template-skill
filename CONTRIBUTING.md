# Contributing

Thanks for your interest in the Terraform Landing Zone Template Skill. This guide covers how to propose changes, how work is reviewed, and the conventions the project follows.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Project status

The project is early in **P0** (core and GCP). The repo holds the design ([docs/DESIGN.md](docs/DESIGN.md)), decision records ([docs/ADR.md](docs/ADR.md)), the CI/CD strategy ([docs/CICD.md](docs/CICD.md)), the CI plumbing, and the first slice of the skill: spec schemas, `lzctl spec validate` and `render` for the GCP `0-org-setup` dataset, and tests. `lzctl check`, the networking and security datasets, the hosted agent and the other clouds aren't written yet.

The most useful contributions right now:

- **Design review:** challenge assumptions in DESIGN.md, especially the spec schema, the capability mapping and the security model.
- **Cloud expertise:** corrections to the Azure (AVM ALZ), AWS (Control Tower, AFT) and OpenStack sections, and real-world gotchas for `references/<cloud>.md`.
- **Answers to open questions:** each doc ends with a list of open questions.
- **Docs:** fixes, clarity, broken links.

## Where things go

| You want to | Use |
| --- | --- |
| Ask a question or float an idea | [Discussions](https://github.com/loriamichaelj/terraform-landing-zone-template-skill/discussions) (Q&A or Ideas) |
| Report a bug | An issue, using the **Bug report** form |
| Propose a feature | An issue, using the **Feature request** form |
| Propose a design change | An issue, using the **Design proposal** form, then a PR that adds an ADR |
| Report a vulnerability | **Privately**, as described in [SECURITY.md](SECURITY.md). Never in a public issue |

For anything bigger than a typo, open or comment on an issue before writing the change, so we can agree on the approach first.

## Making a change

1. **Fork** the repo (or create a branch if you have write access).
2. **Branch** from `dev` with a prefix: `feature/…`, `fix/…`, `docs/…` or `ci/…`.
3. **Make the change.** Keep a PR to one logical change.
4. **Open a pull request against `dev`** and fill in the template.
5. **Review:** every PR needs one approving review from a code owner, and all review conversations resolved, before it can merge. Pushing new commits dismisses earlier approvals. Expect questions; they're about the change, not about you.
6. **Merge:** PRs are squash-merged, and the branch is deleted automatically.

### PR titles and commits

PRs are squash-merged, so **the PR title becomes the commit message** on `dev`. Use the [Conventional Commits](https://www.conventionalcommits.org/) style:

```
<type>(<optional scope>): <summary in the imperative>
```

| Type | For |
| --- | --- |
| `feat` | New capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `ci` | Workflows and repo automation |
| `refactor` | Code change with no behavior change |
| `test` | Tests or eval scenarios |
| `chore` | Maintenance (dependency bumps, tooling) |

Examples: `docs(design): clarify AWS SCP mapping`, `ci: add markdown link check`, `feat(skill): render FAST networking dataset`.

### Design changes and ADRs

Anything that changes the architecture, a security control, a baseline choice or a convention needs an **Architecture Decision Record** in [docs/ADR.md](docs/ADR.md):

- Add a new ADR with the next number, status **Proposed**, and sections for **Context**, **Decision** and **Consequences**.
- Never rewrite an accepted ADR. To change a decision, add a new ADR that supersedes it, and update the old one's status.
- Update DESIGN.md (or CICD.md) in the same PR, so the docs and the decision match.

## Conventions

- **Workflows** follow the naming and actions policy in [docs/CICD.md](docs/CICD.md). In short: `<category>-<subject>.yml`, actions pinned to a full commit SHA with the version in a comment, `permissions: {}` at the top, and a timeout on every job. Run [actionlint](https://github.com/rhysd/actionlint) before pushing workflow changes.
- **Generated landing zones** come only from templates; the project never generates freeform HCL (ADR-001).
- **Cloud resources** created by this repo's own infrastructure carry the tag `skills-mjl-27850/name/Terraform-Landing-Zone-Template-Skill` (ADR-012).
- **Secrets** never go in the repo, issues, PRs or Discussions. Specs and examples often contain org IDs, billing accounts, CIDR plans and group emails: **redact them** before posting.

## Development setup

Contributions are Markdown, workflow YAML, and now the skill and `lzctl`. Useful tools:

- Python 3.11+ for `lzctl` and the tests: `pip install -r tests/requirements.txt`, then `python -m pytest tests`
- [actionlint](https://github.com/rhysd/actionlint) for workflow changes
- A Markdown previewer that renders Mermaid (for the architecture diagram)

`lzctl doctor` checks the runtime dependencies. Terraform 1.16 (or OpenTofu), tflint, trivy, checkov and conftest are optional today and become required as `lzctl check` gains work for them: `check` runs `terraform fmt` when it is installed, and runs trivy and checkov on rendered `.tf` files once there are any, and reports the others `not_applicable` until HCL and policies are rendered.

**Changing the skill:**

- **Output changes need a golden update.** Rendering must stay byte-identical for a given spec. If a template or schema change alters the output, review the diff, then run `UPDATE_GOLDEN=1 python -m pytest tests` and commit `evals/gcp/golden/render-hashes.json` with the change.
- **Never edit `templates/gcp/fast-*/upstream/`.** It is a verbatim copy of the pinned FAST release, checked against `MANIFEST.json`. Change the overlay templates, or re-vendor with `tools/vendor_fast.py` for a baseline bump (ADR-020).
- **Every value that reaches a template must be pattern-restricted** in the schema, so a spec can't inject YAML.

## CI on pull requests from forks

- **Approval:** workflows on PRs from outside contributors run only after a maintainer approves them.
- **No cloud access:** fork PRs never receive GCP credentials, because the OIDC trust only accepts jobs running in this repo's own environments. Checks that need GCP are run by a maintainer after review.

## Licensing

The project is licensed under [Apache-2.0](LICENSE). Under section 5 of the license, any contribution you submit is licensed under the same terms; there's no separate contributor agreement.

## Maintainers

- [@loriamichaelj](https://github.com/loriamichaelj), code owner for the whole repo (see [.github/CODEOWNERS](.github/CODEOWNERS)).
