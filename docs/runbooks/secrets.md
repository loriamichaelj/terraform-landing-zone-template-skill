# Runbook: Secrets (Secret Manager with KMS, and GitHub environment secrets)

How secrets are stored for this repo, set up on 2026-10-07. Decision record: [ADR-014](../ADR.md#adr-014-secrets-in-secret-manager-encrypted-with-our-kms-key-github-environment-secrets-only-for-ci).

## Where a secret goes

| Secret is needed by | Store it in | Why |
| --- | --- | --- |
| The running agent or anything deployed in GCP (for example the GitHub App private key) | **Secret Manager**, encrypted with our KMS key | Read at runtime by a service account; audited; never copied into CI |
| A GitHub Actions job, for something outside GCP (for example a third-party API token used only in CI) | **GitHub environment secret** on `dev` (or `bootstrap`) | Only jobs that declare that environment can read it |
| GCP credentials for CI | **Nowhere.** CI uses OIDC (see the [state and OIDC runbook](gcp-state-bucket-and-github-oidc.md)) | No long-lived keys to leak |

KMS holds encryption keys, not secrets. It protects what Secret Manager stores, the same way AWS KMS protects AWS Secrets Manager.

## What exists

| Resource | Value | Tagged |
| --- | --- | --- |
| KMS key ring | `projects/skills-mjl-27850/locations/us-central1/keyRings/tlz` (cannot be deleted, ever) | Yes |
| KMS key | `.../keyRings/tlz/cryptoKeys/secret-manager`, software protection, rotates every 90 days | Not supported; inherits from the key ring |
| Secret Manager service agent | `service-853750160087@gcp-sa-secretmanager.iam.gserviceaccount.com`, can encrypt and decrypt with the key | n/a |
| Access for `lz-dev-sa` | Secret Accessor on secrets whose names start with `dev-` | n/a |
| Access for `lz-bootstrap-sa` | Secret Accessor on secrets whose names start with `bootstrap-` | n/a |

The naming prefix is the access boundary: a secret named `dev-foo` is readable from the GitHub `dev` environment, `bootstrap-foo` from `bootstrap`, and anything else from neither.

## Add a secret to Secret Manager

CMEK is not applied automatically. Every secret must be created with the replication and key flags below, or it falls back to Google-managed encryption.

```bash
P=skills-mjl-27850
KEY=projects/$P/locations/us-central1/keyRings/tlz/cryptoKeys/secret-manager
T=skills-mjl-27850/name/Terraform-Landing-Zone-Template-Skill

gcloud secrets create dev-example --project=$P \
  --replication-policy=user-managed --locations=us-central1 --kms-key-name=$KEY \
  --tags=$T

# Add the value from a file or stdin, never as a command-line argument (it would land in shell history)
gcloud secrets versions add dev-example --project=$P --data-file=path/to/value
# or: pbpaste | gcloud secrets versions add dev-example --project=$P --data-file=-
```

If `--tags` is rejected by your gcloud version, bind the tag afterwards:

```bash
gcloud resource-manager tags bindings create --tag-value=$T \
  --parent=//secretmanager.googleapis.com/projects/853750160087/secrets/dev-example
```

Read it in a workflow job that runs in the `dev` environment (after `google-github-actions/auth`):

```bash
gcloud secrets versions access latest --secret=dev-example --project=skills-mjl-27850
```

## Add a GitHub environment secret

```bash
gh secret set EXAMPLE_TOKEN --env dev --repo loriamichaelj/terraform-landing-zone-template-skill
# gh prompts for the value, so it never appears in shell history
```

Use it in a job that declares `environment: dev` as `${{ secrets.EXAMPLE_TOKEN }}`.

## Verify

```bash
gcloud kms keys get-iam-policy secret-manager --keyring=tlz --location=us-central1 --project=skills-mjl-27850
gcloud projects get-iam-policy skills-mjl-27850 --flatten='bindings[].members' \
  --filter='bindings.role:secretmanager' --format='table(bindings.members,bindings.condition.expression)'
gcloud secrets describe dev-example --project=skills-mjl-27850 --format='yaml(replication)'  # shows customerManagedEncryption
gh secret list --env dev --repo loriamichaelj/terraform-landing-zone-template-skill
```
