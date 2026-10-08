"""Tests for the GCP 2-networking render: CIDR plan, rendered files and what is dropped."""

import copy
import ipaddress
import json
import re

import pytest
import yaml

import _lzctl

lzctl = _lzctl.load()
ROOT = _lzctl.ROOT
NET = "2-networking/datasets/landing-zone/"
ALL_ENVS = ["dev", "stage", "prod"]


def spec(**network) -> dict:
    base = json.loads((ROOT / "evals/gcp/valid/standard.spec.json").read_text())
    base["network"].update(network)
    return base


def render(s: dict) -> tuple[dict, dict]:
    return lzctl.render_spec(s)


def nets(plan: dict) -> list[tuple[str, ipaddress.IPv4Network]]:
    out = []
    for vpc, entry in plan.items():
        out += [(f"{vpc}:{region}", ipaddress.ip_network(cidr)) for region, cidr in entry["subnets"].items()]
        if entry["psa"]:
            out.append((f"{vpc}:psa", ipaddress.ip_network(entry["psa"])))
    return out


# --- CIDR plan ----------------------------------------------------------------


@pytest.mark.parametrize("supernet", ["10.0.0.0/8", "10.64.0.0/10", "172.16.0.0/12", "10.20.0.0/16"])
@pytest.mark.parametrize("regions", [["us-central1"], ["us-central1", "us-east1"], [f"us-r{i}" for i in range(8)]])
def test_plan_never_overlaps_and_stays_inside_the_supernet(supernet, regions):
    plan = lzctl.plan_cidrs(supernet, regions, ALL_ENVS, psa=True)
    ranges = nets(plan)
    inside = ipaddress.ip_network(supernet)
    for name, net in ranges:
        assert net.subnet_of(inside), name
    for i, (a, na) in enumerate(ranges):
        for b, nb in ranges[i + 1:]:
            assert not na.overlaps(nb), (a, b)


def test_default_subnets_are_slash_24_and_psa_is_at_most_slash_20():
    plan = lzctl.plan_cidrs("10.0.0.0/8", ["us-central1", "us-east1"], ALL_ENVS, psa=True)
    assert all(ipaddress.ip_network(c).prefixlen == 24 for e in plan.values() for c in e["subnets"].values())
    assert {ipaddress.ip_network(plan[e]["psa"]).prefixlen for e in ALL_ENVS} == {20}
    small = lzctl.plan_cidrs("10.20.0.0/16", ["us-central1"], ALL_ENVS, psa=True)
    assert {ipaddress.ip_network(small[e]["psa"]).prefixlen for e in ALL_ENVS} == {22}  # the whole block


def test_hub_has_no_psa_range_and_psa_can_be_off():
    plan = lzctl.plan_cidrs("10.0.0.0/8", ["us-central1"], ALL_ENVS, psa=True)
    assert plan["hub"]["psa"] is None
    assert all(e["psa"] is None for e in lzctl.plan_cidrs("10.0.0.0/8", ["us-central1"], ALL_ENVS, psa=False).values())


def test_plan_is_stable_when_environments_or_regions_change():
    full = lzctl.plan_cidrs("10.0.0.0/8", ["us-central1"], ALL_ENVS, psa=True)
    only_prod = lzctl.plan_cidrs("10.0.0.0/8", ["us-central1"], ["prod"], psa=True)
    assert only_prod["prod"] == full["prod"] and "dev" not in only_prod
    more_regions = lzctl.plan_cidrs("10.0.0.0/8", ["us-central1", "europe-west1"], ALL_ENVS, psa=True)
    for vpc, entry in full.items():  # appending a region leaves every existing range where it was
        assert more_regions[vpc]["subnets"]["us-central1"] == entry["subnets"]["us-central1"]
        assert more_regions[vpc]["psa"] == entry["psa"]


def test_plan_does_not_depend_on_environment_order():
    assert lzctl.plan_cidrs("10.0.0.0/8", ["a-b1"], ["prod", "dev", "stage"], True) == lzctl.plan_cidrs("10.0.0.0/8", ["a-b1"], ALL_ENVS, True)


def test_more_than_eight_regions_is_a_spec_finding():
    findings = lzctl.validate_spec(spec(regions=[f"us-r{i}" for i in range(9)]))
    assert [f["rule"] for f in findings] == ["semantic.regions"]
    assert lzctl.validate_spec(spec(regions=[f"us-r{i}" for i in range(8)])) == []


# --- rendered files -------------------------------------------------------------


def test_standard_renders_the_hub_and_one_spoke_per_environment():
    files, report = render(spec())
    vpcs = {m.group(1) for p in files if (m := re.fullmatch(NET + r"vpcs/([a-z]+)/\.config\.yaml", p))}
    assert vpcs == {"hub", "dev", "stage", "prod"}
    hub = yaml.safe_load(files[NET + "vpcs/hub/.config.yaml"])
    assert set(hub["peering_config"]) == {"to-dev", "to-stage", "to-prod"}
    prod = yaml.safe_load(files[NET + "vpcs/prod/.config.yaml"])
    assert prod["peering_config"] == {"to-hub": {"peer_network": "$networks:hub"}}
    assert prod["psa_configs"][0]["ranges"] == {"psa": "10.252.0.0/20"}
    assert yaml.safe_load(files[NET + "projects/net-stage-0.yaml"])["parent"] == "$folder_ids:networking/stage"
    assert not any(f.startswith("network.") for f in report["not_rendered_yet"])


def test_subnets_follow_the_plan_and_use_location_references():
    files, _ = render(spec())
    primary = yaml.safe_load(files[NET + "vpcs/dev/subnets/dev-default.yaml"])
    second = yaml.safe_load(files[NET + "vpcs/dev/subnets/dev-default-us-east1.yaml"])
    assert (primary["region"], primary["ip_cidr_range"]) == ("$locations:primary", "10.64.0.0/24")
    assert (second["region"], second["ip_cidr_range"]) == ("us-east1", "10.68.0.0/24")
    defaults = yaml.safe_load(files[NET + "defaults.yaml"])
    assert defaults["context"]["locations"] == {"primary": "us-central1", "secondary": "us-east1"}
    assert defaults["projects"]["defaults"]["locations"]["storage"] == "$locations:primary"


def test_only_selected_environments_get_networking():
    s = spec()
    s["hierarchy"]["environments"] = ["dev", "prod"]
    files, _ = render(s)
    assert not any("stage" in p for p in files if p.startswith("2-networking/"))
    assert set(yaml.safe_load(files[NET + "vpcs/hub/.config.yaml"])["peering_config"]) == {"to-dev", "to-prod"}
    assert "$networks:stage" not in files[NET + "dns/zones/net-core-0/peer-root.yaml"].decode()
    policy = files[NET + "dns/response-policies/net-core-0.yaml"].decode()
    assert "  - $networks:hub\n  - $networks:dev\n  - $networks:prod\nrules:" in policy and "$networks:stage" not in policy


def test_dns_files_are_patched_not_rewritten():
    files, _ = render(spec())
    upstream = (lzctl.TEMPLATE_DIR / "gcp/fast-v59.0.0/upstream/networking/datasets/hub-and-spokes-peerings"
                / "dns/response-policies/net-core-0.yaml").read_text()
    rendered = files[NET + "dns/response-policies/net-core-0.yaml"].decode()
    assert rendered.split("rules:", 1)[1] == upstream.split("rules:", 1)[1]
    assert "  - $networks:stage\n" in rendered


def test_no_upstream_demo_content_reaches_the_output():
    files, _ = render(spec())
    # Upstream files we keep verbatim carry commented-out examples; only live content counts.
    blob = "\n".join(
        line
        for path, data in files.items()
        if path.startswith("2-networking/")
        for line in data.decode().splitlines()
        if not line.lstrip().startswith("#")
    )
    for placeholder in ("mySecret", "onprem", "my-interconnect", "1.1.1.1", "europe-west1", "10.71.0.0", "10.73.0.0"):
        assert placeholder not in blob, placeholder
    assert not any(re.search(r"/(vpns|vlan-attachments)/|fwd-root|pvt-", p) for p in files)


def test_kept_upstream_files_are_byte_identical():
    files, _ = render(spec())
    upstream = lzctl.TEMPLATE_DIR / "gcp/fast-v59.0.0/upstream/networking/datasets/hub-and-spokes-peerings"
    for relative in ("firewall-policies/networking-policy.yaml", "projects/net-core-0.yaml", "vpcs/hub/firewall-rules/default-ingress.yaml"):
        assert files[NET + relative] == (upstream / relative).read_bytes(), relative


def test_tfvars_points_at_the_networking_dataset():
    files, _ = render(spec())
    assert 'dataset = "datasets/landing-zone"' in files["2-networking/2-networking.auto.tfvars"].decode()


def test_networking_sources_name_real_spec_fields():
    s = spec()
    files, report = render(s)
    net_sources = {p: f for p, f in report["sources"].items() if p.startswith("2-networking/")}
    assert net_sources and set(net_sources) <= set(files)
    assert all(lzctl._present(s, field) for fields in net_sources.values() for field in fields)
    assert net_sources[NET + "vpcs/dev/subnets/dev-default.yaml"] == ["network.cidr_supernet", "network.regions"]


# --- what is not rendered ---------------------------------------------------------


def test_single_topology_renders_no_networking():
    s = spec(topology="single", regions=["us-central1"])
    files, report = render(s)
    assert not any(p.startswith("2-networking/") for p in files)
    assert "single topology" in report["not_rendered_yet"]["network.topology"]
    assert "network.cidr_supernet" in report["not_rendered_yet"]


@pytest.mark.parametrize("connectivity", ["ncc", "nva", "vpn"])
def test_other_hub_connectivity_is_reported_not_rendered(connectivity):
    s = spec()
    s["extensions"]["gcp"]["hub_connectivity"] = connectivity
    files, report = render(s)
    assert not any(p.startswith("2-networking/") for p in files)
    assert connectivity in report["not_rendered_yet"]["extensions.gcp.hub_connectivity"]
    assert "network.regions[1:]" in report["not_rendered_yet"]


def test_networking_render_is_deterministic_and_independent_of_environment_order():
    s = spec()
    shuffled = copy.deepcopy(s)
    shuffled["hierarchy"]["environments"] = ["prod", "dev", "stage"]
    assert render(s)[1]["output_hash"] == render(shuffled)[1]["output_hash"]


def test_a_changed_upstream_networking_layout_is_refused(monkeypatch):
    monkeypatch.setattr(lzctl, "NETWORKING_DROPPED", (*lzctl.NETWORKING_DROPPED, "vpcs/does-not-exist/"))
    with pytest.raises(lzctl.RenderError, match="is gone"):
        render(spec())


def test_a_changed_upstream_dns_shape_is_refused(monkeypatch):
    monkeypatch.setattr(lzctl, "PEER_ROOT_CLIENTS", "  client_networks:\n    - $networks:nope\n")
    with pytest.raises(lzctl.RenderError, match="changed shape"):
        render(spec())


# --- check ------------------------------------------------------------------------


def write(tmp_path, files, report):
    out = tmp_path / "out"
    for path, data in files.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(data)
    (out / lzctl.REPORT_NAME).write_text(json.dumps(report))
    return out


def test_check_validates_networking_files_against_the_networking_schemas(tmp_path):
    out = write(tmp_path, *render(spec()))
    assert lzctl.check_output(out)[1] == []
    # `mtu` must be an integer in the networking vpc schema; the stage-0 schemas would not catch this.
    vpc = out / NET / "vpcs/dev/.config.yaml"
    vpc.write_text(vpc.read_text().replace("mtu: 1500", "mtu: not-a-number"))
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    report["files"][NET + "vpcs/dev/.config.yaml"] = lzctl._sha256(vpc.read_bytes())
    report["output_hash"] = lzctl._output_hash(report["files"])
    (out / lzctl.REPORT_NAME).write_text(json.dumps(report))
    findings = lzctl.check_output(out)[1]
    assert [(f["rule"], f["path"]) for f in findings] == [("check.schema.type", NET + "vpcs/dev/.config.yaml")]
    explained = lzctl.explain_findings(findings, report)[0]["cause"]
    assert explained["kind"] == "spec" and "network.cidr_supernet" in explained["spec_fields"]
