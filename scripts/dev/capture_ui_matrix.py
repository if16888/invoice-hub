"""Capture reproducible, local-only Invoice Hub UI review screenshots.

The utility deliberately creates an isolated database and writes only below
``runtime/ui-review`` (which is ignored by Git).  It is intended for visual
review of the current source tree, not for capturing a user's live data.

Examples
--------
python scripts/dev/capture_ui_matrix.py --page imports-mobile --state mobile-active
python scripts/dev/capture_ui_matrix.py --page all --size 1366x768 --scale 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QDateTime
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.api_key_dialog import ApiKeyDialog
from scripts.invoice_fetch.gui.app import InvoiceReviewApp


PAGES = (
    "dashboard", "review", "imports-email", "imports-local", "imports-mobile",
    "export", "settings-mailbox", "settings-ai", "runtime", "data", "about", "api-key",
)
STATES = (
    "normal", "empty", "error", "long-text", "missing-authorization", "multi-ai",
    "export-blocked", "mobile-active",
)


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT") from exc
    if width < 800 or height < 600:
        raise argparse.ArgumentTypeError("size must be at least 800x600")
    return width, height


def set_page(window: InvoiceReviewApp, page: str) -> ApiKeyDialog | None:
    if page == "dashboard":
        window._switch_main_page("overview")
    elif page == "review":
        window._switch_main_page("review")
    elif page.startswith("imports-"):
        window._switch_main_page("imports")
        window._set_import_source_selected(page.removeprefix("imports-"))
    elif page == "export":
        window._switch_main_page("export")
    elif page.startswith("settings-"):
        window._switch_main_page("settings")
        window.settings_tabs.setCurrentIndex({"settings-mailbox": 0, "settings-ai": 1}[page])
    elif page in {"runtime", "data", "about"}:
        window._switch_main_page("settings")
        window.settings_tabs.setCurrentIndex({"runtime": 2, "data": 4, "about": 5}[page])
    elif page == "api-key":
        dialog = ApiKeyDialog("DeepSeek", window, has_existing_key=True)
        dialog.show()
        return dialog
    return None


def apply_state(window: InvoiceReviewApp, page: str, state: str) -> None:
    if state == "mobile-active" and page == "imports-mobile":
        controller = window.mobile_upload_controller
        controller.host_options = [SimpleNamespace(label="WLAN - 192.168.31.251", host="192.168.31.251")]
        controller.started.emit(SimpleNamespace(
            upload_url="http://192.168.31.251:54867/u/synthetic-review",
            host="192.168.31.251", port=54867,
        ))
        controller.stats_changed.emit({"accepted": 2, "duplicate": 0, "failed": 0, "imported": 2})
    elif state == "error" and page == "imports-mobile":
        window.mobile_upload_controller.failed.emit("Synthetic startup failure for visual review")
    elif state == "long-text" and page == "settings-mailbox":
        long_value = "long-synthetic-value-" * 12
        window.lbl_detail_name.setText(long_value)
        window.lbl_detail_email.setText(f"{long_value}@example.invalid")
        window.lbl_detail_server.setText(f"{long_value}.imap.example.invalid:993 (SSL/TLS)")
        for label in (window.lbl_detail_name, window.lbl_detail_email, window.lbl_detail_server):
            label.setToolTip(label.text())
    elif state == "missing-authorization" and page == "settings-mailbox":
        window.lbl_detail_credential_status.setText("需要授权")
        window.lbl_settings_mailbox_test_status.setText("请补充授权码后再测试连接。")
    elif state == "multi-ai" and page == "settings-ai":
        profiles = [
            {"profile_id": "synthetic-a", "name": "Synthetic A", "provider": "Provider A", "model": "model-a", "enabled": True},
            {"profile_id": "synthetic-b", "name": "Synthetic B", "provider": "Provider B", "model": "model-b", "enabled": True},
        ]
        original = window._ai_profiles_for_settings
        window._ai_profiles_for_settings = lambda: profiles
        window._refresh_settings_ai_page()
        window._ai_profiles_for_settings = original
    elif state == "export-blocked" and page == "export":
        window.lbl_export_action_hint.setText("阻塞：请先选择报销组并补齐缺失材料。")
        window.btn_run_export_page.setEnabled(False)


def capture_one(app: QApplication, page: str, state: str, size: tuple[int, int], scale: float, output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="invoice-hub-ui-") as td:
        window = InvoiceReviewApp(Path(td) / "review.db")
        window.resize(*size)
        dialog = set_page(window, page)
        apply_state(window, page, state)
        window.show()
        app.processEvents(); app.processEvents()
        target = dialog or window
        name = f"{page}__{state}__{size[0]}x{size[1]}__scale-{scale:g}.png"
        path = output / name
        if not target.grab().save(str(path)):
            raise RuntimeError(f"failed to write {path}")
        screen = QGuiApplication.primaryScreen()
        entry = {
            "file": str(path), "page": page, "state": state, "size": list(size),
            "requested_scale": scale,
            "device_pixel_ratio": screen.devicePixelRatio() if screen else None,
            "logical_dpi": screen.logicalDotsPerInch() if screen else None,
        }
        if dialog:
            dialog.close()
        window.close()
        app.processEvents()
        return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", choices=(*PAGES, "all"), action="append", default=[])
    parser.add_argument("--state", choices=STATES, default="normal")
    parser.add_argument("--size", type=parse_size, action="append", default=[])
    parser.add_argument("--scale", type=float, action="append", default=[])
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "ui-review")
    args = parser.parse_args()
    pages = list(PAGES if "all" in args.page else (args.page or PAGES))
    sizes = args.size or [(1366, 768), (1920, 1080), (2560, 1440)]
    scales = args.scale or [1.0]
    if len(scales) != 1:
        parser.error("run once per --scale so Qt can apply it before QApplication starts")
    # Qt only reads this at QApplication creation.  Requiring one scale per
    # invocation avoids silently producing an incorrectly labelled matrix.
    os.environ["QT_SCALE_FACTOR"] = str(scales[0])
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    entries = [capture_one(app, page, args.state, size, scale, output)
               for page in pages for size in sizes for scale in scales]
    manifest = output / f"matrix-{QDateTime.currentDateTimeUtc().toString('yyyyMMdd-hhmmss')}.json"
    manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"captured {len(entries)} local-only screenshots to {output}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
