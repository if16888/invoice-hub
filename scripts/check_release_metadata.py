"""Fail when public release metadata drifts from repository release truth."""

from __future__ import annotations

import re
import runpy
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_FILES = (
    "requirements.lock.txt",
    "requirements-desktop.lock.txt",
    "requirements-build.lock.txt",
    "requirements-test.lock.txt",
)
RELEASE_NOTE_NAME = re.compile(
    r"^v(?P<version>\d+\.\d+\.\d+(?:-(?:rc|pre)\d+)?)\.md$"
)
STABLE_PUBLICATION_PATTERNS = (
    r"Status:\s*\*\*\s*Stable\s*[—-]\s*published\b",
    r"正式版已发布",
    r"current official release",
    r"published as the stable release",
)
LIVE_PUBLICATION_AUTHORITY = (
    "Live publication status is authoritative on the GitHub Releases page."
)


def load_version(repo_root: Path = REPO_ROOT) -> str:
    """Load VERSION without importing the application package."""
    version, _ = load_version_metadata(repo_root)
    return version


def load_version_metadata(repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    """Load the source release line and its previous published stable version."""
    metadata = runpy.run_path(
        str(repo_root / "scripts" / "invoice_fetch" / "version.py")
    )
    return str(metadata["VERSION"]), str(metadata["PREVIOUS_STABLE_VERSION"])


def _contains_stable_publication_claim(text: str) -> bool:
    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in STABLE_PUBLICATION_PATTERNS
    )


def _local_tag_type(repo_root: Path, version: str) -> str | None:
    result = subprocess.run(
        ["git", "cat-file", "-t", f"refs/tags/v{version}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _annotated_tag_error(
    repo_root: Path,
    version: str,
    *,
    required: bool,
) -> str | None:
    tag_type = _local_tag_type(repo_root, version)
    if tag_type is None:
        if required:
            return f"v{version} historical stable metadata requires a local annotated tag"
        return None
    if tag_type != "tag":
        return (
            f"v{version} tag must be annotated "
            f"(found {tag_type})"
        )
    return None


def _release_note_version(path: Path) -> str | None:
    match = RELEASE_NOTE_NAME.fullmatch(path.name)
    return match.group("version") if match else None


def check_release_metadata(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return release-truth and Python-baseline consistency errors."""
    version, previous_stable_version = load_version_metadata(repo_root)
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    expected_previous_link = (
        f"[Invoice Hub v{previous_stable_version}]"
        f"(https://github.com/if16888/invoice-hub/releases/tag/v{previous_stable_version})"
    )
    expected_source_notes_link = (
        f"[v{version} release notes](docs/release-notes/v{version}.md)"
    )
    errors: list[str] = []

    if expected_previous_link not in readme:
        errors.append(
            f"README 上一稳定版链接必须指向 v{previous_stable_version}"
        )
    if expected_source_notes_link not in readme:
        errors.append(f"README 必须链接当前源码发布线 v{version} release notes")
    if "GitHub Releases" not in readme:
        errors.append("README 必须声明 GitHub Releases 为实时发布状态权威")

    time_sensitive_source_patterns = (
        rf"v{re.escape(version)}\s+Stable\b",
        rf"v{re.escape(version)}[^\n]*(?:正式版已发布|当前公开稳定版|current official release)",
        rf"v{re.escape(version)}[^\n]*(?:未发布开发线|不应作为正式版下载|\bUnreleased\b)",
    )
    for pattern in time_sensitive_source_patterns:
        if re.search(pattern, readme, flags=re.IGNORECASE):
            errors.append(
                f"README 不得硬编码 v{version} 的实时发布/未发布状态；"
                "应以 GitHub Releases 为权威"
            )

    notes_dir = repo_root / "docs" / "release-notes"
    previous_notes_path = notes_dir / f"v{previous_stable_version}.md"
    checked_tag_versions: set[str] = set()
    if not previous_notes_path.is_file():
        errors.append(f"缺少 v{previous_stable_version} historical stable release notes")
    else:
        previous_notes = previous_notes_path.read_text(encoding="utf-8")
        if not _contains_stable_publication_claim(previous_notes):
            errors.append(
                f"v{previous_stable_version} release notes 必须声明 Stable — published"
            )
        tag_error = _annotated_tag_error(
            repo_root,
            previous_stable_version,
            required=True,
        )
        checked_tag_versions.add(previous_stable_version)
        if tag_error:
            errors.append(tag_error)

    source_notes_path = notes_dir / f"v{version}.md"
    if not source_notes_path.is_file():
        errors.append(f"缺少 v{version} source release notes")
    else:
        source_notes = source_notes_path.read_text(encoding="utf-8")
        if LIVE_PUBLICATION_AUTHORITY not in source_notes:
            errors.append(
                f"v{version} release notes 必须把实时发布状态委托给 GitHub Releases"
            )
        if _contains_stable_publication_claim(source_notes):
            errors.append(
                f"v{version} source release notes 不得硬编码 Stable — published 状态"
            )
        if re.search(r"\bUnreleased\b|未发布", source_notes, flags=re.IGNORECASE):
            errors.append(
                f"v{version} source release notes 不得硬编码 Unreleased 状态"
            )
        tag_error = _annotated_tag_error(repo_root, version, required=False)
        checked_tag_versions.add(version)
        if tag_error:
            errors.append(tag_error)

    if notes_dir.is_dir():
        for path in sorted(notes_dir.glob("v*.md")):
            note_version = _release_note_version(path)
            if note_version is None or not _contains_stable_publication_claim(
                path.read_text(encoding="utf-8")
            ):
                continue
            if note_version in checked_tag_versions:
                continue
            tag_error = _annotated_tag_error(repo_root, note_version, required=True)
            checked_tag_versions.add(note_version)
            if tag_error:
                errors.append(tag_error)

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
    version, previous_stable_version = load_version_metadata()
    errors = check_release_metadata()

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(
        "[PASS] Release truth 与 Python 3.11 baseline 一致: "
        f"VERSION={version}, PREVIOUS_STABLE_VERSION={previous_stable_version}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
