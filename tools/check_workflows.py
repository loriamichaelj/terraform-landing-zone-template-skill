#!/usr/bin/env python3
"""Checks .github/workflows against the repo's own rules in docs/CICD.md.

actionlint and zizmor cover syntax and security; this covers conventions they can't know:
file and workflow naming, `permissions: {}`, job timeouts, the runner image, SHA-pinned actions
with a version comment, and allowed publishers.

Usage: check_workflows.py [workflow files or directories...]   (default: .github/workflows)
Exit codes: 0 clean, 1 findings, 2 usage error. Needs PyYAML.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

CATEGORIES = {"ci": "CI", "cd": "CD", "ops": "Ops", "release": "Release", "reusable": "Reusable"}
ALLOWED_PUBLISHERS = {"actions", "google-github-actions", "hashicorp", "aquasecurity", "terraform-linters"}
RUNNER = "ubuntu-24.04"

FILE_NAME = re.compile(r"^(?P<category>[a-z]+)-[a-z0-9]+(-[a-z0-9]+)*\.yml$")
USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>[^\s#]+)\s*(?P<comment>#.*)?$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^#\s*v\d+(\.\d+){0,2}\s*$")


def check_workflow(path: Path) -> list[str]:
    """Return one message per rule the workflow breaks."""
    findings: list[str] = []

    def fail(message: str) -> None:
        findings.append(f"{path.name}: {message}")

    match = FILE_NAME.match(path.name)
    category = match.group("category") if match else None
    if category not in CATEGORIES:
        fail(f"file name must be <category>-<subject>.yml with category one of {sorted(CATEGORIES)}")

    text = path.read_text(encoding="utf-8")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"{path.name}: not valid YAML: {str(exc).splitlines()[0]}"]
    if not isinstance(document, dict):
        return [f"{path.name}: not a workflow mapping"]

    name = document.get("name")
    if category in CATEGORIES and not (isinstance(name, str) and name.startswith(f"{CATEGORIES[category]}: ")):
        fail(f"name must start with '{CATEGORIES.get(category)}: ' (got {name!r})")

    # YAML 1.1 reads the bare key `on` as True.
    triggers = document.get("on", document.get(True))
    if isinstance(triggers, dict) and "pull_request_target" in triggers or triggers == "pull_request_target" \
            or isinstance(triggers, list) and "pull_request_target" in triggers:
        fail("pull_request_target is not allowed")

    if document.get("permissions") != {}:
        fail("top-level `permissions: {}` is required; grant permissions per job")

    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        fail("no jobs")
        jobs = {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", str(job_id)):
            fail(f"job id '{job_id}' must be kebab-case")
        if "uses" not in job:  # a reusable-workflow call has no runner or timeout of its own
            if "timeout-minutes" not in job:
                fail(f"job '{job_id}' needs timeout-minutes")
            if job.get("runs-on") != RUNNER:
                fail(f"job '{job_id}' must run on {RUNNER} (got {job.get('runs-on')!r})")

    for number, line in enumerate(text.splitlines(), start=1):
        found = USES_LINE.match(line)
        if not found:
            continue
        ref, comment = found.group("ref"), found.group("comment") or ""
        if ref.startswith("./"):
            continue
        if ref.startswith("docker://"):
            fail(f"line {number}: docker:// actions are not allowed")
            continue
        if not PINNED.match(ref):
            fail(f"line {number}: {ref.split('@')[0]} must be pinned to a full commit SHA")
        elif not VERSION_COMMENT.match(comment):
            fail(f"line {number}: {ref.split('@')[0]} needs a trailing '# vX.Y.Z' comment")
        publisher = ref.split("/")[0]
        if publisher not in ALLOWED_PUBLISHERS:
            fail(f"line {number}: publisher '{publisher}' is not allowed; record the decision in ADR.md first")
    return findings


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or [Path(".github/workflows")]
    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            files += sorted(target.glob("*.yml")) + sorted(target.glob("*.yaml"))
        elif target.is_file():
            files.append(target)
        else:
            print(f"check_workflows: {target} not found", file=sys.stderr)
            return 2
    if not files:
        print("check_workflows: no workflow files found", file=sys.stderr)
        return 2
    findings = [message for file in files for message in check_workflow(file)]
    for message in findings:
        print(message)
    if not findings:
        print(f"{len(files)} workflow file(s) follow docs/CICD.md")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
