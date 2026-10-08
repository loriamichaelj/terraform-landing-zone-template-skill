"""Tests for `lzctl check` on rendered GCP output."""

import json
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
    assert {status[name] for name in lzctl.NOT_APPLICABLE} == {"not_applicable"}


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
