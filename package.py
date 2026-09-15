#!/usr/bin/env python3
"""Build a QGIS-marketplace-ready zip of the plugin.

Usage:  python package.py
Output: GISPublisher_<version>.zip
"""

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

PLUGIN_NAME = "GISPublisher"

EXCLUDE_NAMES = {
    ".git", ".gitignore", ".github", ".claude",
    "__pycache__", "package.sh", "package.py",
}

EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}

EXCLUDE_PREFIXES = {"ui_", "resources_rc"}


def should_exclude(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_NAMES:
            return True
    name = path.name
    if name in EXCLUDE_NAMES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    for prefix in EXCLUDE_PREFIXES:
        if name.startswith(prefix) and name.endswith(".py"):
            return True
    return False


def get_version(metadata_path: Path) -> str:
    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*version\s*=\s*(.+)", line)
        if m:
            return m.group(1).strip()
    raise ValueError("version not found in metadata.txt")


def main():
    root = Path(__file__).parent.resolve()
    version = get_version(root / "metadata.txt")
    archive_name = f"{PLUGIN_NAME}_{version}.zip"
    archive_path = root / archive_name

    print(f"Packaging {PLUGIN_NAME} v{version} -> {archive_name}")

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path in sorted(root.rglob("*")):
            rel = abs_path.relative_to(root)
            if should_exclude(rel):
                continue
            if abs_path.is_file():
                arcname = Path(PLUGIN_NAME) / rel
                zf.write(abs_path, arcname)

    print(f"Done: {archive_path}")


if __name__ == "__main__":
    main()
