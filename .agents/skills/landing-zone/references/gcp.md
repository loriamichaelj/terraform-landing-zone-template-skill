# GCP baseline

**Baseline:** Cloud Foundation Fabric FAST, pinned by release tag (`v59.0.0`). Hierarchy: organization, folders, projects. `lzctl render` produces the `0-org-setup` dataset and, for hub-and-spoke over peering, the `2-networking` dataset, from the vendored upstream copy plus overlay templates (ADR-020, ADR-024).

## Profile mapping

| Profile | FAST dataset |
| --- | --- |
| `starter` | `classic`, trimmed to one environment |
| `standard` | `classic` |
| `regulated` | `hardened` plus `1-vpcsc` and `2-security`. Its detective controls need SCC Premium or Enterprise |

## `extensions.gcp`

| Field | Values | Meaning |
| --- | --- | --- |
| `customer_id` (required) | 6 to 12 letters and digits | Cloud Identity customer ID, from `gcloud organizations list` |
| `prefix` (required) | 2 to 8 lowercase letters, digits, hyphens | Project name prefix; must be unique |
| `hub_connectivity` | `peering`, `ncc`, `nva`, `vpn` | How spokes connect to the hub in `2-networking`. Only meaningful with `network.topology: hub_spoke` |
| `audit_sink` | `bigquery`, `gcs`, `both` | Where organization log sinks write |

## What `render` produces

| Spec field | Rendered into |
| --- | --- |
| `organization.id`, `billing_ref`, `domain`, `extensions.gcp.customer_id`, `prefix` | `defaults.yaml` |
| `network.regions[0]` | `defaults.yaml` primary location |
| `iam.groups.org_admins` | `defaults.yaml` organization admins principal |
| `hierarchy.environments` | `dev`, `stage`, `prod` folders under networking and security, and the `environment` tag values |
| `hierarchy.business_units` | Folders under `Teams` |
| `logging.retention_days`, `audit_destination` | Audit log buckets in the log project (`analytics` and `both` turn on Log Analytics) |
| `network.topology: hub_spoke` with `hub_connectivity: peering` (the default) | `2-networking`: a hub VPC, and a project and peered spoke VPC per environment |
| `network.regions` | A default /24 subnet and Cloud NAT per region, in every VPC (at most 8 regions; put the primary region first and append new regions at the end) |
| `network.cidr_supernet` | The CIDR plan: four fixed slots (hub, dev, stage, prod), one block per region in each; the range of an existing region or environment never moves |
| `network.private_service_access` | A private service access range (up to a /20) in each spoke |

Everything else is reported in `not_rendered_yet` and is not in the configuration. Do not tell the user it is.

## GCP notes

- `classic` has only development and production. The overlay adds a `staging` tag value and stage folders when `stage` is in the spec.
- `classic` creates an organization tag key named `environment`. If the target organization already has one, import it before applying.
- `security.service_perimeter: true` means a VPC Service Controls perimeter; it is available on GCP only.
- `organization.id` is the numeric organization ID, and `billing_ref` is the billing account ID (`XXXXXX-XXXXXX-XXXXXX`).
- Group emails in `iam.groups` must exist in Cloud Identity before the landing zone is applied.
