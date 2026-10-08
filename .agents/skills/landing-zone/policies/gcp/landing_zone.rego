# Policy pack for a rendered GCP landing zone (ADR-028).
#
# `lzctl check` runs it with `conftest test --combine --parser yaml`, so `input` is a list of
# {"path": ..., "contents": ...}, one entry per YAML file. Each deny carries a stable `rule` id and
# the `path` of the file at fault, which `lzctl` turns into a finding.
#
# These rules back up the vendored baseline and the overlay templates: they fail the render if a
# baseline bump or a spec value weakens a guardrail, overlaps the CIDR plan or opens a firewall.
package main

import rego.v1

org_policy_prefix := "datasets/landing-zone/organization/org-policies/"

# Constraints a landing zone must keep enforced. A rule that enforces one without a condition counts.
required_enforced := {
	"compute.requireOsLogin",
	"compute.skipDefaultNetworkCreation",
	"compute.disableSerialPortAccess",
	"iam.disableServiceAccountKeyCreation",
	"iam.disableServiceAccountKeyUpload",
	"sql.restrictPublicIp",
	"storage.publicAccessPrevention",
	"storage.uniformBucketLevelAccess",
	"storage.secureHttpTransport",
}

# Every audit log bucket keeps logs at least this long (days).
min_retention_days := 30

private_ranges := {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}

# --- helpers ------------------------------------------------------------------

files contains f if {
	some f in input
	is_object(f.contents)
}

is_dataset(path, kind) if contains(path, concat("", ["/", kind, "/"]))

# The org policy files, keyed by constraint name.
org_policies[name] := {"path": f.path, "rules": object.get(f.contents[name], "rules", [])} if {
	some f in files
	startswith(f.path, org_policy_prefix)
	some name, _ in f.contents
}

enforced_unconditionally(rules) if {
	some r in rules
	r.enforce == true
	not r.condition
}

# Subnet and private service access ranges with the file they come from.
ranges contains {"path": f.path, "cidr": f.contents.ip_cidr_range} if {
	some f in files
	is_dataset(f.path, "subnets")
	is_string(f.contents.ip_cidr_range)
	not startswith(f.contents.ip_cidr_range, "$")
}

ranges contains {"path": f.path, "cidr": cidr} if {
	some f in files
	some config in object.get(f.contents, "psa_configs", [])
	some _, list in object.get(config, "ranges", {})
	cidr := list
	is_string(cidr)
	not startswith(cidr, "$")
}

in_private_range(cidr) if {
	some p in private_ranges
	net.cidr_contains(p, cidr)
}

# --- rules --------------------------------------------------------------------

# LZ-ORG-001: the baseline guardrails stay enforced.
deny contains {"rule": "LZ-ORG-001", "path": path, "msg": msg} if {
	some constraint in required_enforced
	policy := object.get(org_policies, constraint, null)
	policy == null
	path := concat("", [org_policy_prefix, split(constraint, ".")[0], ".yaml"])
	msg := sprintf("org policy %s is missing from the landing zone", [constraint])
}

deny contains {"rule": "LZ-ORG-001", "path": policy.path, "msg": msg} if {
	some constraint in required_enforced
	policy := org_policies[constraint]
	not enforced_unconditionally(policy.rules)
	msg := sprintf("org policy %s is not enforced unconditionally", [constraint])
}

deny contains {"rule": "LZ-ORG-001", "path": policy.path, "msg": msg} if {
	some constraint in required_enforced
	policy := org_policies[constraint]
	some r in policy.rules
	r.enforce == false
	not r.condition
	msg := sprintf("org policy %s is switched off", [constraint])
}

# LZ-LOG-001: audit log buckets keep logs long enough.
deny contains {"rule": "LZ-LOG-001", "path": f.path, "msg": msg} if {
	some f in files
	some name, bucket in object.get(f.contents, "log_buckets", {})
	bucket.retention < min_retention_days
	msg := sprintf("log bucket %s keeps logs %d days; the minimum is %d", [name, bucket.retention, min_retention_days])
}

# LZ-NET-001: subnets and private service ranges are private (RFC 1918).
deny contains {"rule": "LZ-NET-001", "path": r.path, "msg": msg} if {
	some r in ranges
	not in_private_range(r.cidr)
	msg := sprintf("range %s is not in a private (RFC 1918) block", [r.cidr])
}

# LZ-NET-002: no two ranges overlap.
deny contains {"rule": "LZ-NET-002", "path": a.path, "msg": msg} if {
	some a in ranges
	some b in ranges
	a.path < b.path
	net.cidr_intersects(a.cidr, b.cidr)
	msg := sprintf("range %s overlaps %s in %s", [a.cidr, b.cidr, b.path])
}

# LZ-NET-003: no firewall rule allows non-ICMP ingress from the whole internet.
deny contains {"rule": "LZ-NET-003", "path": f.path, "msg": msg} if {
	some f in files
	is_dataset(f.path, "firewall-rules")
	some name, rule in object.get(f.contents, "ingress", {})
	not rule.deny
	"0.0.0.0/0" in object.get(rule, "source_ranges", [])
	some p in object.get(rule, "rules", [{"protocol": "all"}])
	lower(p.protocol) != "icmp"
	msg := sprintf("ingress rule %s allows %s from 0.0.0.0/0", [name, p.protocol])
}

deny contains {"rule": "LZ-NET-003", "path": f.path, "msg": msg} if {
	some f in files
	is_dataset(f.path, "firewall-policies")
	some name, rule in object.get(f.contents, "ingress_rules", {})
	rule.match.source_ranges[_] == "0.0.0.0/0"
	some l4 in object.get(rule.match, "layer4_configs", [{"protocol": "all"}])
	lower(l4.protocol) != "icmp"
	msg := sprintf("ingress rule %s allows %s from 0.0.0.0/0", [name, l4.protocol])
}

# LZ-NET-004: every VPC keeps a deny-all ingress rule at the lowest priority.
vpc_dirs contains dir if {
	some f in files
	endswith(f.path, "/.config.yaml")
	is_dataset(f.path, "vpcs")
	f.contents.peering_config
	dir := trim_suffix(f.path, "/.config.yaml")
}

vpc_dirs contains dir if {
	some f in files
	endswith(f.path, "/.config.yaml")
	is_dataset(f.path, "vpcs")
	f.contents.project_id
	dir := trim_suffix(f.path, "/.config.yaml")
}

has_default_deny(dir) if {
	some f in files
	startswith(f.path, concat("", [dir, "/firewall-rules/"]))
	some _, rule in object.get(f.contents, "ingress", {})
	rule.deny == true
	rule.priority == 65535
}

deny contains {"rule": "LZ-NET-004", "path": concat("", [dir, "/.config.yaml"]), "msg": msg} if {
	some dir in vpc_dirs
	not has_default_deny(dir)
	msg := "the VPC has no deny-all ingress rule at priority 65535"
}

# LZ-IAM-001: nothing is granted to everyone.
deny contains {"rule": "LZ-IAM-001", "path": f.path, "msg": msg} if {
	some f in files
	walk(f.contents, [_, value])
	value in {"allUsers", "allAuthenticatedUsers"}
	msg := sprintf("%s appears in this file; public principals are not allowed", [value])
}
