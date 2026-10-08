# GCP baseline

**Baseline:** Cloud Foundation Fabric FAST, pinned by release tag (`v59.0.0`). Hierarchy: organization, folders, projects. Rendering of FAST YAML datasets is not implemented yet; this file covers what the spec accepts.

## Profile mapping

| Profile | FAST dataset |
| --- | --- |
| `starter` | `classic`, trimmed to one environment |
| `standard` | `classic` |
| `regulated` | `hardened` plus `1-vpcsc` and `2-security`. Its detective controls need SCC Premium or Enterprise |

## `extensions.gcp`

| Field | Values | Meaning |
| --- | --- | --- |
| `hub_connectivity` | `peering`, `ncc`, `nva`, `vpn` | How spokes connect to the hub in `2-networking`. Only meaningful with `network.topology: hub_spoke` |
| `audit_sink` | `bigquery`, `gcs`, `both` | Where organization log sinks write |

## GCP notes

- `security.service_perimeter: true` means a VPC Service Controls perimeter; it is available on GCP only.
- `organization.id` is the numeric organization ID, and `billing_ref` is the billing account ID (`XXXXXX-XXXXXX-XXXXXX`).
- Group emails in `iam.groups` must exist in Cloud Identity before the landing zone is applied.
