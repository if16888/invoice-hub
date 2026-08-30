"""Fail when public release metadata drifts from the application version."""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_FILES = (
    "requirements.lock.txt",
    "requirements-desktop.lock.txt",
    "requirements-build.lock.txt",
    "requirements-test.lock.txt",
)


def load_version(repo_root: Path = REPO_ROOT) -> str:
    """Load VERSION without importing the application package."""
    metadata = runpy.run_path(
        str(repo_root / "scripts" / "invoice_fetch" / "version.py")
    )
    return str(metadata["VERSION"])


def check_release_metadata(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return public-release and Python-baseline consistency errors."""
    version = load_version(repo_root)
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    expected_link = (
        f"[Invoice Hub v{version}]"
        f"(https://github.com/if16888/invoice-hub/releases/tag/v{version})"
    )
    errors: list[str] = []
    if expected_link not in readme:
        errors.append(f"README 当前稳定版链接必须指向 v{version}")
    if f"v{version} Stable" not in readme:
        errors.append(f"README 发布状态必须声明 v{version} Stable")

    stale_patterns = (
        rf"v{re.escape(version)}[^\n]*(?:尚未发布|release preparation|RC 准备中)",
        rf"(?:当前稳定版|stable 用户)[^\n]*v(?!{re.escape(version)}\b)\d+\.\d+\.\d+",
    )
    for pattern in stale_patterns:
        if re.search(pattern, readme, flags=re.IGNORECASE):
            errors.append(f"README 包含与 VERSION 冲突的发布状态：{pattern}")

    release_notes_path = repo_root / "docs" / "release-notes" / f"v{version}.md"
    if not release_notes_path.is_file():
        errors.append(f"缺少 v{version} release notes")
    else:
        release_notes = release_notes_path.read_text(encoding="utf-8")
        if "Status: **Stable — published" not in release_notes:
            errors.append(f"v{version} release notes 必须声明 Stable — published")
        if re.search(
            r"release preparation|candidate not yet published|not a stable-release",
            release_notes,
            flags=re.IGNORECASE,
        ):
            errors.append(f"v{version} release notes 仍包含未发布状态")

    expected_lock_header = "pip-compile with Python 3.11"
    for relative in LOCK_FILES:
        path = repo_root / relative
        if not path.is_file():
            errors.append(f"缺少 lock 文件：{relative}")
            continue
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:5])
        if expected_lock_header not in header:
            errors.append(f"{relative} header 必须声明 Python 3.11")

    return errors


def main() -> int:
    version = load_version()
    errors = check_release_metadata()

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(f"[PASS] Release truth 与 Python 3.11 baseline 一致: VERSION={version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
