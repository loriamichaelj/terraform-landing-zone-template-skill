#!/usr/bin/env python3
"""Checks the repo's markdown: relative links and anchors, and the ADR index.

- Every relative link (and image) resolves to a file in the repo, and every #anchor to a heading.
- docs/ADR.md has one index row per ADR heading, in order, with the same title and status.
- README.md's "N ADRs" matches the number of ADRs.

External links are not fetched: they make CI flaky and say nothing about this repo.

Usage: check_docs.py [repo root]        Exit codes: 0 clean, 1 findings, 2 usage error. Stdlib only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

LINK = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
ADR_HEADING = re.compile(r"^## (ADR-(\d{3})): (?P<title>.+)$")
ADR_STATUS = re.compile(r"^\*\*Status:\*\*\s*(?P<status>Accepted|Proposed|Rejected|Superseded by ADR-\d{3})\b")
ADR_ROW = re.compile(r"^\| \[(?P<num>\d{3})\]\(#(?P<anchor>[^)]+)\) \| (?P<title>.+?) \| (?P<status>[^|]+?) \| (?P<date>[\d-]+) \|$")


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text.strip())


def lines_outside_fences(text: str):
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        seen: dict[str, int] = {}
        found: set[str] = set()
        for _, line in lines_outside_fences(path.read_text(encoding="utf-8")):
            match = HEADING.match(line)
            if match:
                base = slug(match.group("text"))
                count = seen.get(base, 0)
                seen[base] = count + 1
                found.add(base if count == 0 else f"{base}-{count}")
        cache[path] = found
    return cache[path]


def markdown_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True).stdout
        return sorted(root / line for line in out.splitlines() if (root / line).is_file())
    except (OSError, subprocess.CalledProcessError):
        return sorted(p for p in root.rglob("*.md") if ".git" not in p.parts)


def check_links(root: Path, files: list[Path]) -> list[str]:
    findings: list[str] = []
    cache: dict[Path, set[str]] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        for number, line in lines_outside_fences(path.read_text(encoding="utf-8")):
            line = re.sub(r"`[^`]*`", "", line)  # inline code is not a link
            for match in LINK.finditer(line):
                target = match.group("target")
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("//"):
                    continue  # http, https, mailto and other external schemes
                file_part, _, fragment = target.partition("#")
                destination = path if not file_part else (path.parent / unquote(file_part)).resolve()
                where = f"{relative}:{number}"
                if not destination.is_relative_to(root.resolve()) or not destination.exists():
                    findings.append(f"{where}: link target not found: {target}")
                elif fragment and destination.suffix == ".md" and unquote(fragment).lower() not in anchors(destination, cache):
                    findings.append(f"{where}: no heading for anchor: {target}")
    return findings


def check_adr_index(root: Path) -> list[str]:
    adr = root / "docs/ADR.md"
    if not adr.is_file():
        return []
    findings: list[str] = []
    headings: list[tuple[str, str, str, str]] = []  # (number, anchor, title, status)
    rows = []
    current: list | None = None
    for number, line in lines_outside_fences(adr.read_text(encoding="utf-8")):
        heading = ADR_HEADING.match(line)
        if heading:
            current = [heading.group(2), slug(line[3:]), heading.group("title"), None]
            headings.append(current)  # type: ignore[arg-type]
            continue
        status = ADR_STATUS.match(line)
        if status and current is not None and current[3] is None:
            current[3] = status.group("status")
        row = ADR_ROW.match(line)
        if row:
            rows.append((number, row))
    numbers = [int(h[0]) for h in headings]
    if numbers != list(range(1, len(numbers) + 1)):
        findings.append(f"docs/ADR.md: ADR numbers must run 001..{len(numbers):03d} in order (got {numbers})")
    if [r.group("num") for _, r in rows] != [h[0] for h in headings]:
        findings.append("docs/ADR.md: the index must have exactly one row per ADR heading, in order")
    for (_, row), heading in zip(rows, headings):
        label = f"ADR-{heading[0]}"
        if row.group("anchor") != heading[1]:
            findings.append(f"docs/ADR.md: {label} index anchor should be #{heading[1]}")
        if row.group("title") != heading[2]:
            findings.append(f"docs/ADR.md: {label} index title differs from its heading")
        if heading[3] is None:
            findings.append(f"docs/ADR.md: {label} has no **Status:** line")
        elif not row.group("status").startswith(heading[3].split(" ·")[0]):
            findings.append(f"docs/ADR.md: {label} index status '{row.group('status')}' differs from '{heading[3]}'")

    readme = root / "README.md"
    if readme.is_file():
        for claimed in re.findall(r"\b(\d+) ADRs\b", readme.read_text(encoding="utf-8")):
            if int(claimed) != len(headings):
                findings.append(f"README.md: says {claimed} ADRs, but docs/ADR.md has {len(headings)}")
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else ".").resolve()
    if not root.is_dir():
        print(f"check_docs: {root} is not a directory", file=sys.stderr)
        return 2
    files = markdown_files(root)
    findings = check_links(root, files) + check_adr_index(root)
    for message in findings:
        print(message)
    if not findings:
        print(f"{len(files)} markdown file(s): links, anchors and the ADR index are consistent")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
