# -*- coding: utf-8 -*-
"""
Invoice Hub GUI Helpers
"""

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
        "export_filter": {}
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


def resolve_invoice_documents(invoice: dict, runtime_dir: Path = None) -> list[dict]:
    """
    Extracts all document paths from an invoice dict.
    Returns a list of dicts:
      [
        {"type": "primary", "title": "主发票", "path": Path, "basename": str},
        {"type": "supporting", "title": "证明材料", "path": Path, "basename": str},
      ]
    """
    if runtime_dir is None:
        from ..config import RUNTIME_DIR as runtime_dir

    docs = []

    # 1. Attachment Path (Primary)
    att_path = invoice.get("attachment_path")
    if att_path:
        raw_path = Path(str(att_path))
        resolved_path = None
        candidates = [raw_path] if raw_path.is_absolute() else [
            runtime_dir / raw_path,
            runtime_dir / "attachments" / raw_path,
        ]
        for candidate in candidates:
            if candidate.exists():
                resolved_path = candidate
                break
        if resolved_path is None:
            resolved_path = raw_path if raw_path.is_absolute() else runtime_dir / raw_path

        docs.append({
            "type": "primary",
            "title": "主发票",
            "path": resolved_path,
            "basename": resolved_path.name
        })

    # 2. Extra Paths (Supporting)
    extra_paths_raw = invoice.get("extra_paths")
    extra_paths = _normalize_path_list(extra_paths_raw)
    for p in extra_paths:
        if not p:
            continue
        raw_path = Path(str(p))
        resolved_path = None
        candidates = [raw_path] if raw_path.is_absolute() else [
            runtime_dir / raw_path,
            runtime_dir / "attachments" / raw_path,
        ]
        for candidate in candidates:
            if candidate.exists():
                resolved_path = candidate
                break
        if resolved_path is None:
            resolved_path = raw_path if raw_path.is_absolute() else runtime_dir / raw_path

        docs.append({
            "type": "supporting",
            "title": "证明材料",
            "path": resolved_path,
            "basename": resolved_path.name
        })

    return docs
