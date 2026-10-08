"""Tests for tools/check_workflows.py (the docs/CICD.md policy checker)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/check_workflows.py"
_spec = importlib.util.spec_from_file_location("check_workflows", TOOL)
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)

GOOD = """\
name: "CI: Example"
on:
  pull_request:
permissions: {}
jobs:
  test:
    name: Test
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - run: echo hi
"""


def write(tmp_path: Path, text: str = GOOD, name: str = "ci-example.yml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def messages(path: Path) -> str:
    return "\n".join(cw.check_workflow(path))


def test_repo_workflows_follow_the_policy():
    assert [m for f in sorted((ROOT / ".github/workflows").glob("*.yml")) for m in cw.check_workflow(f)] == []


def test_a_conforming_workflow_is_clean(tmp_path):
    assert cw.check_workflow(write(tmp_path)) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda t: t.replace("permissions: {}\njobs", "jobs"), "permissions: {}"),
        (lambda t: t.replace("permissions: {}\njobs", "permissions: read-all\njobs"), "permissions: {}"),
        (lambda t: t.replace("    timeout-minutes: 5\n", ""), "timeout-minutes"),
        (lambda t: t.replace("ubuntu-24.04", "ubuntu-latest"), "ubuntu-24.04"),
        (lambda t: t.replace("@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1", "@v7"), "pinned to a full commit SHA"),
        (lambda t: t.replace(" # v7.0.1", ""), "'# vX.Y.Z' comment"),
        (lambda t: t.replace(" # v7.0.1", " # latest"), "'# vX.Y.Z' comment"),
        (lambda t: t.replace("actions/checkout", "evil/checkout"), "publisher 'evil' is not allowed"),
        (lambda t: t.replace("  pull_request:\n", "  pull_request_target:\n"), "pull_request_target"),
        (lambda t: t.replace('"CI: Example"', '"Example"'), "name must start with 'CI: '"),
        (lambda t: t.replace("  test:", "  Run_Tests:"), "kebab-case"),
        (lambda t: t.replace("      - run: echo hi", "      - uses: docker://alpine:3"), "docker://"),
    ],
)
def test_each_rule_is_enforced(tmp_path, change, expected):
    assert expected in messages(write(tmp_path, change(GOOD)))


@pytest.mark.parametrize("name", ["example.yml", "build-thing.yml", "ci_example.yml", "CI-example.yml", "ci-example.yaml"])
def test_file_names_follow_the_convention(tmp_path, name):
    assert "file name must be" in messages(write(tmp_path, name=name))


def test_category_must_match_the_workflow_name(tmp_path):
    assert "name must start with 'Ops: '" in messages(write(tmp_path, name="ops-example.yml"))


def test_local_actions_and_reusable_workflow_calls_are_allowed(tmp_path):
    text = GOOD.replace("      - run: echo hi", "      - uses: ./.github/actions/thing") + (
        "  call:\n    uses: ./.github/workflows/reusable-x.yml\n"
    )
    assert cw.check_workflow(write(tmp_path, text)) == []


def test_invalid_yaml_is_a_finding(tmp_path):
    assert "not valid YAML" in messages(write(tmp_path, "name: [unclosed\n"))


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


def test_cli_exit_codes(tmp_path):
    assert run(str(write(tmp_path))).returncode == 0
    bad = write(tmp_path, GOOD.replace("ubuntu-24.04", "ubuntu-latest"), "ci-bad.yml")
    assert run(str(bad)).returncode == 1
    assert run(str(tmp_path / "missing")).returncode == 2
    assert run(str(tmp_path / "empty-dir-that-does-not-exist")).returncode == 2
