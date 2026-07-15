import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QScrollArea, QWidget

from scripts.dev.capture_design_v1 import _classify_geometry_widget


class CaptureGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_button_inside_parent_passes(self):
        parent = QWidget(); parent.resize(200, 100)
        button = QPushButton("OK", parent); button.setGeometry(10, 10, 80, 30)
        parent.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(button)[0], "PASS")

    def test_button_outside_parent_fails(self):
        parent = QWidget(); parent.resize(200, 100)
        button = QPushButton("OK", parent); button.setGeometry(240, 10, 80, 30)
        parent.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(button)[0], "FAIL")

    def test_button_text_wider_than_button_fails(self):
        parent = QWidget(); parent.resize(200, 100)
        button = QPushButton("A very long button label", parent); button.setGeometry(10, 10, 20, 30)
        parent.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(button)[0], "FAIL")

    def test_blank_clickable_button_fails(self):
        parent = QWidget(); parent.resize(200, 100)
        button = QPushButton(parent); button.setGeometry(10, 10, 20, 20)
        parent.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(button)[0], "FAIL")

    def test_offscreen_business_button_is_not_silently_ignored(self):
        parent = QWidget(); parent.resize(200, 100)
        button = QPushButton("legacy", parent); button.setGeometry(10, 10, 80, 30)
        button.setAttribute(Qt.WA_DontShowOnScreen, True)
        parent.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(button)[0], "FAIL")

    def test_scroll_content_is_ignored(self):
        scroll = QScrollArea(); scroll.resize(200, 100)
        content = QWidget(); content.resize(500, 500)
        button = QPushButton("OK", content); button.setGeometry(400, 400, 80, 30)
        scroll.setWidget(content); scroll.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(button)[0], "IGNORED")

    def test_popup_is_ignored(self):
        menu = QMenu(); menu.addAction("Action"); menu.show(); self.app.processEvents()
        self.assertEqual(_classify_geometry_widget(menu)[0], "IGNORED")
        menu.close()


if __name__ == "__main__":
    unittest.main()
