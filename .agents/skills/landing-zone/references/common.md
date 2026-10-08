# Spec fields, profiles and rules

The schema in `schemas/lz-spec.core.schema.json` is the source of truth. This file explains it.

## Fields

| Field | Required | Notes |
| --- | --- | --- |
| `spec_version` | yes | Always `"2.0"` |
| `target.cloud` | yes | `gcp` today; `azure`, `aws`, `openstack` later |
| `target.profile` | yes | `starter`, `standard`, `regulated` |
| `target.baseline_version` | yes | Pinned upstream release, for GCP `v59.0.0` |
| `organization.id` | yes | Cloud organization ID, tenant or account root |
| `organization.billing_ref` | yes | Billing account or equivalent |
| `organization.domain` | yes | Primary DNS domain, such as `example.com` |
| `hierarchy.environments` | yes | Subset of `dev`, `stage`, `prod`, no duplicates |
| `hierarchy.business_units` | no | Lowercase names, 3 to 30 characters, hyphens allowed |
| `network.topology` | yes | `single` or `hub_spoke` |
| `network.regions` | yes | At least one, no duplicates |
| `network.cidr_supernet` | yes | Private IPv4, a `/16` or larger, network address only (`10.0.0.0/8`, not `10.0.0.1/8`) |
| `network.private_service_access` | no | Boolean |
| `security.service_perimeter` | yes | `true` only on GCP |
| `security.customer_managed_keys` | yes | Boolean |
| `security.compliance` | no | Any of `soc2`, `pci`, `hipaa` |
| `logging.audit_destination` | yes | `analytics`, `archive` or `both` |
| `logging.retention_days` | yes | 30 to 3650 |
| `iam.groups.org_admins`, `network_admins`, `security_admins` | yes | Group email addresses |
| `extensions.<cloud>` | no | Only the block for `target.cloud` |
| `decisions[]` | no | `field`, `value`, `rationale`, `source` |

Unknown fields are rejected. Do not invent inputs.

## Profiles

| Profile | Environments | Retention | Keys | Other rules |
| --- | --- | --- | --- | --- |
| `starter` | exactly one | any (30+) | any | Sandbox or proof of concept |
| `standard` | one to three | 365+ days | any | Default. With `hub_spoke`, needs two or more environments |
| `regulated` | one to three | 400+ days | `customer_managed_keys` must be `true` | With `hub_spoke`, needs two or more environments. Pair with `soc2`, `pci` or `hipaa` in `compliance` |

## Reading findings

`lzctl spec validate` prints JSON: `{"valid": bool, "findings": [{"rule", "path", "message"}]}`. `path` is the dotted spec field to change, for example `logging.retention_days`. Rule prefixes: `schema.*` (shape and limits) and `semantic.*` (checks a schema can't express, such as CIDR sanity).

Exit codes: 0 valid, 1 findings, 2 usage or file error.
