"""Tests for the conftest policy pack, the rendered README and decision log, and the validation report."""

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _lzctl
from test_lzctl_check import DS, render_to, rules, statuses

lzctl = _lzctl.load()
ROOT = _lzctl.ROOT
VALID_DIR = ROOT / "evals/gcp/valid"
NET = "2-networking/datasets/landing-zone/"
needs_conftest = pytest.mark.skipif(not shutil.which("conftest"), reason="conftest not installed")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_lzctl.LZCTL), *args], capture_output=True, text=True)


def policy_rules(out: Path) -> set[str]:
    return {r.removeprefix("check.conftest.") for r in rules(lzctl.check_output(out)[1]) if r.startswith("check.conftest.")}


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new, 1))


# --- the policy pack ---------------------------------------------------------


@needs_conftest
@pytest.mark.parametrize("profile", ["starter", "standard"])
def test_clean_render_passes_the_policy_pack(tmp_path, profile):
    checks, findings = lzctl.check_output(render_to(tmp_path, profile))
    assert statuses(checks)["conftest"] == "passed"
    assert not [f for f in findings if f["rule"].startswith("check.conftest.")]


@needs_conftest
def test_a_guardrail_that_is_switched_off_is_caught(tmp_path):
    out = render_to(tmp_path)
    edit(out / DS / "organization/org-policies/storage.yaml", "storage.uniformBucketLevelAccess:\n  rules:\n    - enforce: true",
         "storage.uniformBucketLevelAccess:\n  rules:\n    - enforce: false")
    assert policy_rules(out) == {"LZ-ORG-001"}


@needs_conftest
def test_a_missing_guardrail_is_caught(tmp_path):
    out = render_to(tmp_path)
    path = out / DS / "organization/org-policies/compute.yaml"
    path.write_text(re.sub(r"\ncompute\.requireOsLogin:\n(?:  .*\n|\n)+?(?=\S)", "\n", path.read_text(), count=1))
    findings = [f for f in lzctl.check_output(out)[1] if f["rule"] == "check.conftest.LZ-ORG-001"]
    assert any("compute.requireOsLogin is missing" in f["message"] for f in findings)
    assert all(f["path"].startswith(DS) for f in findings)


@needs_conftest
def test_short_log_retention_is_caught(tmp_path):
    out = render_to(tmp_path)
    edit(out / DS / "projects/core/log-0.yaml", "retention: 365", "retention: 7")
    assert policy_rules(out) == {"LZ-LOG-001"}


@needs_conftest
def test_a_public_subnet_range_is_caught(tmp_path):
    out = render_to(tmp_path)
    edit(out / NET / "vpcs/prod/subnets/prod-default.yaml", "ip_cidr_range: ", "ip_cidr_range: 8.8.8.0/24 #")
    assert "LZ-NET-001" in policy_rules(out)


@needs_conftest
def test_overlapping_ranges_are_caught(tmp_path):
    out = render_to(tmp_path)
    dev = (out / NET / "vpcs/dev/subnets/dev-default.yaml").read_text()
    cidr = re.search(r"ip_cidr_range: (\S+)", dev).group(1)
    edit(out / NET / "vpcs/stage/subnets/stage-default.yaml", "ip_cidr_range: ", f"ip_cidr_range: {cidr} #")
    assert "LZ-NET-002" in policy_rules(out)


@needs_conftest
def test_ingress_from_the_internet_is_caught_in_a_vpc_rule_and_a_policy(tmp_path):
    out = render_to(tmp_path)
    rule = out / NET / "vpcs/dev/firewall-rules/default-ingress.yaml"
    rule.write_text(rule.read_text() + "  allow-ssh-world:\n    source_ranges:\n      - 0.0.0.0/0\n    rules:\n      - protocol: tcp\n        ports: [\"22\"]\n")
    policy = out / NET / "firewall-policies/networking-policy.yaml"
    edit(policy, "        - 35.235.240.0/20", "        - 0.0.0.0/0")
    findings = [f for f in lzctl.check_output(out)[1] if f["rule"] == "check.conftest.LZ-NET-003"]
    assert {f["path"] for f in findings} == {rule.relative_to(out).as_posix(), policy.relative_to(out).as_posix()}


@needs_conftest
def test_a_vpc_without_the_default_deny_is_caught(tmp_path):
    out = render_to(tmp_path)
    (out / NET / "vpcs/hub/firewall-rules/default-ingress.yaml").unlink()
    findings = [f for f in lzctl.check_output(out)[1] if f["rule"] == "check.conftest.LZ-NET-004"]
    assert [f["path"] for f in findings] == [NET + "vpcs/hub/.config.yaml"]


@needs_conftest
def test_public_principals_are_caught(tmp_path):
    out = render_to(tmp_path)
    (out / DS / "projects/core/public.yaml").write_text("iam:\n  roles/viewer:\n    - allUsers\n")
    assert "LZ-IAM-001" in policy_rules(out)


@needs_conftest
def test_policy_findings_on_an_edited_file_are_blamed_on_the_edit(tmp_path):
    out = render_to(tmp_path)
    edit(out / DS / "projects/core/log-0.yaml", "retention: 365", "retention: 7")
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    explained = lzctl.explain_findings(lzctl.check_output(out)[1], report)
    cause = next(f["cause"] for f in explained if f["rule"] == "check.conftest.LZ-LOG-001")
    assert cause["kind"] == "integrity"


@needs_conftest
def test_policy_findings_on_a_resigned_file_name_the_spec_fields(tmp_path):
    from test_lzctl_check import resign

    out = render_to(tmp_path)
    edit(out / DS / "projects/core/log-0.yaml", "retention: 365", "retention: 7")
    resign(out)
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    explained = lzctl.explain_findings(lzctl.check_output(out)[1], report)
    cause = next(f["cause"] for f in explained if f["rule"] == "check.conftest.LZ-LOG-001")
    assert cause["kind"] == "spec" and "logging.retention_days" in cause["spec_fields"]


def test_missing_conftest_is_reported_as_skipped(tmp_path, monkeypatch):
    out = render_to(tmp_path)
    real = shutil.which
    monkeypatch.setattr(lzctl.shutil, "which", lambda name, *a, **k: None if name == "conftest" else real(name, *a, **k))
    checks, findings = lzctl.check_output(out)
    assert statuses(checks)["conftest"] == "skipped"
    assert findings == []


def test_unparsable_yaml_skips_the_policy_check_instead_of_duplicating_the_finding(tmp_path):
    out = render_to(tmp_path)
    (out / DS / "defaults.yaml").write_text("a: [unclosed\n")
    checks, findings = lzctl.check_output(out)
    assert statuses(checks)["conftest"] == "skipped"
    assert not [f for f in findings if f["rule"].startswith("check.conftest.")]


def test_every_rule_in_the_pack_has_a_test():
    pack = (ROOT / ".agents/skills/landing-zone/policies/gcp/landing_zone.rego").read_text()
    declared = set(re.findall(r'"rule": "(LZ-[A-Z]+-\d+)"', pack))
    tested = set(re.findall(r"LZ-[A-Z]+-\d+", Path(__file__).read_text()))
    assert declared and declared <= tested, f"untested: {sorted(declared - tested)}"


# --- README and decision log -------------------------------------------------


def render(spec: dict) -> tuple[dict[str, bytes], dict]:
    return lzctl.render_spec(spec)


def spec_with_decision(**fields) -> dict:
    spec = copy.deepcopy(json.loads((VALID_DIR / "standard.spec.json").read_text()))
    spec["decisions"].append({"field": "logging.retention_days", "value": 400, "rationale": "needed", "source": "user", **fields})
    return spec


@pytest.mark.parametrize("profile", ["starter", "standard"])
def test_render_includes_the_readme_and_decision_log_in_the_report(profile):
    files, report = render(json.loads((VALID_DIR / f"{profile}.spec.json").read_text()))
    assert {"README.md", "decision-log.md"} <= set(files)
    assert {"README.md", "decision-log.md"} <= set(report["files"])
    assert report["sources"]["decision-log.md"] == ["decisions"]
    text = files["README.md"].decode()
    assert "example.com" in text and "lzctl check" in text and "never runs `terraform apply`" in text


def test_readme_lists_what_is_not_rendered_yet():
    files, report = render(json.loads((VALID_DIR / "starter.spec.json").read_text()))
    text = files["README.md"].decode()
    assert report["not_rendered_yet"], "the Starter golden spec should leave something unrendered"
    for field in report["not_rendered_yet"]:
        assert f"`{field}`" in text


def test_decision_log_has_one_row_per_decision():
    spec = json.loads((VALID_DIR / "standard.spec.json").read_text())
    text = render(spec)[0]["decision-log.md"].decode()
    rows = [line for line in text.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(rows) == len(spec["decisions"])


def test_decision_log_says_so_when_there_are_no_decisions():
    spec = json.loads((VALID_DIR / "standard.spec.json").read_text())
    spec["decisions"] = []
    assert "records no decisions" in render(spec)[0]["decision-log.md"].decode()


@pytest.mark.parametrize(
    "rationale",
    ["a | b", "`code` and *emphasis* and _under_", "<script>alert(1)</script>", "[link](http://example.com)", "back\\slash", "a & b"],
)
def test_decision_text_cannot_break_the_markdown_table(rationale):
    text = render(spec_with_decision(rationale=rationale))[0]["decision-log.md"].decode()
    row = next(line for line in text.splitlines() if line.startswith("| 3 |"))
    assert len(re.findall(r"(?<!\\)\|", row)) == 6, row
    assert "<" not in row and not re.search(r"(?<!\\)[\[\]]", row), row


def test_decision_field_cannot_break_out_of_its_code_span():
    text = render(spec_with_decision(field="a`b|c"))[0]["decision-log.md"].decode()
    row = next(line for line in text.splitlines() if line.startswith("| 3 |"))
    assert "`a'b\\|c`" in row


def test_readme_and_decision_log_are_deterministic():
    spec = json.loads((VALID_DIR / "standard.spec.json").read_text())
    first, second = render(spec)[0], render(copy.deepcopy(spec))[0]
    assert first["README.md"] == second["README.md"] and first["decision-log.md"] == second["decision-log.md"]


def test_editing_the_readme_after_rendering_is_caught(tmp_path):
    out = render_to(tmp_path)
    with (out / "README.md").open("a") as handle:
        handle.write("\nTrust me.\n")
    assert [(f["rule"], f["path"]) for f in lzctl.check_output(out)[1]] == [("check.integrity.modified", "README.md")]


# --- the validation report ---------------------------------------------------


def test_write_report_creates_the_validation_report_and_check_stays_clean(tmp_path):
    out = render_to(tmp_path)
    first = run_cli("check", str(out), "--write-report")
    assert first.returncode == 0, first.stdout + first.stderr
    report = (out / lzctl.VALIDATION_REPORT).read_text()
    assert report.startswith("# Validation report")
    assert json.loads((out / lzctl.REPORT_NAME).read_text())["output_hash"] in report
    again = run_cli("check", str(out))
    assert again.returncode == 0 and json.loads(again.stdout)["findings"] == []


def test_validation_report_says_when_checks_did_not_run(tmp_path):
    out = render_to(tmp_path)
    assert run_cli("check", str(out), "--write-report").returncode == 0
    text = (out / lzctl.VALIDATION_REPORT).read_text()
    assert "not fully validated" in text
    assert "terraform-validate (not\\_applicable)" in text and "tflint (not\\_applicable)" in text


def test_validation_report_lists_findings_and_fails(tmp_path):
    out = render_to(tmp_path)
    with (out / DS / "defaults.yaml").open("a") as handle:
        handle.write("# edited by hand\n")
    result = run_cli("check", str(out), "--write-report")
    assert result.returncode == 1
    text = (out / lzctl.VALIDATION_REPORT).read_text()
    assert "**Failed:** 1 finding(s)." in text and "check.integrity.modified" in text


def test_validation_report_is_deterministic(tmp_path):
    out = render_to(tmp_path)
    run_cli("check", str(out), "--write-report")
    first = (out / lzctl.VALIDATION_REPORT).read_bytes()
    run_cli("check", str(out), "--write-report")
    assert (out / lzctl.VALIDATION_REPORT).read_bytes() == first


def test_check_without_the_flag_writes_nothing(tmp_path):
    out = render_to(tmp_path)
    run_cli("check", str(out))
    assert not (out / lzctl.VALIDATION_REPORT).exists()
