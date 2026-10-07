#!/usr/bin/env python3
import json
import os
import re
import shutil
import sys
from pathlib import Path

ACR_REGISTRY = os.environ["ACR_REGISTRY"].strip("/")
ACR_NAMESPACE = os.environ["ACR_NAMESPACE"].strip("/")
ACR_PREFIX = f"{ACR_REGISTRY}/{ACR_NAMESPACE}"
SRC_PREFIX = "ghcr.io/hassio-addons"
REPO_NAME = os.environ.get("REPO_NAME", "Home Assistant Community Apps (Mirror)")
REPO_URL = os.environ.get(
    "REPO_URL", "https://github.com/Desmond-Dong/offcial-apps-mirror"
)
REPO_MAINTAINER = os.environ.get("REPO_MAINTAINER", "Desmond-Dong")
EXCLUDE = {".git", ".github"}
IMAGE_RE = re.compile(
    r"^(\s*image:\s*)(ghcr\.io/hassio-addons/\S+)[ \t]*$", re.MULTILINE
)


def rewrite_image(match):
    value = match.group(2)[len(SRC_PREFIX) + 1 :]
    if value.endswith("/{arch}"):
        value = value[: -len("/{arch}")] + "-{arch}"
    return f"{match.group(1)}{ACR_PREFIX}/{value}"


def sync_tree(src, dst, top=False):
    src_names = {child.name for child in src.iterdir()}
    if dst.is_dir():
        for child in list(dst.iterdir()):
            if top and child.name in EXCLUDE:
                continue
            if child.name in src_names:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    for child in src.iterdir():
        if top and child.name in EXCLUDE:
            continue
        target = dst / child.name
        if child.is_dir() and not child.is_symlink():
            target.mkdir(exist_ok=True)
            sync_tree(child, target)
        else:
            shutil.copy2(child, target)


def rewrite_file(path):
    text = path.read_text(encoding="utf-8")
    updated = IMAGE_RE.sub(rewrite_image, text)
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")
        return True
    return False


def main():
    if len(sys.argv) != 3:
        print("usage: mirror.py <upstream-dir> <dest-dir>", file=sys.stderr)
        return 2
    upstream = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    if not upstream.is_dir() or not (upstream / "repository.json").is_file():
        print(
            f"error: {upstream} is not a checkout of the upstream repository",
            file=sys.stderr,
        )
        return 1
    sync_tree(upstream, dest, top=True)
    rewritten = 0
    for config in sorted(dest.glob("*/config.yaml")):
        if rewrite_file(config):
            rewritten += 1
    apps = dest / ".apps.yml"
    if apps.is_file() and rewrite_file(apps):
        rewritten += 1
    repository = {
        "name": REPO_NAME,
        "url": REPO_URL,
        "maintainer": REPO_MAINTAINER,
    }
    (dest / "repository.json").write_text(
        json.dumps(repository, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    readme = dest / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        updated = text.replace(
            "https://github.com/hassio-addons/repository", REPO_URL.rstrip("/")
        )
        if updated != text:
            readme.write_text(updated, encoding="utf-8", newline="\n")
    print(f"mirrored upstream tree into {dest}")
    print(f"rewrote image references in {rewritten} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
