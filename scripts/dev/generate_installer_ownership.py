"""Generate auditable installer ownership manifests and Inno include data.

The historical manifests are checked-in records made from official release
assets.  The current manifest is generated from the exact PyInstaller payload
that is passed to Inno Setup.  The generated include contains only historical
files whose relative paths are absent from the current payload; the Inno
uninstaller verifies the hash again before removing any such file.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MANIFEST_FIELDS = ("relative_path", "size", "sha256")


@dataclass(frozen=True, order=True)
class OwnershipRecord:
    relative_path: str
    size: int
    sha256: str


def normalize_relative_path(value: str) -> str:
    """Return a safe, slash-normalized relative path or raise ValueError."""

    candidate = value.replace("\\", "/")
    if not candidate or candidate.startswith("/"):
        raise ValueError(f"ownership path is not relative: {value!r}")
    if len(candidate) >= 2 and candidate[1] == ":":
        raise ValueError(f"ownership path is drive-qualified: {value!r}")
    parts = PurePosixPath(candidate).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"ownership path contains an unsafe component: {value!r}")
    return "/".join(parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_records(source_dir: Path) -> list[OwnershipRecord]:
    """Hash every regular file below *source_dir* without following links."""

    root = source_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"source directory does not exist: {source_dir}")

    records: list[OwnershipRecord] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in installer payloads: {path}")
        if not path.is_file():
            continue
        relative_path = normalize_relative_path(path.relative_to(root).as_posix())
        records.append(
            OwnershipRecord(
                relative_path=relative_path,
                size=path.stat().st_size,
                sha256=_sha256(path),
            )
        )
    return records


def write_manifest(
    records: Sequence[OwnershipRecord],
    output: Path,
    *,
    release: str,
    asset_name: str,
    asset_sha256: str,
) -> None:
    if not SHA256_RE.fullmatch(asset_sha256):
        raise ValueError("asset_sha256 must be a 64-character SHA256")
    ordered = sorted(set(records))
    lines = [
        "# Invoice Hub installer ownership manifest",
        f"# release={release}",
        f"# asset={asset_name}",
        f"# asset_sha256={asset_sha256.lower()}",
        f"# file_count={len(ordered)}",
        "# format=relative_path|size|sha256",
    ]
    lines.extend(
        f"{record.relative_path}|{record.size}|{record.sha256.lower()}"
        for record in ordered
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> list[OwnershipRecord]:
    records: list[OwnershipRecord] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) != len(MANIFEST_FIELDS):
            raise ValueError(f"{path}:{line_number}: invalid manifest row")
        relative_path, size_text, sha256 = fields
        relative_path = normalize_relative_path(relative_path)
        try:
            size = int(size_text)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid file size") from exc
        if size < 0 or not SHA256_RE.fullmatch(sha256):
            raise ValueError(f"{path}:{line_number}: invalid file hash")
        records.append(
            OwnershipRecord(relative_path, size, sha256.lower())
        )
    return sorted(set(records))


def compute_legacy_obsolete(
    current_records: Iterable[OwnershipRecord],
    legacy_records: Iterable[OwnershipRecord],
) -> list[OwnershipRecord]:
    """Return historical records for paths absent from the current payload."""

    current_paths = {record.relative_path for record in current_records}
    return sorted(
        {
            record
            for record in legacy_records
            if record.relative_path not in current_paths
        }
    )


def _pascal_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_inno_include(
    records: Sequence[OwnershipRecord],
    output: Path,
    *,
    source_manifests: Sequence[Path],
) -> None:
    ordered = sorted(set(records))
    lines = [
        "// Generated by scripts/dev/generate_installer_ownership.py.",
        "// Do not edit this file by hand.",
        "// Source manifests: " + ", ".join(str(path) for path in source_manifests),
        f"  LegacyOwnershipCount = {len(ordered)};",
    ]
    if not ordered:
        lines.append("  LegacyOwnershipData = '';")
    else:
        lines.append("  LegacyOwnershipData =")
        payload_lines = [
            _pascal_string(
                record.relative_path.replace("/", "\\") + "|" + record.sha256.lower()
            )
            + "#13#10"
            for record in ordered
        ]
        lines.extend(
            "    " + value + (" +" if index < len(payload_lines) - 1 else ";")
            for index, value in enumerate(payload_lines)
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def command_manifest(args: argparse.Namespace) -> None:
    records = build_records(Path(args.source_dir))
    write_manifest(
        records,
        Path(args.output),
        release=args.release,
        asset_name=args.asset_name,
        asset_sha256=args.asset_sha256,
    )


def command_include(args: argparse.Namespace) -> None:
    current_records = build_records(Path(args.current_dir))
    legacy_records: list[OwnershipRecord] = []
    manifests = [Path(value) for value in args.legacy_manifest]
    for manifest in manifests:
        legacy_records.extend(read_manifest(manifest))
    obsolete = compute_legacy_obsolete(current_records, legacy_records)
    write_inno_include(obsolete, Path(args.output), source_manifests=manifests)
    if args.current_manifest_output:
        write_manifest(
            current_records,
            Path(args.current_manifest_output),
            release="current-build",
            asset_name="generated-from-current-payload",
            asset_sha256="0" * 64,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--source-dir", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--release", required=True)
    manifest.add_argument("--asset-name", required=True)
    manifest.add_argument("--asset-sha256", required=True)
    manifest.set_defaults(handler=command_manifest)

    include = subparsers.add_parser("include")
    include.add_argument("--current-dir", required=True)
    include.add_argument("--legacy-manifest", action="append", required=True)
    include.add_argument("--output", required=True)
    include.add_argument("--current-manifest-output")
    include.set_defaults(handler=command_include)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
