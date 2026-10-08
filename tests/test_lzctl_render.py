"""Tests for `lzctl render` (GCP, FAST classic dataset)."""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import validators

import _lzctl

lzctl = _lzctl.load()
ROOT = _lzctl.ROOT
VALID_DIR = ROOT / "evals/gcp/valid"
GOLDEN = ROOT / "evals/gcp/golden/render-hashes.json"
RENDERABLE = ["starter", "standard"]
DS = "datasets/landing-zone/"


def load(name: str) -> dict:
    return json.loads((VALID_DIR / f"{name}.spec.json").read_text())


def mutated(name: str, change) -> dict:
    spec = copy.deepcopy(load(name))
    change(spec)
    return spec


@pytest.fixture(scope="module")
def rendered():
    return {name: lzctl.render_spec(load(name)) for name in RENDERABLE}


def test_render_is_deterministic():
    spec = load("standard")
    first, report1 = lzctl.render_spec(spec)
    second, report2 = lzctl.render_spec(copy.deepcopy(spec))
    assert first == second
    assert report1 == report2


def test_render_does_not_depend_on_list_order():
    shuffled = mutated(
        "standard",
        lambda s: (
            s["hierarchy"].update(environments=["prod", "dev", "stage"], business_units=["platform", "payments"]),
        ),
    )
    assert lzctl.render_spec(shuffled)[1]["output_hash"] == lzctl.render_spec(load("standard"))[1]["output_hash"]


def test_render_has_no_timestamps_or_absolute_paths(rendered):
    for files, report in rendered.values():
        blob = json.dumps(report) + b"".join(files.values()).decode()
        assert not re.search(r"20\d\d-\d\d-\d\dT", blob)
        assert str(ROOT) not in blob and "/Users/" not in blob


def test_golden_output_hashes():
    actual = {name: lzctl.render_spec(load(name))[1]["output_hash"] for name in RENDERABLE}
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
    assert actual == json.loads(GOLDEN.read_text()), "rendered output changed; review it, then rerun with UPDATE_GOLDEN=1"


def test_rendered_yaml_validates_against_upstream_schemas(rendered):
    schemas = ROOT / ".agents/skills/landing-zone/templates/gcp/fast-v59.0.0/upstream/schemas"
    checked = 0
    for files, _ in rendered.values():
        for path, data in files.items():
            if not path.endswith((".yaml", ".yml")):
                continue
            declared = re.search(rb"yaml-language-server: \$schema=\S*?([\w-]+\.schema\.json)", data)
            # Some upstream files hold only comments; an empty factory file means an empty map.
            document = yaml.safe_load(data) or {}
            if declared is None:
                continue
            schema = json.loads((schemas / declared.group(1).decode()).read_text())
            validators.validator_for(schema)(schema).validate(document)
            checked += 1
    assert checked >= 50


def test_values_land_where_the_spec_says(rendered):
    files, _ = rendered["standard"]
    defaults = yaml.safe_load(files[DS + "defaults.yaml"])
    assert defaults["global"]["billing_account"] == "000000-000000-000000"
    assert defaults["global"]["organization"] == {"domain": "example.com", "id": 123456789012, "customer_id": "C0123abcd"}
    assert defaults["projects"]["defaults"]["prefix"] == "acme"
    assert defaults["context"]["locations"]["primary"] == "us-central1"
    assert defaults["context"]["iam_principals"]["gcp-organization-admins"] == "group:gcp-org-admins@example.com"

    log = yaml.safe_load(files[DS + "projects/core/log-0.yaml"])["log_buckets"]
    assert log["audit-logs"] == {"log_analytics": {"enable": True}, "retention": 365}
    assert log["iam"] == {"retention": 365}
    assert log["vpc-sc"]["retention"] == 31  # untouched upstream value


def test_archive_destination_leaves_log_analytics_off():
    files, _ = lzctl.render_spec(mutated("standard", lambda s: s["logging"].update(audit_destination="archive")))
    assert yaml.safe_load(files[DS + "projects/core/log-0.yaml"])["log_buckets"]["audit-logs"] == {"retention": 365}


def test_environments_drive_folders_and_tag_values(rendered):
    std, _ = rendered["standard"]
    assert {p for p in std if re.fullmatch(DS + r"folders/(networking|security)/[a-z]+/\.config\.yaml", p)} == {
        DS + f"folders/{kind}/{env}/.config.yaml" for kind in ("networking", "security") for env in ("dev", "stage", "prod")
    }
    assert set(yaml.safe_load(std[DS + "organization/tags/environment.yaml"])["values"]) == {"development", "staging", "production"}

    start, _ = rendered["starter"]
    assert not any("/prod/" in p or "/stage/" in p for p in start)
    assert set(yaml.safe_load(start[DS + "organization/tags/environment.yaml"])["values"]) == {"development"}
    folder = yaml.safe_load(std[DS + "folders/security/stage/.config.yaml"])
    assert folder == {"name": "Staging", "parent": "$folder_ids:security", "tag_bindings": {"environment": "$tag_values:environment/staging"}}


def test_business_units_become_team_folders(rendered):
    std, _ = rendered["standard"]
    assert yaml.safe_load(std[DS + "folders/teams/payments/.config.yaml"]) == {"name": "payments"}
    assert DS + "folders/teams/platform/.config.yaml" in std
    assert not any("folders/teams/" in p and p != DS + "folders/teams/.config.yaml" for p in rendered["starter"][0])


def test_unchanged_upstream_files_are_byte_identical(rendered):
    upstream = ROOT / ".agents/skills/landing-zone/templates/gcp/fast-v59.0.0/upstream/datasets/classic"
    files, _ = rendered["standard"]
    changed = {"defaults.yaml", "projects/core/log-0.yaml", "organization/tags/environment.yaml"}
    compared = 0
    for path in upstream.rglob("*"):
        relative = path.relative_to(upstream).as_posix()
        if not path.is_file() or relative in changed or re.match(r"folders/(networking|security)/[a-z]+/", relative):
            continue
        assert files[DS + relative] == path.read_bytes(), relative
        compared += 1
    assert compared >= 30


def test_tfvars_points_at_the_rendered_dataset(rendered):
    text = rendered["standard"][0]["0-org-setup.auto.tfvars"].decode()
    assert 'dataset = "datasets/landing-zone"' in text


def test_report_lists_what_is_not_rendered(rendered):
    std = rendered["standard"][1]["not_rendered_yet"]
    assert std["network.topology"] and std["network.regions[1:]"] and std["extensions.gcp.hub_connectivity"]
    start = rendered["starter"][1]["not_rendered_yet"]
    assert "network.regions[1:]" not in start and "extensions.gcp.hub_connectivity" not in start
    assert "network.topology" in start and "network.cidr_supernet" in start


def test_report_digests_match_the_files(rendered):
    import hashlib

    files, report = rendered["standard"]
    assert set(report["files"]) == set(files)
    assert all(hashlib.sha256(files[p]).hexdigest() == d for p, d in report["files"].items())
    assert report["baseline"]["commit"] == "23171949f616be9f643e082e18770eab1bad3d85"


def test_regulated_is_refused_until_hardened_dataset_exists():
    with pytest.raises(lzctl.RenderError, match="hardened"):
        lzctl.render_spec(load("regulated"))


def test_invalid_spec_is_refused():
    with pytest.raises(lzctl.RenderError, match="invalid"):
        lzctl.render_spec(mutated("standard", lambda s: s["logging"].update(retention_days=1)))


def test_tampered_upstream_file_is_refused(tmp_path, monkeypatch):
    copy_root = tmp_path / "templates"
    shutil.copytree(lzctl.TEMPLATE_DIR, copy_root)
    victim = copy_root / "gcp/fast-v59.0.0/upstream/datasets/classic/organization/org-policies/iam.yaml"
    victim.write_text(victim.read_text() + "\n# tampered\n")
    monkeypatch.setattr(lzctl, "TEMPLATE_DIR", copy_root)
    with pytest.raises(lzctl.RenderError, match="MANIFEST"):
        lzctl.render_spec(load("standard"))


def test_manifest_covers_every_vendored_file():
    root = lzctl.TEMPLATE_DIR / "gcp/fast-v59.0.0"
    manifest = json.loads((root / "MANIFEST.json").read_text())
    on_disk = {p.relative_to(root / "upstream").as_posix() for p in (root / "upstream").rglob("*") if p.is_file()}
    assert on_disk == set(manifest["files"])
    assert manifest["tag"] == "v59.0.0" and manifest["license"] == "Apache-2.0"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_lzctl.LZCTL), *args], capture_output=True, text=True)


def test_cli_render_writes_files_and_report(tmp_path):
    out = tmp_path / "out"
    result = run_cli("render", str(VALID_DIR / "standard.spec.json"), "--out", str(out))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["rendered"] is True
    report = json.loads((out / "render-report.json").read_text())
    assert report["output_hash"] == summary["output_hash"]
    assert (out / "0-org-setup.auto.tfvars").is_file()
    assert (out / DS / "defaults.yaml").is_file()


def test_cli_render_refuses_a_non_empty_directory(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    result = run_cli("render", str(VALID_DIR / "standard.spec.json"), "--out", str(tmp_path))
    assert result.returncode == 2
    assert (tmp_path / "keep.txt").read_text() == "x"


def test_cli_render_exit_one_when_refused(tmp_path):
    result = run_cli("render", str(VALID_DIR / "regulated.spec.json"), "--out", str(tmp_path / "out"))
    assert result.returncode == 1
    assert json.loads(result.stdout)["rendered"] is False
    assert not (tmp_path / "out").exists()
