"""Unit tests for `lzctl spec validate` and `lzctl doctor`."""

import copy
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LZCTL = ROOT / ".agents/skills/landing-zone/scripts/lzctl"
VALID_DIR = ROOT / "evals/gcp/valid"


def _load_lzctl():
    loader = importlib.machinery.SourceFileLoader("lzctl", str(LZCTL))
    spec = importlib.util.spec_from_loader("lzctl", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


lzctl = _load_lzctl()


def load(name: str) -> dict:
    return json.loads((VALID_DIR / f"{name}.spec.json").read_text())


def mutated(name: str, change) -> dict:
    spec = copy.deepcopy(load(name))
    change(spec)
    return spec


def paths(findings) -> set[str]:
    return {f["path"] for f in findings}


@pytest.mark.parametrize("name", ["starter", "standard", "regulated"])
def test_golden_specs_are_valid(name):
    assert lzctl.validate_spec(load(name)) == []


def test_validation_is_deterministic():
    spec = mutated("standard", lambda s: s["network"].update(regions=[], cidr_supernet="8.8.8.0/24"))
    assert lzctl.validate_spec(spec) == lzctl.validate_spec(copy.deepcopy(spec))


def test_missing_mandatory_field_is_reported():
    spec = mutated("standard", lambda s: s["iam"]["groups"].pop("security_admins"))
    findings = lzctl.validate_spec(spec)
    assert paths(findings) == {"iam.groups"}
    assert "security_admins" in findings[0]["message"]


def test_unknown_field_is_rejected():
    spec = mutated("standard", lambda s: s["network"].update(hallucinated_input=True))
    assert paths(lzctl.validate_spec(spec)) == {"network"}


def test_wrong_spec_version():
    spec = mutated("standard", lambda s: s.update(spec_version="1.0"))
    assert paths(lzctl.validate_spec(spec)) == {"spec_version"}


def test_non_object_spec():
    assert paths(lzctl.validate_spec([])) == {"(root)"}


@pytest.mark.parametrize("cidr", ["8.8.8.0/24", "10.0.0.1/8", "10.0.0.0/24", "300.0.0.0/8"])
def test_bad_cidr(cidr):
    spec = mutated("standard", lambda s: s["network"].update(cidr_supernet=cidr))
    assert "network.cidr_supernet" in paths(lzctl.validate_spec(spec))


def test_bad_group_email():
    spec = mutated("standard", lambda s: s["iam"]["groups"].update(org_admins="not-an-email"))
    assert paths(lzctl.validate_spec(spec)) == {"iam.groups.org_admins"}


def test_starter_allows_one_environment_only():
    spec = mutated("starter", lambda s: s["hierarchy"].update(environments=["dev", "prod"]))
    assert paths(lzctl.validate_spec(spec)) == {"hierarchy.environments"}


@pytest.mark.parametrize("profile", ["standard", "regulated"])
def test_short_retention_rejected(profile):
    spec = mutated(profile, lambda s: s["logging"].update(retention_days=90))
    assert paths(lzctl.validate_spec(spec)) == {"logging.retention_days"}


def test_regulated_requires_customer_managed_keys():
    spec = mutated("regulated", lambda s: s["security"].update(customer_managed_keys=False))
    assert paths(lzctl.validate_spec(spec)) == {"security.customer_managed_keys"}


def test_regulated_requires_400_day_retention():
    spec = mutated("regulated", lambda s: s["logging"].update(retention_days=365))
    assert paths(lzctl.validate_spec(spec)) == {"logging.retention_days"}


def test_hub_spoke_needs_multiple_environments():
    spec = mutated("standard", lambda s: s["hierarchy"].update(environments=["prod"]))
    assert paths(lzctl.validate_spec(spec)) == {"hierarchy.environments"}


def test_service_perimeter_is_gcp_only():
    def change(s):
        s["target"]["cloud"] = "aws"
        s.pop("extensions")
        s["security"]["service_perimeter"] = True

    assert "security.service_perimeter" in paths(lzctl.validate_spec(mutated("regulated", change)))


def test_extensions_must_match_target_cloud():
    spec = mutated("standard", lambda s: s["extensions"].update(aws={"anything": 1}))
    assert paths(lzctl.validate_spec(spec)) == {"extensions"}


def test_gcp_extension_values_checked():
    spec = mutated("standard", lambda s: s["extensions"]["gcp"].update(hub_connectivity="carrier-pigeon"))
    assert paths(lzctl.validate_spec(spec)) == {"extensions.gcp.hub_connectivity"}


def test_unsupported_cloud_is_flagged():
    def change(s):
        s["target"]["cloud"] = "azure"
        s["security"]["service_perimeter"] = False
        s["extensions"] = {"azure": {"x": 1}}

    findings = lzctl.validate_spec(mutated("standard", change))
    assert [(f["rule"], f["path"]) for f in findings] == [("semantic.cloud_unsupported", "target.cloud")]


def test_decision_requires_rationale():
    spec = mutated("standard", lambda s: s["decisions"][0].pop("rationale"))
    assert paths(lzctl.validate_spec(spec)) == {"decisions.0"}


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LZCTL), *args], capture_output=True, text=True)


def test_cli_exit_zero_and_json_for_valid_spec():
    result = run_cli("spec", "validate", str(VALID_DIR / "standard.spec.json"))
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"valid": True, "findings": []}


def test_cli_exit_one_for_invalid_spec(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(mutated("standard", lambda s: s.update(spec_version="9"))))
    result = run_cli("spec", "validate", str(bad))
    assert result.returncode == 1
    assert json.loads(result.stdout)["valid"] is False


def test_cli_exit_two_for_missing_or_malformed_file(tmp_path):
    assert run_cli("spec", "validate", str(tmp_path / "nope.json")).returncode == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{")
    assert run_cli("spec", "validate", str(broken)).returncode == 2


def test_doctor_reports_required_dependencies():
    result = run_cli("doctor")
    assert result.stderr == ""  # no deprecation warnings leaking from dependencies
    report = json.loads(result.stdout)
    names = {c["name"] for c in report["checks"]}
    assert {"python>=3.11", "jsonschema", "jinja2", "terraform", "tflint", "trivy", "conftest"} <= names
    assert report["ok"] is True


def test_gcp_requires_extensions_block():
    spec = mutated("standard", lambda s: s.pop("extensions"))
    assert paths(lzctl.validate_spec(spec)) == {"(root)"}


@pytest.mark.parametrize("field", ["customer_id", "prefix"])
def test_gcp_requires_customer_id_and_prefix(field):
    spec = mutated("standard", lambda s: s["extensions"]["gcp"].pop(field))
    assert paths(lzctl.validate_spec(spec)) == {"extensions.gcp"}


@pytest.mark.parametrize("prefix", ["toolongpfx", "Acme", "a", "acme-", "-acme"])
def test_gcp_prefix_must_be_short_lowercase(prefix):
    spec = mutated("standard", lambda s: s["extensions"]["gcp"].update(prefix=prefix))
    assert paths(lzctl.validate_spec(spec)) == {"extensions.gcp.prefix"}


def test_gcp_organization_id_must_be_numeric():
    spec = mutated("standard", lambda s: s["organization"].update(id="organizations/123"))
    assert paths(lzctl.validate_spec(spec)) == {"organization.id"}


def test_gcp_billing_ref_format():
    spec = mutated("standard", lambda s: s["organization"].update(billing_ref="not-a-billing-id"))
    assert paths(lzctl.validate_spec(spec)) == {"organization.billing_ref"}


def test_baseline_version_must_match_the_pinned_baseline():
    spec = mutated("standard", lambda s: s["target"].update(baseline_version="v58.0.0"))
    assert paths(lzctl.validate_spec(spec)) == {"target.baseline_version"}


@pytest.mark.parametrize("value", ["example.com\n", "gcp-admins@example.com\r", "a\x00b"])
def test_control_characters_are_rejected_everywhere(value):
    spec = mutated("standard", lambda s: s["organization"].update(domain=value))
    assert any(f["rule"] == "semantic.control_character" for f in lzctl.validate_spec(spec))


@pytest.mark.parametrize("email", ["{x}@example.com", "a b@example.com", "x@example.com: y", "a:b@example.com"])
def test_yaml_significant_characters_in_emails_are_rejected(email):
    spec = mutated("standard", lambda s: s["iam"]["groups"].update(org_admins=email))
    assert "iam.groups.org_admins" in paths(lzctl.validate_spec(spec))
