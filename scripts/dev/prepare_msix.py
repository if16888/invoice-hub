"""Stage the frozen Invoice Hub payload as a Microsoft Store MSIX layout.

This script intentionally does not sign or publish the package. Store identity
values must come from Partner Center and are kept outside source control.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402

from scripts.invoice_fetch.version import VERSION  # noqa: E402

DEFAULT_TEMPLATE = PROJECT_ROOT / "packaging" / "msix" / "AppxManifest.template.xml"
DEFAULT_LOGO = PROJECT_ROOT / "scripts" / "invoice_fetch" / "gui" / "assets" / "logo_icon.png"

_PACKAGE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$")
_PLACEHOLDER_MARKERS = ("@@", "<partner-center", "replace-me", "example.publisher")
_STAGING_OWNER_MARKER = "<!-- invoice-hub-msix-staging-owner:v1 -->"


def store_package_version(source_version: str = VERSION) -> str:
    """Map app SemVer X.Y.Z to a Store-safe four-part package version."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(source_version).strip())
    if not match:
        raise ValueError("Store packaging requires a stable numeric source version X.Y.Z.")
    major, minor, patch = (int(part) for part in match.groups())
    values = (major + 1, minor, patch, 0)
    if any(value < 0 or value > 65535 for value in values):
        raise ValueError("Store package version components must be between 0 and 65535.")
    return ".".join(str(value) for value in values)


def validate_package_version(value: str) -> str:
    match = _PACKAGE_VERSION_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError("MSIX package version must contain four numeric components.")
    parts = tuple(int(part) for part in match.groups())
    if parts[0] == 0:
        raise ValueError("MSIX package major version must be non-zero for Store submission.")
    if parts[3] != 0:
        raise ValueError("MSIX package revision must be 0 for Store submission.")
    if any(part > 65535 for part in parts):
        raise ValueError("MSIX package version components must not exceed 65535.")
    return ".".join(str(part) for part in parts)


def _partner_center_value(name: str, value: str) -> str:
    cleaned = str(value or "").strip()
    lowered = cleaned.lower()
    if not cleaned:
        raise ValueError(f"{name} must be copied from Partner Center and cannot be empty.")
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise ValueError(f"{name} still contains a placeholder value.")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"{name} contains an invalid control character.")
    return cleaned


def _xml(value: str) -> str:
    return escape(value, {'"': "&quot;", "'": "&apos;"})


def render_manifest(
    template_text: str,
    *,
    identity_name: str,
    publisher: str,
    publisher_display_name: str,
    display_name: str,
    description: str,
    package_version: str,
) -> str:
    values = {
        "@@IDENTITY_NAME@@": _partner_center_value("identity name", identity_name),
        "@@PUBLISHER@@": _partner_center_value("publisher", publisher),
        "@@PUBLISHER_DISPLAY_NAME@@": _partner_center_value(
            "publisher display name", publisher_display_name
        ),
        "@@DISPLAY_NAME@@": _partner_center_value("display name", display_name),
        "@@DESCRIPTION@@": str(description or "Invoice Hub").strip() or "Invoice Hub",
        "@@PACKAGE_VERSION@@": validate_package_version(package_version),
    }
    rendered = template_text
    for marker, value in values.items():
        rendered = rendered.replace(marker, _xml(value))
    if "@@" in rendered:
        raise ValueError("MSIX manifest template contains unresolved placeholders.")
    return rendered


def _write_square_asset(source: Path, destination: Path, size: int) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        x = (size - image.width) // 2
        y = (size - image.height) // 2
        canvas.alpha_composite(image, (x, y))
        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(destination, format="PNG", optimize=True)


def _path_contains(container: Path, candidate: Path) -> bool:
    return candidate == container or container in candidate.parents


def _validate_staging_boundaries(
    *,
    payload_dir: Path,
    output_dir: Path,
    template_path: Path,
    logo_path: Path,
) -> None:
    if _path_contains(payload_dir, output_dir) or _path_contains(output_dir, payload_dir):
        raise ValueError("MSIX payload and output directories must not overlap.")
    for name, source in (
        ("manifest template", template_path),
        ("logo source", logo_path),
    ):
        if _path_contains(output_dir, source):
            raise ValueError(f"MSIX output directory must not contain the {name} input.")


def _with_staging_owner_marker(manifest: str) -> str:
    if _STAGING_OWNER_MARKER in manifest:
        return manifest
    if manifest.startswith("<?xml"):
        declaration_end = manifest.find("?>")
        if declaration_end >= 0:
            insertion = declaration_end + 2
            return (
                manifest[:insertion]
                + "\n"
                + _STAGING_OWNER_MARKER
                + manifest[insertion:]
            )
    return _STAGING_OWNER_MARKER + "\n" + manifest


def _remove_existing_owned_staging(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError("MSIX output path already exists and is not a directory.")

    manifest_path = output_dir / "AppxManifest.xml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(
            "Refusing to replace an existing MSIX output directory without staging ownership."
        )
    try:
        existing_manifest = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError(
            "Refusing to replace an existing MSIX output directory whose ownership cannot be verified."
        ) from None
    if _STAGING_OWNER_MARKER not in existing_manifest:
        raise ValueError(
            "Refusing to replace an existing MSIX output directory not owned by Invoice Hub staging."
        )
    shutil.rmtree(output_dir)


def stage_msix_layout(
    *,
    payload_dir: Path,
    output_dir: Path,
    template_path: Path,
    logo_path: Path,
    identity_name: str,
    publisher: str,
    publisher_display_name: str,
    display_name: str = "Invoice Hub",
    description: str = "本地优先的发票与报销资料整理工具",
) -> dict[str, str]:
    raw_output_dir = Path(output_dir)
    if raw_output_dir.is_symlink():
        raise ValueError("MSIX output directory must not be a symbolic link.")

    payload_dir = payload_dir.resolve()
    output_dir = raw_output_dir.resolve()
    template_path = template_path.resolve()
    logo_path = logo_path.resolve()

    _validate_staging_boundaries(
        payload_dir=payload_dir,
        output_dir=output_dir,
        template_path=template_path,
        logo_path=logo_path,
    )

    if not (payload_dir / "InvoiceHub.exe").is_file():
        raise FileNotFoundError("Frozen payload must contain InvoiceHub.exe at its root.")
    if not template_path.is_file():
        raise FileNotFoundError("MSIX manifest template is missing.")
    if not logo_path.is_file():
        raise FileNotFoundError("Invoice Hub logo source is missing.")

    resolved_package_version = validate_package_version(store_package_version(VERSION))
    manifest = render_manifest(
        template_path.read_text(encoding="utf-8"),
        identity_name=identity_name,
        publisher=publisher,
        publisher_display_name=publisher_display_name,
        display_name=display_name,
        description=description,
        package_version=resolved_package_version,
    )
    manifest = _with_staging_owner_marker(manifest)

    _remove_existing_owned_staging(output_dir)
    shutil.copytree(payload_dir, output_dir)

    (output_dir / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    assets = output_dir / "Assets"
    _write_square_asset(logo_path, assets / "Square44x44Logo.png", 44)
    _write_square_asset(logo_path, assets / "Square150x150Logo.png", 150)
    _write_square_asset(logo_path, assets / "StoreLogo.png", 50)

    return {
        "source_version": VERSION,
        "package_version": resolved_package_version,
        "identity_name": identity_name.strip(),
        "publisher": publisher.strip(),
        "publisher_display_name": publisher_display_name.strip(),
        "display_name": display_name.strip(),
        "architecture": "x64",
        "distribution": "microsoft-store-msix",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--identity-name", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--publisher-display-name", required=True)
    parser.add_argument("--display-name", default="Invoice Hub")
    parser.add_argument(
        "--description",
        default="本地优先的发票与报销资料整理工具",
    )
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument("--metadata-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    metadata = stage_msix_layout(
        payload_dir=args.payload_dir,
        output_dir=args.output_dir,
        template_path=args.template,
        logo_path=args.logo,
        identity_name=args.identity_name,
        publisher=args.publisher,
        publisher_display_name=args.publisher_display_name,
        display_name=args.display_name,
        description=args.description,
    )
    metadata_output = args.metadata_output.resolve()
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"MSIX layout staged: {args.output_dir}")
    print(f"Store package version: {metadata['package_version']}")
    print(f"Metadata: {metadata_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
