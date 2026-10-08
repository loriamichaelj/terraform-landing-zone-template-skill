#!/usr/bin/env python3
"""Vendor a pinned Cloud Foundation Fabric FAST dataset and its schemas.

Downloads fast/stages/0-org-setup/datasets/<dataset> and the stage's JSON schemas
at one commit, and writes them unmodified under:

  .agents/skills/landing-zone/templates/gcp/fast-<tag>/upstream/

plus MANIFEST.json (tag, commit, per-file SHA-256). The overlay templates next to
`upstream/` are written by hand; this tool never touches them.

Usage: tools/vendor_fast.py <tag> <commit-sha> [--dataset classic]
Set GITHUB_TOKEN to avoid API rate limits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

REPO = "GoogleCloudPlatform/cloud-foundation-fabric"
STAGE = "fast/stages/0-org-setup"
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / ".agents/skills/landing-zone/templates/gcp"


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "lz-vendor-fast"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag")
    parser.add_argument("commit", help="full commit SHA the tag points to")
    parser.add_argument("--dataset", default="classic")
    args = parser.parse_args()

    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{args.commit}?recursive=1"))
    if tree.get("truncated"):
        print("tree listing truncated", file=sys.stderr)
        return 2

    dataset_prefix = f"{STAGE}/datasets/{args.dataset}/"
    schema_prefix = f"{STAGE}/schemas/"
    wanted = {}
    for item in tree["tree"]:
        path = item["path"]
        if item["type"] != "blob":
            continue
        if path.startswith(dataset_prefix):
            wanted[path] = f"datasets/{args.dataset}/{path[len(dataset_prefix):]}"
        elif path.startswith(schema_prefix) and path.endswith(".schema.json"):
            wanted[path] = f"schemas/{path[len(schema_prefix):]}"
    wanted["LICENSE"] = "LICENSE"
    if len(wanted) < 10:
        print(f"suspiciously few files ({len(wanted)}); wrong commit or dataset?", file=sys.stderr)
        return 2

    out = TEMPLATES / f"fast-{args.tag}"
    upstream = out / "upstream"
    if upstream.exists():
        shutil.rmtree(upstream)

    files = {}
    for source, relative in sorted(wanted.items()):
        data = _get(f"https://raw.githubusercontent.com/{REPO}/{args.commit}/{source}")
        target = upstream / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[relative] = hashlib.sha256(data).hexdigest()

    manifest = {
        "source": f"https://github.com/{REPO}",
        "tag": args.tag,
        "commit": args.commit,
        "license": "Apache-2.0",
        "dataset": args.dataset,
        "files": files,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"vendored {len(files)} files into {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
