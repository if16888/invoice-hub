"""Regression tests for P1-26 (no emoji in the GUI) and P2-4 warning tooltip."""

import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
EMOJI = re.compile("[\U0001F000-\U0001FAFF]")


class IconLanguageTests(unittest.TestCase):
    def test_gui_sources_carry_no_emoji(self):
        offenders = []
        for path in sorted((ROOT / "scripts/invoice_fetch/gui").rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if EMOJI.search(text):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_export_status_uses_text_markers(self):
        source = (ROOT / "scripts/invoice_fetch/claim_export.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("注意 发现", source)
        self.assertIn("合格", source)
        self.assertNotIn("⚠", source)

    def test_buyer_warning_prefix_is_plain_text_with_full_tooltip(self):
        source = (
            ROOT / "scripts/invoice_fetch/gui/buyer_warning_controller.py"
        ).read_text(encoding="utf-8")
        self.assertIn('label.setText(f"注意 {display_text}"', source)
        self.assertIn("label.setToolTip(display_text)", source)


if __name__ == "__main__":
    unittest.main()
