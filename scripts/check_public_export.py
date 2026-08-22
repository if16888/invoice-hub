"""Validate that a public export tree does not contain private-only files.

This script is intended for the clean public repository/export directory, not
for the private development repository. It checks the file tree on disk and
fails if internal docs, local runtime data, generated artifacts, or private
strategy files are present.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REQUIRED_FILES = {
    ".github/CODEOWNERS",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/user-quickstart.md",
    "docs/privacy-and-feedback.md",
    "docs/privacy-data-flow.md",
    "docs/release-checklist.md",
}

FORBIDDEN_EXACT = {
    "AGENTS.md",
    "config.json",
    "desktop_app_design.md",
    "implementation_plan.md",
    "docs/minimum-mvp-gap.md",
    "docs/public-private-code-boundary.md",
}

SOURCE_TREE_ALLOWED_FORBIDDEN_EXACT = FORBIDDEN_EXACT - {"config.json"}

FORBIDDEN_NAMES = {
    ".env",
    ".env.local",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}

FORBIDDEN_DIRS = {
    ".antigravitycli",
    ".claude",
    ".gemini",
    ".worktrees",
    "bench-local",
    "build",
    "dist",
    "exports",
    "private",
    "private-data",
    "real-samples",
    "runtime",
    "scratch",
    "secrets",
}

SKIP_DIRS = {
    ".git",
    "__pycache__",
}

FORBIDDEN_SUFFIXES = {
    ".csv",
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".pdf",
    ".ofd",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".heic",
    ".key",
    ".xlsx",
    ".xls",
    ".p12",
    ".pfx",
    ".pem",
    ".zip",
}

ALLOW_SUFFIX_UNDER = {
    "docs/images": {".png"},
    "scripts/invoice_fetch/gui/assets": {".png", ".ico", ".svg"},
    "scripts/invoice_fetch/web_assets/pdfjs": {".mjs", ".bcmap", ".pfb", ".ttf"},
    "tests/fixtures/synthetic": {".pdf", ".png", ".jpg", ".jpeg", ".zip", ".xlsx"},
}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _allowed_suffix(rel: str, suffix: str) -> bool:
    for prefix, suffixes in ALLOW_SUFFIX_UNDER.items():
        if rel == prefix or rel.startswith(prefix + "/"):
            return suffix.lower() in suffixes
    return False


def find_public_export_issues(root: Path) -> list[str]:
    root = root.resolve()
    issues: list[str] = []

    for required in sorted(REQUIRED_FILES):
        if not (root / required).exists():
            issues.append(f"missing required public file: {required}")

    for path in root.rglob("*"):
        rel = _rel(path, root)
        parts = set(Path(rel).parts)

        if parts & SKIP_DIRS:
            continue

        if path.is_dir():
            if path.name in FORBIDDEN_DIRS:
                issues.append(f"forbidden directory: {rel}")
            continue

        if rel in FORBIDDEN_EXACT:
            issues.append(f"forbidden file: {rel}")
        if path.name.lower() in FORBIDDEN_NAMES:
            issues.append(f"forbidden secret/config file name: {rel}")
        if parts & FORBIDDEN_DIRS:
            issues.append(f"file under forbidden directory: {rel}")
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES and not _allowed_suffix(rel, suffix):
            issues.append(f"forbidden generated/private file type: {rel}")

    return sorted(set(issues))


def _tracked_files(root: Path) -> list[Path]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    return [root / line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _looks_like_private_source_tree(root: Path) -> bool:
    return (root / ".git").exists() and bool(_tracked_files(root))


def find_source_tree_issues(root: Path) -> list[str]:
    """Check release-readiness of the private source checkout.

    This is intentionally narrower than strict public export validation: the
    private development repository may contain internal docs and local generated
    directories that must not be exported, but tracked secret-like files should
    still fail the gate.
    """
    root = root.resolve()
    issues: list[str] = []

    for required in sorted(REQUIRED_FILES):
        if not (root / required).exists():
            issues.append(f"missing required public file: {required}")

    for path in _tracked_files(root):
        if not path.exists() or path.is_dir():
            continue
        rel = _rel(path, root)
        parts = set(Path(rel).parts)
        suffix = path.suffix.lower()
        if rel in FORBIDDEN_EXACT and rel not in SOURCE_TREE_ALLOWED_FORBIDDEN_EXACT:
            issues.append(f"forbidden tracked private/public-excluded file: {rel}")
        if path.name.lower() in FORBIDDEN_NAMES:
            issues.append(f"forbidden secret/config file name: {rel}")
        if parts & FORBIDDEN_DIRS:
            issues.append(f"forbidden tracked file under generated/private directory: {rel}")
        if suffix in FORBIDDEN_SUFFIXES and not _allowed_suffix(rel, suffix):
            issues.append(f"forbidden tracked release-risk file type: {rel}")

    return sorted(set(issues))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Invoice Hub public export tree hygiene.")
    parser.add_argument("path", nargs="?", default=".", help="Path to the public export tree.")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.exists() or not root.is_dir():
        print(f"[public-export] path is not a directory: {root}", file=sys.stderr)
        return 2

    source_mode = _looks_like_private_source_tree(root.resolve())
    issues = find_source_tree_issues(root) if source_mode else find_public_export_issues(root)
    if issues:
        print("[public-export] failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    if source_mode:
        print("[public-export] passed (source tree mode)")
    else:
        print("[public-export] passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
