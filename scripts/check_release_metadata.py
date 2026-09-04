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


def load_version(repo_root: Path = REPO_ROOT) -> str:
    """Load VERSION without importing the application package."""
    version, _ = load_version_metadata(repo_root)
    return version


def load_version_metadata(repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    """Load source and published-stable versions without importing the app."""
    metadata = runpy.run_path(
        str(repo_root / "scripts" / "invoice_fetch" / "version.py")
    )
    return str(metadata["VERSION"]), str(metadata["STABLE_VERSION"])


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


def _annotated_tag_error(repo_root: Path, version: str) -> str | None:
    tag_type = _local_tag_type(repo_root, version)
    if tag_type is None:
        return f"v{version} stable metadata requires a local annotated tag"
    if tag_type != "tag":
        return (
            f"v{version} stable metadata requires an annotated tag "
            f"(found {tag_type})"
        )
    return None


def _release_note_version(path: Path) -> str | None:
    match = RELEASE_NOTE_NAME.fullmatch(path.name)
    return match.group("version") if match else None


def check_release_metadata(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return release-truth and Python-baseline consistency errors."""
    version, stable_version = load_version_metadata(repo_root)
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    expected_link = (
        f"[Invoice Hub v{stable_version}]"
        f"(https://github.com/if16888/invoice-hub/releases/tag/v{stable_version})"
    )
    errors: list[str] = []
    if expected_link not in readme:
        errors.append(f"README 当前稳定版链接必须指向 v{stable_version}")
    if f"v{stable_version} Stable" not in readme:
        errors.append(f"README 发布状态必须声明 v{stable_version} Stable")

    source_stable_patterns = (
        rf"v{re.escape(version)}\s+Stable\b",
        rf"v{re.escape(version)}[^\n]*(?:正式版已发布|当前稳定版|官方 Release|current official release)",
    )
    if version != stable_version:
        for pattern in source_stable_patterns:
            if re.search(pattern, readme, flags=re.IGNORECASE):
                errors.append(
                    f"README 不得将 source VERSION v{version} 声明为稳定发布版"
                )
        if not re.search(
            rf"v{re.escape(version)}[^\n]*(?:未发布|unreleased|development)",
            readme,
            flags=re.IGNORECASE,
        ):
            errors.append(f"README 必须明确 v{version} 仍为未发布开发线")

    notes_dir = repo_root / "docs" / "release-notes"
    stable_notes_path = notes_dir / f"v{stable_version}.md"
    checked_tag_versions: set[str] = set()
    if not stable_notes_path.is_file():
        errors.append(f"缺少 v{stable_version} stable release notes")
    else:
        stable_notes = stable_notes_path.read_text(encoding="utf-8")
        if not _contains_stable_publication_claim(stable_notes):
            errors.append(
                f"v{stable_version} release notes 必须声明 Stable — published"
            )
        tag_error = _annotated_tag_error(repo_root, stable_version)
        checked_tag_versions.add(stable_version)
        if tag_error:
            errors.append(tag_error)

    if version != stable_version:
        development_notes_path = notes_dir / f"v{version}.md"
        if not development_notes_path.is_file():
            errors.append(f"缺少 v{version} development release notes")
        else:
            development_notes = development_notes_path.read_text(encoding="utf-8")
            if _contains_stable_publication_claim(development_notes):
                errors.append(
                    f"v{version} development release notes 不得声明 Stable — published"
                )
            if not re.search(
                r"\bUnreleased\b|未发布|previous candidate superseded",
                development_notes,
                flags=re.IGNORECASE,
            ):
                errors.append(f"v{version} release notes 必须明确为 Unreleased")

    if notes_dir.is_dir():
        for path in sorted(notes_dir.glob("v*.md")):
            note_version = _release_note_version(path)
            if note_version is None or not _contains_stable_publication_claim(
                path.read_text(encoding="utf-8")
            ):
                continue
            if note_version in checked_tag_versions:
                continue
            tag_error = _annotated_tag_error(repo_root, note_version)
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
    version, stable_version = load_version_metadata()
    errors = check_release_metadata()

    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    print(
        "[PASS] Release truth 与 Python 3.11 baseline 一致: "
        f"VERSION={version}, STABLE_VERSION={stable_version}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
