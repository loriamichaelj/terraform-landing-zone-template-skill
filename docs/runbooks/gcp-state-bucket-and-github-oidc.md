# Runbook: Terraform state bucket and GitHub OIDC on GCP

How the Terraform state bucket and the GitHub Actions OIDC trust in project `skills-mjl-27850` were created on 2026-10-07, and how to recreate or extend them by hand. Decision record: [ADR-013](../ADR.md#adr-013-github-oidc-through-workload-identity-federation-one-service-account-per-environment).

## AWS to GCP mapping

| AWS | GCP equivalent | What we created |
| --- | --- | --- |
| IAM OIDC identity provider for `token.actions.githubusercontent.com` | Workload identity pool + OIDC provider | Pool `github`, provider `github-actions` |
| Provider-wide audience/thumbprint checks | Provider attribute condition | `assertion.repository_owner_id == '165821667'` (account `loriamichaelj`) |
| IAM role | Service account | `lz-bootstrap-sa`, `lz-dev-sa` |
| Role trust policy with `token.actions.githubusercontent.com:sub` condition | `roles/iam.workloadIdentityUser` on the service account, granted to one `subject` | `repo:loriamichaelj@165821667/terraform-landing-zone-template-skill@1409542604:environment:<env>` |
| Permissions policy on the role | IAM roles granted to the service account | `roles/storage.objectUser` on the state bucket |
| `aws-actions/configure-aws-credentials` with `role-to-assume` | `google-github-actions/auth` with `workload_identity_provider` + `service_account` | GitHub environment variables (below) |

## What exists

| Resource | Value | Tagged |
| --- | --- | --- |
| State bucket | `gs://skills-mjl-27850-tlz-tfstate` (us-central1, versioning on, uniform access, public access prevention enforced, noncurrent versions kept up to 10 copies or 90 days) | Yes |
| Workload identity pool | `projects/853750160087/locations/global/workloadIdentityPools/github` | Not supported (global resource) |
| OIDC provider | `.../workloadIdentityPools/github/providers/github-actions` | Not supported |
| Service account | `lz-bootstrap-sa@skills-mjl-27850.iam.gserviceaccount.com` (environment `bootstrap`) | Yes |
| Service account | `lz-dev-sa@skills-mjl-27850.iam.gserviceaccount.com` (environment `dev`) | Yes |
| GitHub environments | `bootstrap`, `dev` | n/a |

Each GitHub environment has these variables: `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `TF_STATE_BUCKET`, `TF_STATE_PREFIX` (`bootstrap` or `dev`).

## The subject claim

This repo uses GitHub's **immutable subject** format, which puts the owner and repo IDs in `sub`:

```
repo:loriamichaelj@165821667/terraform-landing-zone-template-skill@1409542604:environment:dev
```

A binding to the older name-only format (`repo:loriamichaelj/terraform-landing-zone-template-skill:environment:dev`) never matches, and the job fails with `Permission 'iam.serviceAccounts.getAccessToken' denied`. Check the format GitHub uses with:

```bash
gh api repos/loriamichaelj/terraform-landing-zone-template-skill/actions/oidc/customization/sub
# {"use_default":true,"use_immutable_subject":true,"sub_claim_prefix":"repo:loriamichaelj@165821667/terraform-landing-zone-template-skill@1409542604"}
```

Because the IDs never change, renaming the repo or account, or someone recreating it under the same name, can't take over the trust. The **Ops: OIDC check** workflow prints the live claims in its first step.

## Recreate by hand

Run in bash. In zsh, write `${REPO}` (with braces) wherever a colon follows a variable: zsh reads `$REPO:e…` as a history modifier and silently mangles the value.

```bash
P=skills-mjl-27850
N=$(gcloud projects describe $P --format='value(projectNumber)')
B=skills-mjl-27850-tlz-tfstate
L=us-central1
REPO=loriamichaelj/terraform-landing-zone-template-skill
OWNER_ID=$(gh api repos/${REPO} --jq .owner.id)
SUB_PREFIX=$(gh api repos/${REPO}/actions/oidc/customization/sub --jq .sub_claim_prefix)
TAG=skills-mjl-27850/name/Terraform-Landing-Zone-Template-Skill

# 1. APIs
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  cloudresourcemanager.googleapis.com --project=$P

# 2. State bucket (versioning must be a separate update in current gcloud), then the tag
gcloud storage buckets create gs://${B} --project=$P --location=$L \
  --uniform-bucket-level-access --public-access-prevention --lifecycle-file=lifecycle.json
gcloud storage buckets update gs://${B} --versioning
gcloud resource-manager tags bindings create --tag-value=${TAG} \
  --parent=//storage.googleapis.com/projects/_/buckets/${B} --location=$L

# 3. OIDC trust (the "identity provider")
gcloud iam workload-identity-pools create github --project=$P --location=global \
  --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github-actions --project=$P \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository_owner_id == '${OWNER_ID}'"

# 4. One "role" per environment
for e in bootstrap dev; do
  SA="lz-${e}-sa@${P}.iam.gserviceaccount.com"
  gcloud iam service-accounts create "lz-${e}-sa" --project=$P --display-name="TLZ GitHub ${e}"
  # New service accounts take a few seconds to propagate; retry the next commands if they say "does not exist"
  gcloud iam service-accounts add-iam-policy-binding "$SA" --role=roles/iam.workloadIdentityUser \
    --member="principal://iam.googleapis.com/projects/${N}/locations/global/workloadIdentityPools/github/subject/${SUB_PREFIX}:environment:${e}"
  gcloud storage buckets add-iam-policy-binding gs://${B} --member="serviceAccount:${SA}" \
    --role=roles/storage.objectUser
  UID_=$(gcloud iam service-accounts describe "$SA" --format='value(uniqueId)')
  gcloud resource-manager tags bindings create --tag-value=${TAG} \
    --parent=//iam.googleapis.com/projects/${P}/serviceAccounts/${UID_}
done

# 5. GitHub environments and variables
for e in bootstrap dev; do
  gh api -X PUT repos/${REPO}/environments/${e}
  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --env $e --repo $REPO \
    --body "projects/${N}/locations/global/workloadIdentityPools/github/providers/github-actions"
  gh variable set GCP_SERVICE_ACCOUNT --env $e --repo $REPO --body "lz-${e}-sa@${P}.iam.gserviceaccount.com"
  gh variable set TF_STATE_BUCKET --env $e --repo $REPO --body "$B"
  gh variable set TF_STATE_PREFIX --env $e --repo $REPO --body "$e"
done
```

`lifecycle.json`:

```json
{"rule":[
 {"action":{"type":"Delete"},"condition":{"isLive":false,"numNewerVersions":10}},
 {"action":{"type":"Delete"},"condition":{"isLive":false,"daysSinceNoncurrentTime":90}}
]}
```

Console path, if you prefer clicking: IAM & Admin → Workload Identity Federation → Create pool → add provider (OpenID Connect, issuer above, same attribute mapping and condition). Then IAM & Admin → Service Accounts → select the account → Principals with access → Grant access, with the `principal://…/subject/…` string as the principal and the role Workload Identity User.

## Using it in a workflow

The job must name the environment, because the token's `sub` claim (and therefore which service account it can use) comes from the environment.

```yaml
permissions:
  contents: read
  id-token: write

jobs:
  plan:
    runs-on: ubuntu-latest
    environment: dev
    steps:
      - uses: actions/checkout@v7
      - uses: google-github-actions/auth@v3
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}
      - uses: hashicorp/setup-terraform@v4
      - run: |
          terraform init \
            -backend-config="bucket=${{ vars.TF_STATE_BUCKET }}" \
            -backend-config="prefix=${{ vars.TF_STATE_PREFIX }}"
```

Backend block in Terraform:

```hcl
terraform {
  backend "gcs" {} # bucket and prefix supplied by -backend-config
}
```

## Extending

- **Another environment** (such as `prod`): repeat step 4 and step 5 with the new name. Add required reviewers to the GitHub environment before giving its service account any write access to real infrastructure.
- **More permissions:** grant roles to the environment's service account, scoped to the narrowest resource that works. Today both accounts can only read and write objects in the state bucket.
- **Tighter state isolation:** both accounts can currently read every prefix in the bucket. If dev must not read bootstrap state, move to one bucket per environment.

## Verify

```bash
gcloud iam service-accounts get-iam-policy lz-dev-sa@skills-mjl-27850.iam.gserviceaccount.com
gcloud storage buckets describe gs://skills-mjl-27850-tlz-tfstate \
  --format='yaml(versioning_enabled,public_access_prevention,uniform_bucket_level_access)'
gcloud resource-manager tags bindings list \
  --parent=//storage.googleapis.com/projects/_/buckets/skills-mjl-27850-tlz-tfstate --location=us-central1
```

End to end, run **Ops: OIDC check** (`gh workflow run ops-oidc-check.yml -f environment=dev`, or `bootstrap`). It passes only if all three jobs pass:

- The job in the chosen environment authenticates, writes and reads the bucket, and runs Terraform init and apply on the GCS backend.
- A job with no environment is refused.
- A job asking for the other environment's service account is refused.

Both environments passed on 2026-10-07.
