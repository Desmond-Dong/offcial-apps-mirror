#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path

ACR_REGISTRY = os.environ["ACR_REGISTRY"].strip("/")
ACR_NAMESPACE = os.environ["ACR_NAMESPACE"].strip("/")
ACR_PREFIX = f"{ACR_REGISTRY}/{ACR_NAMESPACE}"
SRC_PREFIX = "ghcr.io/hassio-addons"
ARCH_PLACEHOLDER = "{arch}"
FORCE = os.environ.get("FORCE", "false").lower() == "true"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def parse_config(path):
    image = None
    version = None
    archs = []
    in_arch = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("image:"):
            image = line.split(":", 1)[1].strip()
            in_arch = False
        elif line.startswith("version:"):
            version = line.split(":", 1)[1].strip().strip("\"'")
            in_arch = False
        elif line.startswith("arch:"):
            inline = line.split(":", 1)[1].strip()
            if inline:
                archs = [
                    item.strip() for item in inline.strip("[]").split(",") if item.strip()
                ]
                in_arch = False
            else:
                archs = []
                in_arch = True
        elif in_arch:
            stripped = line.strip()
            if stripped.startswith("- "):
                archs.append(stripped[2:].strip())
            elif stripped:
                in_arch = False
    return image, version, archs


def to_source(image):
    if image.startswith(SRC_PREFIX + "/"):
        return image
    if image.startswith(ACR_PREFIX + "/"):
        rest = image[len(ACR_PREFIX) + 1 :]
        if rest.endswith("-" + ARCH_PLACEHOLDER):
            rest = rest[: -len(ARCH_PLACEHOLDER) - 1] + "/" + ARCH_PLACEHOLDER
        return f"{SRC_PREFIX}/{rest}"
    return None


def to_destination(image):
    if image.startswith(ACR_PREFIX + "/"):
        return image
    if image.startswith(SRC_PREFIX + "/"):
        rest = image[len(SRC_PREFIX) + 1 :]
        if rest.endswith("/" + ARCH_PLACEHOLDER):
            rest = rest[: -len(ARCH_PLACEHOLDER) - 1] + "-" + ARCH_PLACEHOLDER
        return f"{ACR_PREFIX}/{rest}"
    return None


def build_pairs(image, version, archs):
    src_base = to_source(image)
    dst_base = to_destination(image)
    if src_base is None or dst_base is None:
        return None, f"unsupported image reference: {image}"
    if src_base.endswith("/" + ARCH_PLACEHOLDER):
        if not archs:
            return None, f"image {image} uses arch placeholders but no arch list exists"
        src_root = src_base[: -len(ARCH_PLACEHOLDER) - 1]
        dst_root = dst_base[: -len(ARCH_PLACEHOLDER) - 1]
        pairs = [
            (f"{src_root}/{arch}:{version}", f"{dst_root}-{arch}:{version}")
            for arch in archs
        ]
        return pairs, None
    return [(f"{src_base}:{version}", f"{dst_base}:{version}")], None


def skopeo(args):
    return subprocess.run(["skopeo", *args], capture_output=True, text=True)


def image_exists(ref):
    return skopeo(["inspect", "--format", "{{.Digest}}", f"docker://{ref}"]).returncode == 0


def copy_image(src, dst):
    last_error = ""
    for attempt in range(1, 4):
        result = skopeo(["copy", "--all", f"docker://{src}", f"docker://{dst}"])
        if result.returncode == 0:
            return True, ""
        last_error = (result.stderr or result.stdout).strip()
        if attempt < 3:
            time.sleep(5 * attempt)
    lines = [line for line in last_error.splitlines() if line.strip()]
    return False, lines[-1] if lines else "unknown error"


def main():
    configs = sorted(Path(".").glob("*/config.yaml"))
    if not configs:
        print("error: no add-on config.yaml files found", file=sys.stderr)
        return 1
    synced = 0
    skipped = 0
    warned = 0
    failures = []
    for config in configs:
        image, version, archs = parse_config(config)
        addon = config.parent.name
        if not image:
            continue
        if not version:
            print(f"skip {addon}: config has no version", flush=True)
            warned += 1
            continue
        pairs, error = build_pairs(image, version, archs)
        if error:
            print(f"skip {addon}: {error}", flush=True)
            warned += 1
            continue
        for src, dst in pairs:
            if DRY_RUN:
                print(f"dry-run {src} -> {dst}", flush=True)
                synced += 1
                continue
            if not FORCE and image_exists(dst):
                skipped += 1
                continue
            if not image_exists(src):
                print(
                    f"warn {addon}: source image not published yet: {src}",
                    flush=True,
                )
                warned += 1
                continue
            ok, error = copy_image(src, dst)
            if ok:
                synced += 1
                print(f"synced {dst}", flush=True)
            else:
                failures.append((dst, error))
                print(f"failed {dst}: {error}", flush=True)
    print(
        f"done: synced={synced} skipped={skipped} warnings={warned} "
        f"failures={len(failures)}",
        flush=True,
    )
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write("### Image sync\n\n")
            handle.write(f"- synced: {synced}\n")
            handle.write(f"- skipped (already present): {skipped}\n")
            handle.write(f"- warnings: {warned}\n")
            handle.write(f"- failures: {len(failures)}\n")
            if failures:
                handle.write("\n")
                for dst, _ in failures:
                    handle.write(f"- `{dst}`\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
