from __future__ import annotations

from pathlib import Path


def replace_bytes(path: str, old: bytes, new: bytes) -> None:
    target = Path(path)
    data = target.read_bytes()
    count = data.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one byte match, found {count}")
    target.write_bytes(data.replace(old, new, 1))


# app.py has historical mixed line endings. Replace only the exact line bytes
# and keep every untouched byte unchanged.
replace_bytes(
    "scripts/invoice_fetch/gui/app.py",
    b"        content_row.addWidget(self.overview_content_host, 8, Qt.AlignTop)\n",
    b"        content_row.addWidget(self.overview_content_host, 8)\n",
)

path = Path("tests/test_v018_post_merge_ux_regressions.py")
text = path.read_text(encoding="utf-8")
old = '''                window.resize(1600, 900)\n                window._nav_collapsed_manual = True\n                window._apply_workbench_metrics(1600, 900)\n                window._switch_main_page("overview")\n                for _ in range(6):\n                    self.qt_app.processEvents()\n'''
new = '''                window.resize(1600, 900)\n                window.show()\n                for _ in range(4):\n                    self.qt_app.processEvents()\n                window._nav_collapsed_manual = True\n                window._apply_workbench_metrics(1600, 900)\n                window._switch_main_page("overview")\n                for _ in range(6):\n                    self.qt_app.processEvents()\n'''
if text.count(old) != 1:
    raise RuntimeError("focused wide-dashboard test block not found exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
