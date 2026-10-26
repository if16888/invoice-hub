# -*- coding: utf-8 -*-
"""Required payload for the Windows release build.

``invoice_hub_windows.spec`` bundles a copy of this list through
``require_release_payload``.  Keeping the check in an importable module (rather
than inside the spec) lets a normal unit test prove that a release cannot be
built without the PDF viewer, its CMaps/standard fonts, the GUI assets or the
license files — each of which turns into a silently broken installer instead of
a build failure.

Import-safe: no PyInstaller globals and no side effects on import.
"""

from __future__ import annotations

import os
from pathlib import Path

# Single files that must exist at the repository root.
REQUIRED_FILES = (
    "config.example.json",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
)

# Directories that must exist and contain at least one file.
REQUIRED_DIRS = (
    "licenses",
    "scripts/invoice_fetch/gui/assets",
    "scripts/invoice_fetch/web_assets/pdfjs",
    "scripts/invoice_fetch/web_assets/pdfjs/cmaps",
    "scripts/invoice_fetch/web_assets/pdfjs/standard_fonts",
)

# Individual files inside a required directory (the viewer entry points).
REQUIRED_FILES_RELATIVE = (
    "scripts/invoice_fetch/web_assets/pdfjs/pdf.min.mjs",
    "scripts/invoice_fetch/web_assets/pdfjs/pdf.worker.min.mjs",
)


def _directory_has_files(path: Path) -> bool:
    try:
        return path.is_dir() and any(entry.is_file() for entry in path.iterdir())
    except OSError:
        return False


def collect_missing_payload(root: str | Path) -> list[str]:
    """Return the required payload entries that are missing or empty."""
    root_path = Path(root)
    missing: list[str] = []
    for name in REQUIRED_FILES:
        if not (root_path / name).is_file():
            missing.append(name)
    for name in REQUIRED_DIRS:
        target = root_path / name
        if not _directory_has_files(target):
            missing.append(name + "/")
    for name in REQUIRED_FILES_RELATIVE:
        if not (root_path / name).is_file():
            missing.append(name)
    return missing


def require_release_payload(root: str | Path) -> None:
    """Raise when the release payload is incomplete.

    The build must stop here: a missing PDF.js runtime or license directory
    produces an installer that installs cleanly and then fails at runtime.
    """
    missing = collect_missing_payload(root)
    if not missing:
        return
    raise FileNotFoundError(
        "发行包缺少必需文件，已停止打包以免产出不可用的安装包："
        + "、".join(missing)
    )


def playwright_driver_dir(playwright_package: str | Path) -> Path:
    """Return the driver directory bundled into the release payload."""
    return Path(playwright_package) / "driver"


def require_playwright_driver(driver_dir: str | Path) -> None:
    """Raise when the bundled Playwright driver is missing."""
    path = Path(driver_dir)
    try:
        node_present = any(candidate.is_file() and candidate.stat().st_size > 0
                           for candidate in (path / "node.exe", path / "node"))
        cli = path / "package" / "cli.js"
        cli_present = cli.is_file() and cli.stat().st_size > 0
    except OSError:
        node_present = cli_present = False
    if not (node_present and cli_present):
        raise FileNotFoundError(
            f"发行包缺少 Playwright driver，已停止打包：{os.fspath(path)}"
        )
