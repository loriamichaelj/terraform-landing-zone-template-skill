"""Tests for tools/check_docs.py (links, anchors and the ADR index)."""

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools/check_docs.py"
_spec = importlib.util.spec_from_file_location("check_docs", TOOL)
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)


@pytest.fixture
def repo(tmp_path):
    """A copy of the real docs, so tests break the real structure."""
    for relative in ("README.md", "docs/ADR.md", "docs/DESIGN.md", "docs/CICD.md", "CONTRIBUTING.md"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, target)
    return tmp_path


def findings(root: Path) -> list[str]:
    files = sorted(root.rglob("*.md"))
    return cd.check_links(root, files) + cd.check_adr_index(root)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) >= 1, old
    path.write_text(text.replace(old, new, 1))


def test_repo_docs_are_consistent():
    assert cd.main([str(ROOT)]) == 0


def test_slug_matches_github():
    assert cd.slug("ADR-002: Domain knowledge ships as a portable Agent Skill; deterministic work lives in `lzctl`") == (
        "adr-002-domain-knowledge-ships-as-a-portable-agent-skill-deterministic-work-lives-in-lzctl"
    )
    assert cd.slug("Cost estimate") == "cost-estimate"
    assert cd.slug("GCP and GitHub environment reference") == "gcp-and-github-environment-reference"


def test_copy_of_the_docs_is_clean(repo):
    # Some links point at files outside the copy; only the ADR index must be clean here.
    assert cd.check_adr_index(repo) == []


def test_missing_link_target_is_found(tmp_path):
    (tmp_path / "a.md").write_text("[x](missing.md) and ![i](img/none.png)\n")
    assert [m.split(": ", 1)[1] for m in findings(tmp_path)] == ["link target not found: missing.md", "link target not found: img/none.png"]


def test_missing_anchor_is_found(tmp_path):
    (tmp_path / "a.md").write_text("# Title\n\n[ok](#title) [bad](#nope) [other](b.md#section) [bad2](b.md#absent)\n")
    (tmp_path / "b.md").write_text("## Section\n")
    assert [m.split(": ", 1)[1] for m in findings(tmp_path)] == ["no heading for anchor: #nope", "no heading for anchor: b.md#absent"]


def test_duplicate_headings_get_numbered_anchors(tmp_path):
    (tmp_path / "a.md").write_text("## Same\n\n## Same\n\n[one](#same) [two](#same-1) [three](#same-2)\n")
    assert [m.split(": ", 1)[1] for m in findings(tmp_path)] == ["no heading for anchor: #same-2"]


def test_external_links_code_and_fences_are_ignored(tmp_path):
    (tmp_path / "a.md").write_text(
        "[web](https://example.com/x) [mail](mailto:a@b.c) `[code](nope.md)`\n\n```\n[fenced](nope.md)\n# not-a-heading\n```\n"
    )
    assert findings(tmp_path) == []


def test_links_cannot_escape_the_repo(tmp_path):
    (tmp_path / "outside.md").write_text("# Hi\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.md").write_text("[x](../outside.md)\n")
    assert "link target not found" in findings(root)[0]


def test_adr_without_an_index_row_is_found(repo):
    text = (repo / "docs/ADR.md").read_text()
    row = next(line for line in text.splitlines() if line.startswith("| [021]"))
    (repo / "docs/ADR.md").write_text(text.replace(row + "\n", ""))
    assert any("exactly one row per ADR heading" in m for m in findings(repo))


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("| Accepted | 2026-10-08 |\n| [022]", "| Proposed | 2026-10-08 |\n| [022]", "ADR-021 index status"),
        ("| `lzctl check` verifies rendered output and says which checks did not run |", "| Renamed |", "ADR-021 index title"),
        ("(#adr-022-trivy-and-checkov-both-scan-rendered-hcl)", "(#adr-022-wrong)", "ADR-022 index anchor"),
        ("## ADR-023: The render report", "## ADR-025: The render report", "numbers must run"),
    ],
)
def test_adr_index_drift_is_found(repo, old, new, expected):
    edit(repo / "docs/ADR.md", old, new)
    assert any(expected in m for m in findings(repo))


def test_adr_without_status_is_found(repo):
    text = (repo / "docs/ADR.md").read_text()
    start = text.index("## ADR-022:")
    status = text.index("**Status:**", start)
    end = text.index("\n", status)
    (repo / "docs/ADR.md").write_text(text[:status] + text[end:])
    assert any("ADR-022 has no **Status:**" in m for m in findings(repo))


def test_readme_adr_count_must_match(repo):
    readme = repo / "README.md"
    readme.write_text(re.sub(r"\b\d+ ADRs\b", "999 ADRs", readme.read_text()))
    assert any("says 999 ADRs" in m for m in findings(repo))


def test_cli_exit_codes(tmp_path):
    (tmp_path / "a.md").write_text("[x](missing.md)\n")
    run = lambda *a: subprocess.run([sys.executable, str(TOOL), *a], capture_output=True, text=True)  # noqa: E731
    assert run(str(ROOT)).returncode == 0
    assert run(str(tmp_path)).returncode == 1
    assert run(str(tmp_path / "nope")).returncode == 2


def test_vendored_upstream_markdown_is_not_checked(tmp_path):
    vendored = tmp_path / "templates/fast/upstream/dataset"
    vendored.mkdir(parents=True)
    (vendored / "README.md").write_text("[broken](../../../../nowhere.md)\n")
    (tmp_path / "a.md").write_text("[ok](a.md)\n")
    assert [p.name for p in cd.markdown_files(tmp_path)] == ["a.md"]
    assert cd.main([str(tmp_path)]) == 0
