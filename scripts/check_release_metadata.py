"""Fail when public release metadata drifts from the application version."""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION = str(
    runpy.run_path(str(REPO_ROOT / "scripts" / "invoice_fetch" / "version.py"))[
        "VERSION"
    ]
)


def main() -> int:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    expected_link = (
        f"[Invoice Hub v{VERSION}]"
        f"(https://github.com/if16888/invoice-hub/releases/tag/v{VERSION})"
    )
    errors: list[str] = []
    if expected_link not in readme:
        errors.append(f"README 当前稳定版链接必须指向 v{VERSION}")
    if f"v{VERSION} Stable" not in readme:
        errors.append(f"README 发布状态必须声明 v{VERSION} Stable")

    stale_patterns = (
        rf"v{re.escape(VERSION)}[^\n]*(?:尚未发布|release preparation|RC 准备中)",
        rf"(?:当前稳定版|stable 用户)[^\n]*v(?!{re.escape(VERSION)}\b)\d+\.\d+\.\d+",
    )
    for pattern in stale_patterns:
        if re.search(pattern, readme, flags=re.IGNORECASE):
            errors.append(f"README 包含与 VERSION 冲突的发布状态：{pattern}")

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(f"[PASS] README 与 VERSION={VERSION} 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
