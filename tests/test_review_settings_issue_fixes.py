import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from scripts.invoice_fetch.gui.invoice_detail_panel import InvoiceDetailPanel
from scripts.invoice_fetch.gui.review_settings_issue_fixes import (
    apply_review_attachment_action_fix,
    apply_settings_action_clarity,
)
from scripts.invoice_fetch.gui.ui_components import SecondaryNavStack


_QAPP = None


def _app():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication(sys.argv)
    return _QAPP


def _install_version_footer(window, parent):
    container = QFrame(parent)
    layout = QHBoxLayout(container)
    window.status_actions_container = container
    window.lbl_version = QLabel("v0.1.4", container)
    layout.addWidget(window.lbl_version)
    return container


class ReviewAttachmentActionFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _make_window(self):
        window = QMainWindow()
        page = QWidget(window)
        layout = QVBoxLayout(page)
        detail = InvoiceDetailPanel(parent=page)
        detail.btn_edit_reimbursement_title = QPushButton("公司开票信息", detail)
        detail.layout().addWidget(detail.btn_edit_reimbursement_title)
        layout.addWidget(detail)
        layout.addWidget(_install_version_footer(window, page))
        window.setCentralWidget(page)
        window.review_page = page
        window._detail_panel = detail
        return window, page, detail

    def test_existing_original_keeps_open_primary_and_replace_in_material_row(self):
        window, page, detail = self._make_window()
        try:
            apply_review_attachment_action_fix(page)
            detail.set_attachment_state(
                has_file=True,
                has_url=True,
                file_name="invoice.pdf",
                file_path="C:/invoice.pdf",
                can_download=False,
            )

            self.assertIs(detail.original_status_line._action_widget, detail.btn_open_file)
            self.assertEqual(detail.btn_add_attachment.text(), "替换原件")
            self.assertIs(detail.btn_open_file.parentWidget(), detail.original_status_line)
            self.assertIs(detail.btn_add_attachment.parentWidget(), detail.original_status_line)
            self.assertGreaterEqual(
                detail.original_status_line.layout().indexOf(detail.btn_add_attachment),
                0,
            )
            self.assertFalse(detail.btn_open_file.isHidden())
            self.assertFalse(detail.btn_add_attachment.isHidden())
            self.assertTrue(detail.btn_retry_download.isHidden())
            self.assertIsNot(detail.btn_add_attachment.parentWidget(), detail.summary_card)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_downloadable_missing_original_keeps_download_primary_and_supplement_secondary(self):
        window, page, detail = self._make_window()
        try:
            apply_review_attachment_action_fix(page)
            detail.set_attachment_state(
                has_file=False,
                has_url=True,
                file_name="",
                file_path="",
                can_download=True,
            )

            self.assertIs(
                detail.original_status_line._action_widget,
                detail.btn_retry_download,
            )
            self.assertEqual(detail.btn_add_attachment.text(), "补充原件")
            self.assertEqual(detail.btn_retry_download.text(), "重新下载")
            self.assertTrue(detail.btn_open_file.isHidden())
            self.assertFalse(detail.btn_add_attachment.isHidden())
            self.assertFalse(detail.btn_retry_download.isHidden())
            self.assertIs(detail.btn_retry_download.parentWidget(), detail.original_status_line)
            self.assertIs(detail.btn_add_attachment.parentWidget(), detail.original_status_line)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_missing_original_without_download_keeps_supplement_as_primary(self):
        window, page, detail = self._make_window()
        try:
            apply_review_attachment_action_fix(page)
            detail.set_attachment_state(has_file=False, has_url=False)

            self.assertIs(
                detail.original_status_line._action_widget,
                detail.btn_add_attachment,
            )
            self.assertEqual(detail.btn_add_attachment.text(), "补充原件")
            self.assertFalse(detail.btn_add_attachment.isHidden())
            self.assertTrue(detail.btn_open_file.isHidden())
            self.assertTrue(detail.btn_retry_download.isHidden())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_review_removes_company_button_and_footer_version_chip(self):
        window, page, detail = self._make_window()
        company_button = detail.btn_edit_reimbursement_title
        version = window.lbl_version
        try:
            apply_review_attachment_action_fix(page)

            self.assertTrue(company_button.isHidden())
            self.assertTrue(company_button.property("reviewCompanyActionRemoved"))
            self.assertIs(company_button.parentWidget(), detail)
            self.assertTrue(version.isHidden())
            self.assertTrue(version.property("reviewFooterVersionRemoved"))
            self.assertIs(version.parentWidget(), window)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()


class SettingsActionClarityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _make_window(self):
        window = QMainWindow()
        page = QWidget(window)
        page_layout = QVBoxLayout(page)
        tabs = SecondaryNavStack(page)
        for title in (
            "邮箱账户",
            "AI 配置",
            "运行状态",
            "安全与隐私",
            "数据与备份",
            "关于",
        ):
            tabs.addTab(QWidget(), title)
        page_layout.addWidget(tabs)
        page_layout.addWidget(_install_version_footer(window, page))
        window.setCentralWidget(page)
        window.settings_tabs = tabs
        window.config = {
            "reimbursement": {
                "buyer_name": "示例科技有限公司",
                "buyer_tax_id": "911100000000000000",
                "strict_buyer_check": True,
            }
        }

        window.btn_settings_mailbox_add = QPushButton("新增账号", page)
        window.btn_settings_mailbox_add_credential = QPushButton("补授权码", page)
        window.btn_settings_mailbox_edit_config = QPushButton("编辑", page)
        window.btn_settings_mailbox_scan = QPushButton("立即扫描", page)
        window.btn_settings_mailbox_test = QPushButton("测试连接", page)
        window.btn_settings_mailbox_toggle = QPushButton("停用", page)
        window.settings_mailbox_more = QToolButton(page)
        window.settings_mailbox_more.setText("⋯")
        window.settings_mailbox_more_update_credential = window.settings_mailbox_more.addAction(
            "更新授权码"
        )
        window.settings_mailbox_more_toggle = window.settings_mailbox_more.addAction("停用")
        window.settings_mailbox_list = tabs.nav_list
        window._refresh_settings_page = lambda: None
        return window, page

    def test_settings_adds_company_profile_as_second_navigation_page(self):
        window, page = self._make_window()
        try:
            ai_page = window.settings_tabs.widget(1)
            apply_settings_action_clarity(page)

            self.assertEqual(window.settings_tabs.count(), 6)
            self.assertEqual(window.settings_tabs.nav_list.count(), 7)
            self.assertEqual(
                [
                    window.settings_tabs.nav_list.item(i).text()
                    for i in range(window.settings_tabs.nav_list.count())
                ],
                [
                    "邮箱账户",
                    "开票信息",
                    "AI 配置",
                    "运行状态",
                    "安全与隐私",
                    "数据与备份",
                    "关于",
                ],
            )
            self.assertIs(window.settings_tabs.widget(1), ai_page)
            company_item = window.settings_tabs.nav_list.item(1)
            self.assertEqual(company_item.data(Qt.UserRole), "company_tax_profile")
            window.settings_tabs.nav_list.setCurrentRow(1)
            self.assertIs(window.settings_tabs.currentWidget(), window.settings_company_profile_page)
            self.assertEqual(
                window.settings_company_profile_values["单位名称"].text(),
                "示例科技有限公司",
            )
            self.assertEqual(window.btn_settings_mailbox_add.text(), "＋ 添加邮箱账号")
            self.assertGreaterEqual(window.btn_settings_mailbox_add.minimumWidth(), 132)
            self.assertEqual(window.btn_settings_mailbox_add.property("variant"), "primary")
            self.assertTrue(window.lbl_version.isHidden())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_compatibility_index_one_still_selects_ai_page(self):
        window, page = self._make_window()
        try:
            ai_page = window.settings_tabs.widget(1)
            apply_settings_action_clarity(page)
            window.settings_tabs.setCurrentIndex(1)

            self.assertIs(window.settings_tabs.currentWidget(), ai_page)
            self.assertEqual(window.settings_tabs.currentIndex(), 1)
            self.assertEqual(window.settings_tabs.nav_list.currentRow(), 2)
            self.assertEqual(window.settings_tabs.tabText(1), "AI 配置")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_missing_credential_keeps_edit_and_more_visible(self):
        window, page = self._make_window()
        window.btn_settings_mailbox_add_credential.show()
        try:
            apply_settings_action_clarity(page)

            self.assertEqual(
                window.btn_settings_mailbox_add_credential.text(),
                "设置授权码",
            )
            self.assertEqual(window.btn_settings_mailbox_edit_config.text(), "编辑")
            self.assertFalse(window.btn_settings_mailbox_add_credential.isHidden())
            self.assertFalse(window.btn_settings_mailbox_edit_config.isHidden())
            self.assertFalse(window.settings_mailbox_more.isHidden())
            self.assertTrue(window.btn_settings_mailbox_scan.isHidden())
            self.assertTrue(window.btn_settings_mailbox_test.isHidden())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
