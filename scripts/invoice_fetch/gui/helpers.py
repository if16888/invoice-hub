"""Invoice Hub GUI Helpers."""

from pathlib import Path

from ..url_utils import _mask_url


def _read_manifest_item_count(export_dir) -> int:
    """Read item count from manifest.json inside export_dir safely."""
    summary = _read_manifest_summary(export_dir)
    return summary.get("item_count", 0)


def _read_manifest_summary(export_dir) -> dict:
    """Read complete summary from manifest.json inside export_dir safely."""
    summary = {
        "item_count": 0,
        "skipped_counts": {},
        "export_filter": {},
    }
    if not export_dir:
        return summary

    manifest_dest = Path(export_dir) / "manifest.json"
    if not manifest_dest.exists():
        return summary

    try:
        import json

        with open(manifest_dest, "r", encoding="utf-8") as f:
            data = json.load(f)
            summary["item_count"] = data.get("item_count", 0)
            summary["skipped_counts"] = data.get("skipped_counts", {})
            summary["export_filter"] = data.get("export_filter", {})
    except Exception:
        pass
    return summary


def _normalize_path_list(raw_value) -> list[str]:
    import json

    if not raw_value:
        return []
    if isinstance(raw_value, list):
        return [str(v) for v in raw_value if v]
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return [raw_value]
        if isinstance(parsed, list):
            return [str(v) for v in parsed if v]
        return [str(raw_value)]
    return [str(raw_value)]


def resolve_stored_path(raw_path: str | Path, runtime_dir: Path) -> Path:
    """Resolve a stored attachment path using the same candidates as the GUI."""
    raw_path = Path(str(raw_path))
    if raw_path.is_absolute():
        return raw_path

    runtime_dir = Path(runtime_dir)
    project_root = runtime_dir.parent
    candidates = [
        runtime_dir / raw_path,
        runtime_dir / "attachments" / raw_path,
        project_root / raw_path,
        project_root / "runtime" / raw_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    filename = raw_path.name
    if filename:
        search_roots = [
            runtime_dir / "attachments",
            runtime_dir,
            project_root / "runtime" / "attachments",
        ]
        for root in search_roots:
            if not root.exists():
                continue
            matches = [p for p in root.rglob(filename) if p.is_file()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1 and len(raw_path.parts) >= 2:
                suffix = Path(*raw_path.parts[-2:])
                suffix_matches = [p for p in matches if str(p).endswith(str(suffix))]
                if len(suffix_matches) == 1:
                    return suffix_matches[0]
                return matches[0]

    return candidates[0]


def resolve_invoice_documents(invoice: dict, runtime_dir: Path = None) -> list[dict]:
    """Extract all document paths from an invoice dict."""
    if runtime_dir is None:
        from ..config import RUNTIME_DIR as runtime_dir

    docs = []

    att_path = invoice.get("attachment_path")
    if att_path:
        resolved_path = resolve_stored_path(att_path, runtime_dir)
        docs.append({
            "type": "primary",
            "title": "主发票",
            "path": resolved_path,
            "basename": resolved_path.name,
        })

    for extra_path in _normalize_path_list(invoice.get("extra_paths")):
        if not extra_path:
            continue
        resolved_path = resolve_stored_path(extra_path, runtime_dir)
        docs.append({
            "type": "supporting",
            "title": "证明材料",
            "path": resolved_path,
            "basename": resolved_path.name,
        })

    return docs
