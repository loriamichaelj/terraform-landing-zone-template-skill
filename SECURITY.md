# Security Policy

## Reporting a vulnerability

**Please don't report security issues in public issues, pull requests or Discussions.**

Report them privately through GitHub: go to the [Security tab](https://github.com/loriamichaelj/terraform-landing-zone-template-skill/security) and choose **Report a vulnerability**, or open a [new private report](https://github.com/loriamichaelj/terraform-landing-zone-template-skill/security/advisories/new) directly. Only maintainers can see it.

Please include:

- What the issue is and where it is (file, workflow, template or doc)
- How to reproduce it, or a proof of concept
- The impact you expect (for example, what an attacker could reach)
- Any suggested fix

## What to expect

This is a volunteer-maintained project, so these are targets rather than guarantees:

| Step | Target |
| --- | --- |
| Acknowledge your report | Within 5 business days |
| Initial assessment | Within 10 business days |
| Fix or mitigation for confirmed issues | Depends on severity; we'll keep you updated in the report |

We'll coordinate disclosure with you, publish a GitHub security advisory for confirmed issues, and credit you unless you prefer otherwise.

## Supported versions

The project is pre-release. Only the latest commit on the `dev` branch is supported. Once releases exist, this section will list the supported versions.

## Scope

**In scope**

- GitHub Actions workflows in this repo: injection, over-broad permissions, or ways to obtain the repo's GCP credentials (OIDC trust)
- The skill, `lzctl`, templates and policies, including output that would silently weaken a landing zone's guardrails (for example, dropping an org policy or opening a network path the spec didn't ask for)
- The hosted agent's design and infrastructure: prompt injection paths that bypass the validation or approval gates, identity and isolation gaps
- Secrets or sensitive data committed to the repo

**Out of scope**

- Vulnerabilities in upstream projects (Cloud Foundation Fabric, Azure Verified Modules, AWS AFT, Terraform providers, GitHub Actions we use). Please report those upstream.
- Resource identifiers published in the docs, such as the GCP project ID, project number, service account emails or the workload identity provider path. These are identifiers, not credentials; access is controlled by IAM.
- Findings that require a compromised maintainer account or social engineering.

## Security features in use

- GitHub private vulnerability reporting, Dependabot alerts and security updates, secret scanning and push protection
- OIDC (Workload Identity Federation) for CI, with no long-lived cloud keys; each GitHub environment can use only its own service account
- Actions pinned to commit SHAs, and approval required before workflows run on pull requests from outside contributors
