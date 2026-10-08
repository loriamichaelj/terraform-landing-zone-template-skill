#!/usr/bin/env python3
"""Builds the release zip of the landing-zone skill (ADR-027).

The archive holds one top-level folder, `landing-zone/`, because some platforms reject a zip whose
folder name does not match the skill name. It is built to be reproducible: entries sorted, a fixed
timestamp, normalized modes, no `__pycache__`, and the executable bit kept on `scripts/lzctl`.

Usage: build_skill_zip.py --version X.Y.Z [--out DIR] [--skill DIR]
Writes `landing-zone-<version>.zip` and `landing-zone-<version>.zip.sha256` into DIR (default: dist).
Exit codes: 0 built, 1 skill failed validation, 2 usage error. Needs PyYAML.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".agents/skills/landing-zone"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# The Agent Skills spec allows 1024; 200 is the lowest cap reported for any platform, so stay under it.
MAX_NAME, MAX_DESCRIPTION, MAX_COMPATIBILITY = 64, 200, 500
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the earliest timestamp a zip can store
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def frontmatter(skill: Path) -> dict:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        raise ValueError("SKILL.md has no YAML frontmatter")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter is not a mapping")
    return data


def validate(skill: Path) -> list[str]:
    """Checks the frontmatter against the Agent Skills spec and the stricter limits above."""
    try:
        data = frontmatter(skill)
    except (OSError, ValueError, yaml.YAMLError) as error:
        return [f"SKILL.md: {error}"]
    findings = []
    name, description, compatibility = data.get("name"), data.get("description"), data.get("compatibility")
    if not isinstance(name, str) or not NAME.match(name) or len(name) > MAX_NAME:
        findings.append(f"name {name!r} must be lowercase letters, digits and single hyphens, at most {MAX_NAME} characters")
    elif name != skill.name:
        findings.append(f"name {name!r} must match the folder name {skill.name!r}")
    if not isinstance(description, str) or not description.strip():
        findings.append("description is required")
    elif len(description) > MAX_DESCRIPTION:
        findings.append(f"description is {len(description)} characters; keep it at most {MAX_DESCRIPTION}")
    if compatibility is not None and (not isinstance(compatibility, str) or not 1 <= len(compatibility) <= MAX_COMPATIBILITY):
        findings.append(f"compatibility must be 1 to {MAX_COMPATIBILITY} characters")
    return findings


def files(skill: Path) -> list[Path]:
    """Regular files under the skill (symlinks followed), sorted by relative path."""
    found = [
        path
        for path in skill.rglob("*")
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(skill).parts) and path.suffix not in SKIP_SUFFIXES
    ]
    return sorted(found, key=lambda path: path.relative_to(skill).as_posix())


def build(skill: Path, out: Path, version: str) -> Path:
    archive = out / f"landing-zone-{version}.zip"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files(skill):
            info = zipfile.ZipInfo(f"{skill.name}/{path.relative_to(skill).as_posix()}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.create_system = 3  # Unix, so extractors read the mode bits
            zf.writestr(info, path.read_bytes(), compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n")
    return archive


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True, help="release version, X.Y.Z")
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument("--skill", type=Path, default=SKILL)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return 2 if error.code else 0
    if not VERSION.match(args.version):
        print(f"--version must look like 1.2.3, got {args.version!r}", file=sys.stderr)
        return 2
    skill = args.skill.resolve()
    findings = validate(skill)
    if findings:
        for finding in findings:
            print(f"{skill / 'SKILL.md'}: {finding}", file=sys.stderr)
        return 1
    archive = build(skill, args.out, args.version)
    print(f"{archive} ({archive.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
