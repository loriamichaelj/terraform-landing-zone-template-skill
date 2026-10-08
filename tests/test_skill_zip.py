"""Tests for the two delivery paths (ADR-027): the skill used from the repository, and the release zip.

The repository path is the baseline. The zip must behave identically once extracted, with nothing
from the repository around it.
"""

import hashlib
import json
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

import _lzctl

ROOT = _lzctl.ROOT
sys.path.insert(0, str(ROOT / "tools"))
import build_skill_zip  # noqa: E402

SKILL = build_skill_zip.SKILL
VALID_DIR = ROOT / "evals/gcp/valid"
GOLDEN = json.loads((ROOT / "evals/gcp/golden/render-hashes.json").read_text())
RENDERABLE = sorted(GOLDEN)


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


@pytest.fixture(scope="module")
def archive(tmp_path_factory) -> Path:
    return build_skill_zip.build(SKILL, tmp_path_factory.mktemp("dist"), "0.0.1")


@pytest.fixture(scope="module")
def extracted(archive, tmp_path_factory) -> Path:
    """The zip extracted the way a user's machine would, by a real unzip so mode bits are honored."""
    if not shutil.which("unzip"):
        pytest.skip("unzip is not installed")
    target = tmp_path_factory.mktemp("extracted")
    subprocess.run(["unzip", "-q", str(archive), "-d", str(target)], check=True)
    return target / "landing-zone"


# The skill's own metadata, which both paths and every platform read.


def test_skill_metadata_meets_the_spec_and_the_strictest_platform_limit():
    assert build_skill_zip.validate(SKILL) == []


def test_skill_metadata_states_its_runtime_needs():
    data = build_skill_zip.frontmatter(SKILL)
    for needed in ("Python 3.11", "jsonschema", "jinja2", "PyYAML", "not_applicable"):
        assert needed in data["compatibility"]


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"name": "Landing-Zone"}, "name"),
        ({"name": "something-else"}, "must match the folder name"),
        ({"description": "x" * 201}, "description is 201"),
        ({"description": ""}, "description is required"),
        ({"compatibility": "x" * 501}, "compatibility"),
    ],
)
def test_validate_rejects_bad_metadata(tmp_path, change, expected):
    skill = tmp_path / "landing-zone"
    skill.mkdir()
    data = {"name": "landing-zone", "description": "ok", **change}
    (skill / "SKILL.md").write_text(f"---\n{yaml.safe_dump(data)}---\n\nbody\n")
    assert any(expected in finding for finding in build_skill_zip.validate(skill))


# The zip's shape.


def test_zip_has_one_top_level_folder_named_after_the_skill(archive):
    names = zipfile.ZipFile(archive).namelist()
    assert {name.split("/")[0] for name in names} == {"landing-zone"}
    assert "landing-zone/SKILL.md" in names


def test_zip_holds_the_same_files_as_the_skill_and_nothing_else(archive):
    expected = {f"landing-zone/{p.relative_to(SKILL).as_posix()}" for p in build_skill_zip.files(SKILL)}
    names = zipfile.ZipFile(archive).namelist()
    assert set(names) == expected
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert names == sorted(names)


def test_zip_entries_are_normalized(archive):
    for info in zipfile.ZipFile(archive).infolist():
        assert info.date_time == build_skill_zip.FIXED_TIME
        mode = info.external_attr >> 16
        assert stat.S_ISREG(mode), "no symlinks or directories"
        assert stat.S_IMODE(mode) in (0o644, 0o755)


def test_lzctl_keeps_its_executable_bit_in_the_zip(archive):
    info = zipfile.ZipFile(archive).getinfo("landing-zone/scripts/lzctl")
    assert stat.S_IMODE(info.external_attr >> 16) == 0o755


def test_zip_is_reproducible(tmp_path):
    first = build_skill_zip.build(SKILL, tmp_path / "a", "0.0.1")
    second = build_skill_zip.build(SKILL, tmp_path / "b", "0.0.1")
    assert first.read_bytes() == second.read_bytes()


def test_checksum_file_matches_the_archive(archive):
    recorded = (archive.parent / f"{archive.name}.sha256").read_text().split()
    assert recorded == [hashlib.sha256(archive.read_bytes()).hexdigest(), archive.name]


def test_build_refuses_an_invalid_skill(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/build_skill_zip.py"), "--version", "1.0.0", "--out", str(tmp_path), "--skill", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert not list(tmp_path.glob("*.zip"))


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "latest"])
def test_build_rejects_a_malformed_version(tmp_path, version):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/build_skill_zip.py"), "--version", version, "--out", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


# Behavior after extraction: the zip path must match the repository path.


def test_extracted_lzctl_is_executable(extracted):
    assert (extracted / "scripts/lzctl").stat().st_mode & stat.S_IXUSR


def test_extracted_skill_passes_doctor(extracted):
    result = run(extracted / "scripts/lzctl", "doctor", "--format", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    required = {c["name"] for c in json.loads(result.stdout)["checks"] if c["required"]}
    assert {"python>=3.11", "jsonschema", "jinja2", "yaml"} <= required


@pytest.mark.parametrize("name", RENDERABLE)
def test_zip_renders_the_same_bytes_as_the_repository(extracted, tmp_path, name):
    spec = VALID_DIR / f"{name}.spec.json"
    from_zip, from_repo = tmp_path / "zip", tmp_path / "repo"
    zip_run = run(extracted / "scripts/lzctl", "render", str(spec), "--out", str(from_zip))
    repo_run = run(SKILL / "scripts/lzctl", "render", str(spec), "--out", str(from_repo))
    assert zip_run.returncode == 0, zip_run.stderr
    assert repo_run.returncode == 0, repo_run.stderr
    assert json.loads(zip_run.stdout)["output_hash"] == json.loads(repo_run.stdout)["output_hash"] == GOLDEN[name]
    tree = lambda base: {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    assert tree(from_zip) == tree(from_repo)


def test_zip_checks_its_own_render(extracted, tmp_path):
    out = tmp_path / "out"
    spec = VALID_DIR / "standard.spec.json"
    assert run(extracted / "scripts/lzctl", "render", str(spec), "--out", str(out)).returncode == 0
    result = run(extracted / "scripts/lzctl", "check", str(out))
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, (dict, list))
