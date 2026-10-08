"""Tests for `lzctl check` on rendered GCP output."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _lzctl

lzctl = _lzctl.load()
ROOT = _lzctl.ROOT
VALID_DIR = ROOT / "evals/gcp/valid"
DS = "datasets/landing-zone/"
needs_terraform = pytest.mark.skipif(not (shutil.which("terraform") or shutil.which("tofu")), reason="terraform not installed")


def render_to(tmp_path: Path, name: str = "standard") -> Path:
    files, report = lzctl.render_spec(json.loads((VALID_DIR / f"{name}.spec.json").read_text()))
    out = tmp_path / "out"
    for relative, data in files.items():
        (out / relative).parent.mkdir(parents=True, exist_ok=True)
        (out / relative).write_bytes(data)
    (out / lzctl.REPORT_NAME).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return out


def resign(out: Path) -> None:
    """Make the report match the files on disk, as an attacker who edits both would."""
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    files, _ = lzctl._walk_files(out)
    report["files"] = {rel: lzctl._sha256(p.read_bytes()) for rel, p in sorted(files.items()) if rel != lzctl.REPORT_NAME}
    report["output_hash"] = lzctl._output_hash(report["files"])
    (out / lzctl.REPORT_NAME).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def rules(findings: list[dict]) -> set[str]:
    return {f["rule"] for f in findings}


def statuses(checks: list[dict]) -> dict[str, str]:
    return {c["name"]: c["status"] for c in checks}


@pytest.mark.parametrize("profile", ["starter", "standard"])
def test_clean_render_passes(tmp_path, profile):
    checks, findings = lzctl.check_output(render_to(tmp_path, profile))
    assert findings == []
    status = statuses(checks)
    assert status["integrity"] == "passed" and status["upstream-schemas"] == "passed"
    assert status["terraform-fmt"] in ("passed", "skipped")


def test_tools_without_work_are_reported_not_passed(tmp_path):
    status = statuses(lzctl.check_output(render_to(tmp_path))[0])
    assert {status[name] for name in [*lzctl.NOT_APPLICABLE, "trivy", "checkov"]} == {"not_applicable"}


def test_schema_check_covers_the_rendered_yaml(tmp_path):
    checks, _ = lzctl.check_output(render_to(tmp_path))
    detail = next(c["detail"] for c in checks if c["name"] == "upstream-schemas")
    assert int(detail.split()[0]) >= 40


def test_hand_edit_is_caught(tmp_path):
    out = render_to(tmp_path)
    with (out / DS / "defaults.yaml").open("a") as handle:
        handle.write("# edited by hand\n")
    findings = lzctl.check_output(out)[1]
    assert [(f["rule"], f["path"]) for f in findings] == [("check.integrity.modified", DS + "defaults.yaml")]


def test_extra_and_missing_files_are_caught(tmp_path):
    out = render_to(tmp_path)
    (out / "stray.txt").write_text("x")
    (out / DS / "cicd.yaml").unlink()
    found = {(f["rule"], f["path"]) for f in lzctl.check_output(out)[1]}
    assert ("check.integrity.extra", "stray.txt") in found
    assert ("check.integrity.missing", DS + "cicd.yaml") in found


def test_symlinks_are_refused_and_not_followed(tmp_path):
    out = render_to(tmp_path)
    secret = tmp_path / "secret.yaml"
    secret.write_text("a: [unclosed")
    (out / "link.yaml").symlink_to(secret)
    (out / "linkdir").symlink_to(tmp_path, target_is_directory=True)
    findings = lzctl.check_output(out)[1]
    assert {f["path"] for f in findings if f["rule"] == "check.integrity.symlink"} == {"link.yaml", "linkdir"}
    assert "check.yaml.parse" not in rules(findings)


def test_tampered_output_hash_is_caught(tmp_path):
    out = render_to(tmp_path)
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    report["output_hash"] = "0" * 64
    (out / lzctl.REPORT_NAME).write_text(json.dumps(report))
    assert rules(lzctl.check_output(out)[1]) == {"check.integrity.output_hash"}


def test_resigned_schema_violation_is_caught(tmp_path):
    out = render_to(tmp_path)
    folder = out / DS / "folders/security/dev/.config.yaml"
    folder.write_text(folder.read_text() + "unexpected_key: true\n")
    resign(out)
    findings = lzctl.check_output(out)[1]
    assert [f["path"] for f in findings] == [DS + "folders/security/dev/.config.yaml"]
    assert findings[0]["rule"].startswith("check.schema.") and "unexpected_key" in findings[0]["message"]


def test_resigned_yaml_syntax_error_is_caught(tmp_path):
    out = render_to(tmp_path)
    (out / DS / "defaults.yaml").write_text("a: [unclosed\n")
    resign(out)
    assert rules(lzctl.check_output(out)[1]) == {"check.yaml.parse"}


def test_unknown_schema_declaration_is_caught(tmp_path):
    out = render_to(tmp_path)
    (out / DS / "cicd.yaml").write_text("# yaml-language-server: $schema=../schemas/made-up.schema.json\n")
    resign(out)
    assert rules(lzctl.check_output(out)[1]) == {"check.schema.unknown"}


def test_baseline_version_mismatch_is_caught(tmp_path):
    out = render_to(tmp_path)
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    report["baseline"]["tag"] = "v1.0.0"
    (out / lzctl.REPORT_NAME).write_text(json.dumps(report))
    assert rules(lzctl.check_output(out)[1]) == {"check.baseline.mismatch"}


@needs_terraform
def test_unformatted_tfvars_is_caught(tmp_path):
    out = render_to(tmp_path)
    (out / "0-org-setup.auto.tfvars").write_text('factories_config   =   {\ndataset="datasets/landing-zone"\n}\n')
    resign(out)
    checks, findings = lzctl.check_output(out)
    assert statuses(checks)["terraform-fmt"] == "failed"
    assert [(f["rule"], f["path"]) for f in findings] == [("check.terraform.fmt", "0-org-setup.auto.tfvars")]


def test_missing_terraform_is_skipped_not_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(lzctl.shutil, "which", lambda name: None)
    checks, findings = lzctl.check_output(render_to(tmp_path))
    assert findings == [] and statuses(checks)["terraform-fmt"] == "skipped"


@pytest.mark.parametrize("report", [None, "not json", "[]", '{"files": {"a": 1}}'])
def test_not_a_render_directory_is_an_error(tmp_path, report):
    if report is not None:
        (tmp_path / lzctl.REPORT_NAME).write_text(report)
    with pytest.raises(lzctl.CheckError):
        lzctl.check_output(tmp_path)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_lzctl.LZCTL), *args], capture_output=True, text=True)


def test_cli_check_clean_and_dirty(tmp_path):
    out = render_to(tmp_path)
    clean = run_cli("check", str(out))
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout)["ok"] is True

    (out / "stray.txt").write_text("x")
    dirty = run_cli("check", str(out))
    assert dirty.returncode == 1
    payload = json.loads(dirty.stdout)
    assert payload["ok"] is False and payload["findings"][0]["path"] == "stray.txt"


def test_cli_check_text_format(tmp_path):
    result = run_cli("check", str(render_to(tmp_path)), "--format", "text")
    assert result.returncode == 0 and "passed          integrity" in result.stdout


def test_cli_check_errors_exit_two(tmp_path):
    assert run_cli("check", str(tmp_path / "missing")).returncode == 2
    assert run_cli("check", str(tmp_path)).returncode == 2


# --- HCL scanners (trivy, checkov) -------------------------------------------

BUCKET_TF = '''resource "google_storage_bucket" "b" {
  name     = "example-bucket"
  location = "US"
}
'''


def test_ci_has_every_tool_installed():
    """CI sets REQUIRE_TOOLS so a broken tool install fails the job instead of silently skipping tests."""
    if not os.environ.get("REQUIRE_TOOLS"):
        pytest.skip("REQUIRE_TOOLS not set")
    missing = [tool for tool in ("terraform", "trivy", "checkov", "conftest") if not shutil.which(tool)]
    assert not missing, f"not installed: {missing}"


needs_trivy = pytest.mark.skipif(not shutil.which("trivy"), reason="trivy not installed")
needs_checkov = pytest.mark.skipif(not shutil.which("checkov"), reason="checkov not installed")


def with_hcl(tmp_path: Path, text: str = BUCKET_TF) -> Path:
    out = render_to(tmp_path)
    (out / "main.tf").write_text(text)
    resign(out)
    return out


def completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def fake_tools(monkeypatch, trivy=None, checkov=None):
    """Pretend both scanners are installed and answer with the given results (or exceptions)."""
    answers = {"trivy": trivy, "checkov": checkov}
    monkeypatch.setattr(lzctl.shutil, "which", lambda name: f"/fake/{name}" if name in answers else None)

    def run(argv, **kwargs):
        answer = answers[Path(argv[0]).name]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(lzctl.subprocess, "run", run)


TRIVY_FAIL = json.dumps({"Results": [
    {"Target": "main.tf", "Misconfigurations": [
        {"ID": "GCP-0002", "Title": "Uniform access disabled", "Severity": "MEDIUM", "Status": "FAIL",
         "CauseMetadata": {"Resource": "google_storage_bucket.b"}},
        {"ID": "GCP-0001", "Title": "Passing rule", "Severity": "LOW", "Status": "PASS"},
    ]},
    {"Target": "."},
]})
CHECKOV_FAIL = json.dumps({"summary": {"parsing_errors": 0}, "results": {"failed_checks": [
    {"check_id": "CKV_GCP_114", "check_name": "Public access prevention", "file_path": "/main.tf", "resource": "google_storage_bucket.b"},
]}})
CLEAN_TRIVY = json.dumps({"Results": [{"Target": "main.tf", "MisconfSummary": {"Successes": 3, "Failures": 0}}]})
CLEAN_CHECKOV = json.dumps({"summary": {"parsing_errors": 0}, "results": {"failed_checks": []}})


def test_scanners_report_findings_per_tool(tmp_path, monkeypatch):
    out = with_hcl(tmp_path)
    fake_tools(monkeypatch, completed(TRIVY_FAIL), completed(CHECKOV_FAIL, returncode=1))
    checks, findings = lzctl.check_output(out)
    assert statuses(checks)["trivy"] == "failed" and statuses(checks)["checkov"] == "failed"
    assert [(f["rule"], f["path"]) for f in findings] == [("check.checkov.CKV_GCP_114", "main.tf"), ("check.trivy.GCP-0002", "main.tf")]
    assert "google_storage_bucket.b" in findings[1]["message"] and "[MEDIUM]" in findings[1]["message"]


def test_clean_scans_pass(tmp_path, monkeypatch):
    out = with_hcl(tmp_path)
    fake_tools(monkeypatch, completed(CLEAN_TRIVY), completed(CLEAN_CHECKOV))
    checks, findings = lzctl.check_output(out)
    assert findings == [] and statuses(checks)["trivy"] == statuses(checks)["checkov"] == "passed"


def test_scanners_are_skipped_when_not_installed(tmp_path, monkeypatch):
    out = with_hcl(tmp_path)
    monkeypatch.setattr(lzctl.shutil, "which", lambda name: None)
    checks, findings = lzctl.check_output(out)
    assert findings == [] and statuses(checks)["trivy"] == statuses(checks)["checkov"] == "skipped"


@pytest.mark.parametrize("bad", [
    completed("not json"),
    completed("[]"),
    completed("", returncode=2, stderr="boom\nmore"),
    subprocess.TimeoutExpired("trivy", 120),
    OSError("cannot execute"),
])
def test_trivy_failures_are_findings_not_passes(tmp_path, monkeypatch, bad):
    out = with_hcl(tmp_path)
    fake_tools(monkeypatch, trivy=bad, checkov=completed(CLEAN_CHECKOV))
    checks, findings = lzctl.check_output(out)
    assert statuses(checks)["trivy"] == "failed" and rules(findings) == {"check.trivy.error"}


@pytest.mark.parametrize("bad", [completed("not json"), completed("", returncode=2, stderr="crash"), subprocess.TimeoutExpired("checkov", 120)])
def test_checkov_failures_are_findings_not_passes(tmp_path, monkeypatch, bad):
    out = with_hcl(tmp_path)
    fake_tools(monkeypatch, trivy=completed(CLEAN_TRIVY), checkov=bad)
    checks, findings = lzctl.check_output(out)
    assert statuses(checks)["checkov"] == "failed" and rules(findings) == {"check.checkov.error"}


def test_checkov_parsing_errors_are_findings(tmp_path, monkeypatch):
    out = with_hcl(tmp_path)
    parse_error = json.dumps({"summary": {"parsing_errors": 1}, "results": {"failed_checks": []}})
    fake_tools(monkeypatch, completed(CLEAN_TRIVY), completed(parse_error))
    assert rules(lzctl.check_output(out)[1]) == {"check.checkov.parse"}


def test_checkov_accepts_a_list_of_reports(tmp_path, monkeypatch):
    out = with_hcl(tmp_path)
    fake_tools(monkeypatch, completed(CLEAN_TRIVY), completed(f"[{CHECKOV_FAIL}, {CLEAN_CHECKOV}]", returncode=1))
    assert rules(lzctl.check_output(out)[1]) == {"check.checkov.CKV_GCP_114"}


@pytest.mark.parametrize("comment", ["#checkov:skip=CKV_GCP_114:no", "# trivy:ignore:GCP-0002", "// tfsec:ignore:google-storage"])
def test_inline_suppressions_are_refused(tmp_path, monkeypatch, comment):
    out = with_hcl(tmp_path, comment + "\n" + BUCKET_TF)
    fake_tools(monkeypatch, completed(CLEAN_TRIVY), completed(CLEAN_CHECKOV))
    assert rules(lzctl.check_output(out)[1]) == {"check.hcl.suppression"}


def test_scanners_run_inside_the_rendered_directory_without_network_flags(tmp_path, monkeypatch):
    out = with_hcl(tmp_path)
    seen = []

    def run(argv, **kwargs):
        seen.append((Path(argv[0]).name, argv, kwargs["cwd"], kwargs["timeout"]))
        return completed(CLEAN_TRIVY if "trivy" in argv[0] else CLEAN_CHECKOV)

    monkeypatch.setattr(lzctl.shutil, "which", lambda name: f"/fake/{name}" if name in ("trivy", "checkov") else None)
    monkeypatch.setattr(lzctl.subprocess, "run", run)
    lzctl.check_output(out)
    by_tool = {name: (argv, cwd, timeout) for name, argv, cwd, timeout in seen}
    assert by_tool["trivy"][0].count("--skip-check-update") == 1 and "--skip-download" in by_tool["checkov"][0]
    assert all(cwd == out and timeout == lzctl.SCAN_TIMEOUT for _, cwd, timeout in by_tool.values())


@needs_trivy
def test_real_trivy_flags_a_misconfigured_bucket(tmp_path):
    exe = shutil.which("trivy")
    check, findings = lzctl._scan_trivy(exe, with_hcl(tmp_path))
    assert check["status"] == "failed"
    assert any(f["rule"] == "check.trivy.GCP-0002" and f["path"] == "main.tf" for f in findings)


@needs_checkov
def test_real_checkov_flags_a_misconfigured_bucket(tmp_path):
    exe = shutil.which("checkov")
    check, findings = lzctl._scan_checkov(exe, with_hcl(tmp_path))
    assert check["status"] == "failed"
    assert any(f["rule"].startswith("check.checkov.CKV_GCP") and f["path"] == "main.tf" for f in findings)


@needs_trivy
def test_real_trivy_passes_hcl_with_no_findings(tmp_path):
    out = with_hcl(tmp_path, 'variable "name" {\n  type = string\n}\n')
    assert lzctl._scan_trivy(shutil.which("trivy"), out) == ({"name": "trivy", "status": "passed", "detail": "no misconfigurations"}, [])


# --- explain -----------------------------------------------------------------


def break_schema(path: Path) -> None:
    """Replace a rendered YAML file's body with schema-invalid content, keeping its schema declaration."""
    header = next(line for line in path.read_text().splitlines() if "yaml-language-server" in line)
    path.write_text(header + "\nlog_buckets: 3\n")


def explained(findings, report=None):
    return lzctl.explain_findings(findings, report)


def causes(out: Path) -> dict[tuple[str, str], dict]:
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    return {(e["rule"], e["path"]): e["cause"] for e in explained(lzctl.check_output(out)[1], report)}


def test_sources_name_real_spec_fields_and_rendered_files():
    spec = json.loads((VALID_DIR / "standard.spec.json").read_text())
    files, report = lzctl.render_spec(spec)
    assert report["sources"] and set(report["sources"]) <= set(files)
    for path, fields in report["sources"].items():
        assert fields and all(lzctl._present(spec, field) for field in fields), path
    assert report["sources"][DS + "projects/core/log-0.yaml"] == ["logging.audit_destination", "logging.retention_days"]
    assert report["sources"][DS + "folders/teams/payments/.config.yaml"] == ["hierarchy.business_units"]


def test_sources_do_not_change_the_output_hash():
    # Provenance is metadata about the files, not part of them: golden hashes stay valid.
    spec = json.loads((VALID_DIR / "standard.spec.json").read_text())
    files, report = lzctl.render_spec(spec)
    assert report["output_hash"] == lzctl._output_hash({p: lzctl._sha256(d) for p, d in files.items()})


def test_schema_finding_on_a_generated_file_points_at_the_spec(tmp_path):
    out = render_to(tmp_path)
    break_schema(out / DS / "projects/core/log-0.yaml")
    resign(out)
    cause = next(c for (rule, path), c in causes(out).items() if rule.startswith("check.schema."))
    assert cause["kind"] == "spec" and cause["spec_fields"] == ["logging.audit_destination", "logging.retention_days"]


def test_finding_on_an_untouched_upstream_file_is_not_blamed_on_the_spec(tmp_path):
    out = render_to(tmp_path)
    (out / DS / "cicd.yaml").write_text("# yaml-language-server: $schema=../schemas/made-up.schema.json\n")
    resign(out)
    cause = causes(out)[("check.schema.unknown", DS + "cicd.yaml")]
    assert cause["kind"] == "vendored" and cause["spec_fields"] == []


def test_hand_edit_is_blamed_on_the_edit_not_the_spec(tmp_path):
    out = render_to(tmp_path)
    break_schema(out / DS / "projects/core/log-0.yaml")  # schema-invalid, but the report was not re-signed
    found = causes(out)
    assert {c["kind"] for c in found.values()} == {"integrity"}
    assert any(rule.startswith("check.schema.") for rule, _ in found)


def test_spec_validate_findings_pass_through_as_spec_fields():
    finding = {"rule": "schema.minimum", "path": "logging.retention_days", "message": "too small"}
    cause = explained([finding])[0]["cause"]
    assert cause == {"kind": "spec", "spec_fields": ["logging.retention_days"], "advice": "Change this field in the spec."}


def test_explain_without_a_report_cannot_trace_rendered_files():
    cause = explained([{"rule": "check.schema.type", "path": DS + "defaults.yaml", "message": "x"}])[0]["cause"]
    assert cause["kind"] == "unknown"


def test_explain_handles_reports_without_sources(tmp_path):
    out = render_to(tmp_path)
    report = json.loads((out / lzctl.REPORT_NAME).read_text())
    del report["sources"]
    finding = {"rule": "check.schema.type", "path": DS + "defaults.yaml", "message": "x"}
    assert explained([finding], report)[0]["cause"]["kind"] == "vendored"
    assert explained([{**finding, "path": "nope.yaml"}], report)[0]["cause"]["kind"] == "unknown"


def test_explain_does_not_mutate_or_drop_findings():
    findings = [{"rule": "check.hcl.suppression", "path": "main.tf", "message": "m"}]
    result = explained(findings)
    assert result[0]["cause"]["kind"] == "template" and {k: result[0][k] for k in findings[0]} == findings[0]
    assert "cause" not in findings[0]


def test_cli_explain_checks_the_directory_itself(tmp_path):
    out = render_to(tmp_path)
    (out / "stray.txt").write_text("x")
    result = run_cli("explain", str(out))
    assert result.returncode == 0, result.stderr
    [item] = json.loads(result.stdout)["explained"]
    assert item["path"] == "stray.txt" and item["cause"]["kind"] == "integrity"


def test_cli_explain_reads_findings_from_a_file_and_stdin(tmp_path):
    payload = json.dumps({"valid": False, "findings": [{"rule": "schema.type", "path": "organization.id", "message": "m"}]})
    (tmp_path / "f.json").write_text(payload)
    from_file = run_cli("explain", "--findings", str(tmp_path / "f.json"))
    from_stdin = subprocess.run([sys.executable, str(_lzctl.LZCTL), "explain", "--findings", "-"], input=payload, capture_output=True, text=True)
    for result in (from_file, from_stdin):
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["explained"][0]["cause"]["spec_fields"] == ["organization.id"]


def test_cli_explain_errors_exit_two(tmp_path):
    (tmp_path / "bad.json").write_text('{"findings": [{"rule": 1}]}')
    assert run_cli("explain").returncode == 2
    assert run_cli("explain", str(tmp_path / "missing")).returncode == 2
    assert run_cli("explain", "--findings", str(tmp_path / "missing.json")).returncode == 2
    assert run_cli("explain", "--findings", str(tmp_path / "bad.json")).returncode == 2
