import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QPoint
except ImportError:
    QPoint = None

from scripts.invoice_fetch.db import InvoiceDB


class GuiColumnFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            import sys

            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(f"Skipping GUI tests: {exc}")

    def _make_window(self, rows):
        from scripts.invoice_fetch.gui.app import InvoiceReviewApp

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "column_filters.db"
        with InvoiceDB(db_path) as db:
            claim_ids = {}
            for row in rows:
                payload = {
                    "invoice_number": row.get("invoice_number", "INV"),
                    "expense_date": row.get("expense_date", "2026-06-01"),
                    "invoice_date": row.get("invoice_date", "2026-06-01"),
                    "total_amount": row.get("total_amount", "10.00"),
                    "seller_name": row.get("seller_name", "Seller"),
                    "buyer_name": row.get("buyer_name", "Buyer"),
                    "category": row.get("category", "餐饮"),
                    "review_status": row.get("review_status", "to_review"),
                    "mail_uid": row.get("mail_uid"),
                    "mail_sender": row.get("mail_sender", ""),
                    "attachment_path": row.get("attachment_path", "file.pdf"),
                    "download_url": row.get("download_url", ""),
                }
                inv_id = db.insert_invoice(payload)
                claim_name = row.get("claim_name")
                if claim_name:
                    if claim_name not in claim_ids:
                        claim_ids[claim_name] = db.create_claim_group(claim_name)
                    db.add_invoice_to_claim(claim_ids[claim_name], inv_id)

        config = {"reimbursement": {"strict_buyer_check": False}}
        config_patch = patch("scripts.invoice_fetch.gui.app.load_config_safe", return_value=config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        window = InvoiceReviewApp(db_path, splash=None)
        window._deferred_init()
        self.app.processEvents()

        def close_window():
            if getattr(window, "db", None) is not None:
                window.db.close()
            window.close()
            window.deleteLater()
            self.app.processEvents()

        self.addCleanup(close_window)
        return window

    def _numbers(self, window):
        return [row.get("invoice_number") for row in window.invoices_list]

    def test_categorical_filter_by_category(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮"},
            {"invoice_number": "HOTEL", "category": "住宿"},
        ])

        window._set_column_filter("category", {"values": {"住宿"}})

        self.assertEqual(self._numbers(window), ["HOTEL"])

    def test_text_filters_by_seller_and_invoice_number(self):
        window = self._make_window([
            {"invoice_number": "INV-A", "seller_name": "Alpha"},
            {"invoice_number": "INV-B", "seller_name": "Beta"},
        ])

        window._set_column_filter("seller_name", {"values": {"Alpha"}})
        self.assertEqual(self._numbers(window), ["INV-A"])
        window._set_column_filter("seller_name", {})
        window._set_column_filter("invoice_number", {"values": {"INV-B"}})
        self.assertEqual(self._numbers(window), ["INV-B"])

    def test_date_and_amount_filters(self):
        window = self._make_window([
            {"invoice_number": "LOW", "expense_date": "2026-06-01", "total_amount": "10"},
            {"invoice_number": "MID", "expense_date": "2026-06-02", "total_amount": "50"},
            {"invoice_number": "HIGH", "expense_date": "2026-06-02", "total_amount": "200"},
        ])

        window._set_column_filter("expense_date", {"values": {"2026-06-02"}})
        window._set_column_filter("total_amount", {"min": "20", "max": "100"})

        self.assertEqual(self._numbers(window), ["MID"])

    def test_multiple_filters_and_global_search_combine(self):
        window = self._make_window([
            {"invoice_number": "ALPHA-FOOD", "seller_name": "Alpha", "category": "餐饮"},
            {"invoice_number": "ALPHA-HOTEL", "seller_name": "Alpha", "category": "住宿"},
            {"invoice_number": "BETA-FOOD", "seller_name": "Beta", "category": "餐饮"},
        ])

        window.txt_search.setText("Alpha")
        window.search_reload_timer.stop()
        window._set_column_filter("category", {"values": {"餐饮"}})

        self.assertEqual(self._numbers(window), ["ALPHA-FOOD"])

    def test_reset_clears_filters_and_header_indicator(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "seller_name": "餐饮"},
            {"invoice_number": "HOTEL", "seller_name": "住宿"},
        ])

        window._set_column_filter("seller_name", {"values": {"住宿"}})
        self.assertIn("●", window.table.horizontalHeaderItem(3).text())
        window._reset_invoice_filters()

        self.assertEqual(window.column_filters, {})
        self.assertNotIn("●", window.table.horizontalHeaderItem(3).text())
        self.assertEqual(set(self._numbers(window)), {"FOOD", "HOTEL"})

    def test_header_center_click_does_not_open_filter_popup(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "seller_name": "餐饮"},
            {"invoice_number": "HOTEL", "seller_name": "住宿"},
        ])

        header = window.table.horizontalHeader()
        section = 3
        center_x = header.sectionViewportPosition(section) + header.sectionSize(section) // 2
        window._column_filter_header_press_pos = QPoint(center_x, header.height() // 2)
        window._show_column_filter_popup(section)
        self.app.processEvents()
        self.assertIsNone(window._column_filter_popup)

    def test_supported_headers_open_filter_popup_near_widened_marker_area(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "seller_name": "餐饮"},
            {"invoice_number": "HOTEL", "seller_name": "住宿"},
        ])

        header = window.table.horizontalHeader()
        section = 3
        near_marker_x = header.sectionViewportPosition(section) + header.sectionSize(section) - 10
        window._column_filter_header_press_pos = QPoint(near_marker_x, header.height() // 2)
        window._show_column_filter_popup(section)
        self.app.processEvents()

        popup = window._column_filter_popup
        self.assertIsNotNone(popup)
        self.assertEqual(popup.key, "seller_name")
        self.assertEqual(popup.search_edit.placeholderText(), "搜索值")
        self.assertEqual(popup.value_list.count(), 2)
        popup.close()

    def test_seller_header_visible_marker_opens_filter_popup(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        window = self._make_window([
            {"invoice_number": "A", "seller_name": "Alpha"},
            {"invoice_number": "B", "seller_name": "Beta"},
        ])
        window.resize(1500, 800)
        window.show()
        self.app.processEvents()

        header = window.table.horizontalHeader()
        section = 3
        item = window.table.horizontalHeaderItem(section)
        text_width = header.fontMetrics().horizontalAdvance(item.text())
        marker_width = header.fontMetrics().horizontalAdvance("▾")
        marker_x = (
            header.sectionViewportPosition(section)
            + (header.sectionSize(section) - text_width) // 2
            + text_width
            - marker_width // 2
        )
        QTest.mouseClick(
            header.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(marker_x, header.height() // 2),
        )
        self.app.processEvents()

        self.assertIsNotNone(window._column_filter_popup)
        self.assertEqual(window._column_filter_popup.key, "seller_name")
        window._column_filter_popup.close()

    def test_right_side_clickable_area_works_for_narrow_columns(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮"},
            {"invoice_number": "HOTEL", "category": "住宿"},
        ])

        section = 0
        window._ignore_min_widths = True
        window.table.setColumnWidth(section, 24)
        self.app.processEvents()
        header = window.table.horizontalHeader()
        right_edge_x = header.sectionViewportPosition(section) + header.sectionSize(section) - 1
        window._column_filter_header_press_pos = QPoint(right_edge_x, header.height() // 2)
        window._show_column_filter_popup(section)
        self.app.processEvents()

        self.assertIsNotNone(window._column_filter_popup)
        window._column_filter_popup.close()

    def test_active_filter_header_tooltip_is_clear(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "seller_name": "餐饮"},
            {"invoice_number": "HOTEL", "seller_name": "住宿"},
        ])

        window._set_column_filter("seller_name", {"values": {"住宿"}})
        tooltip = window.table.horizontalHeaderItem(3).toolTip()

        self.assertIn("已启用列筛选", tooltip)
        self.assertIn("点击右侧修改", tooltip)

    def test_inactive_filter_header_tooltip_is_clear(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "seller_name": "餐饮"},
            {"invoice_number": "HOTEL", "seller_name": "住宿"},
        ])

        tooltip = window.table.horizontalHeaderItem(3).toolTip()

        self.assertIn("点击列标题右侧筛选", tooltip)

    def test_empty_value_selection_remains_active_when_popup_reopens(self):
        from PySide6.QtCore import Qt

        window = self._make_window([
            {"invoice_number": "FOOD", "seller_name": "餐饮"},
            {"invoice_number": "HOTEL", "seller_name": "住宿"},
        ])

        window._set_column_filter("seller_name", {"values": set()})
        self.assertEqual(window.table.rowCount(), 0)
        self.assertIn("●", window.table.horizontalHeaderItem(3).text())
        header = window.table.horizontalHeader()
        window._column_filter_header_press_pos = QPoint(
            header.sectionViewportPosition(3) + header.sectionSize(3) - 10,
            header.height() // 2,
        )
        window._show_column_filter_popup(3)
        self.app.processEvents()

        popup = window._column_filter_popup
        self.assertFalse(popup.select_all.isChecked())
        self.assertTrue(all(
            popup.value_list.item(i).checkState() == Qt.Unchecked
            for i in range(popup.value_list.count())
        ))
        popup.close()

    def test_selection_is_preserved_when_selected_invoice_remains_visible(self):
        window = self._make_window([
            {"invoice_number": "FOOD-A", "category": "餐饮", "expense_date": "2026-06-03"},
            {"invoice_number": "FOOD-B", "category": "餐饮", "expense_date": "2026-06-02"},
            {"invoice_number": "HOTEL", "category": "住宿", "expense_date": "2026-06-01"},
        ])
        window.table.selectRow(1)
        self.app.processEvents()
        selected_id = window.current_invoice["id"]

        window._set_column_filter("category", {"values": {"餐饮"}})
        self.app.processEvents()

        self.assertEqual(window.current_invoice["id"], selected_id)

    def test_selection_falls_back_to_nearest_visible_row(self):
        window = self._make_window([
            {"invoice_number": "FOOD", "category": "餐饮", "expense_date": "2026-06-03"},
            {"invoice_number": "HOTEL-A", "category": "住宿", "expense_date": "2026-06-02"},
            {"invoice_number": "HOTEL-B", "category": "住宿", "expense_date": "2026-06-01"},
        ])
        window.table.selectRow(0)
        self.app.processEvents()

        window._set_column_filter("category", {"values": {"住宿"}})
        self.app.processEvents()

        self.assertEqual(window.table.currentRow(), 0)
        self.assertEqual(window.current_invoice["invoice_number"], "HOTEL-A")

    def test_filtering_and_load_all_cover_rows_beyond_first_100(self):
        rows = []
        for index in range(130):
            rows.append({
                "invoice_number": f"ROW-{index:03d}",
                "category": "目标" if index < 105 else "其他",
                "expense_date": f"2026-06-{(index % 28) + 1:02d}",
            })
        window = self._make_window(rows)
        self.assertEqual(window.table.rowCount(), 100)

        window._set_column_filter("category", {"values": {"目标"}})

        self.assertEqual(window.table.rowCount(), 100)
        self.assertEqual(window._limited_first_load_total, 105)
        self.assertIn("100 / 105", window._format_status_count_prefix())
        self.assertFalse(window.btn_load_all.isHidden())
        window._load_all_invoices_clicked()
        self.assertEqual(window.table.rowCount(), 105)
        self.assertTrue(all(row["category"] == "目标" for row in window.invoices_list))

    def test_first_column_naming_and_material_only(self):
        # 表格第一列显示审核状态，列名应为“状态”。
        window = self._make_window([
            {"invoice_number": "", "total_amount": "100.00", "review_status": "approved"},
        ])
        header_text = window.table.horizontalHeaderItem(0).text()
        self.assertTrue("状态" in header_text)
        
        # Check first column text
        item_text = window.table.item(0, 0).text()
        self.assertEqual(item_text, "已通过")

    def test_top_checkbox_bidirectional_sync_needs_fix(self):
        # 勾选“待补全”等价于资料状态列过滤。
        # 清除资料状态列过滤会同步取消顶部“待补全”。
        window = self._make_window([
            {"invoice_number": "INV-1", "category": "餐饮"}, # 正常
            {"invoice_number": "", "total_amount": "50.00"}, # 待补全
        ])
        
        # Check that needs_fix checkbox is initially unchecked
        self.assertFalse(window.chk_needs_fix.isChecked())
        
        # Toggle top checkbox to check
        window.chk_needs_fix.setChecked(True)
        self.app.processEvents()
        
        # Check that it filters to only needs_fix (which is the empty invoice number row)
        self.assertEqual(len(window.invoices_list), 1)
        self.assertEqual(window.invoices_list[0]["total_amount"], "50.00")
        
        # Verify column_filters has been updated
        self.assertIn("status", window.column_filters)
        
        # Clear column filter status manually
        window._set_column_filter("status", {})
        self.app.processEvents()
        
        # Check that top checkbox is automatically unchecked
        self.assertFalse(window.chk_needs_fix.isChecked())
        # Check that all invoices are loaded again
        self.assertEqual(len(window.invoices_list), 2)

    def test_top_checkbox_bidirectional_sync_unlinked(self):
        # 勾选“未关联报销组”等价于报销组列过滤为未加入。
        # 清除报销组列过滤会同步取消顶部“未关联报销组”。
        window = self._make_window([
            {"invoice_number": "INV-1", "claim_name": "Group-A"},
            {"invoice_number": "INV-2", "claim_name": ""},
        ])
        
        self.assertFalse(window.chk_unlinked.isChecked())
        
        # Check unlinked
        window.chk_unlinked.setChecked(True)
        self.app.processEvents()
        
        self.assertEqual(len(window.invoices_list), 1)
        self.assertEqual(window.invoices_list[0]["invoice_number"], "INV-2")
        
        # Clear claim_name filter manually
        window._set_column_filter("claim_name", {})
        self.app.processEvents()
        
        self.assertFalse(window.chk_unlinked.isChecked())
        self.assertEqual(len(window.invoices_list), 2)

    def test_reset_clears_all_filter_states_chips_and_markers(self):
        # 重置会清空顶部过滤、搜索、列过滤、active marker、筛选摘要。
        window = self._make_window([
            {"invoice_number": "INV-1", "category": "餐饮"},
            {"invoice_number": "", "total_amount": "50.00"},
        ])
        
        window.txt_search.setText("INV")
        window.chk_needs_fix.setChecked(True)
        window._set_column_filter("seller_name", {"values": {"餐饮"}})
        window.current_filter_status = "approved"
        
        self.app.processEvents()
        
        # Reset
        window._reset_invoice_filters()
        self.app.processEvents()
        
        self.assertEqual(window.txt_search.text(), "")
        self.assertFalse(window.chk_needs_fix.isChecked())
        self.assertFalse(window.chk_unlinked.isChecked())
        self.assertEqual(window.column_filters, {})
        self.assertIsNone(window.current_filter_status)
        self.assertFalse(window.filter_chips_widget.isVisible())
        self.assertNotIn("●", window.table.horizontalHeaderItem(3).text())

    def test_top_review_counts_dynamic_under_non_review_filters(self):
        # 顶部审核状态数字在待补全过滤条件下仍正确。
        window = self._make_window([
            {"invoice_number": "INV-1", "review_status": "approved"}, # 正常, approved
            {"invoice_number": "", "total_amount": "50.00", "review_status": "to_review"}, # 待补全, to_review
            {"invoice_number": "", "total_amount": "10.00", "review_status": "approved"}, # 待补全, approved
        ])
        
        # Apply "待补全" filter
        window.chk_needs_fix.setChecked(True)
        self.app.processEvents()
        
        # Buttons texts should reflect only the "待补全" invoices (which are 2 in total: 1 to_review, 1 approved)
        to_review_text = window.filter_buttons["to_review"].text()
        approved_text = window.filter_buttons["approved"].text()
        all_text = window.filter_buttons["all"].text()
        
        self.assertTrue("1" in to_review_text)
        self.assertTrue("1" in approved_text)
        self.assertTrue("2" in all_text)
        self.assertEqual(all_text.split()[0], "当前范围全部")

    @patch("scripts.invoice_fetch.link_downloader.LinkDownloader")
    @patch("scripts.invoice_fetch.invoice_parser.InvoiceParser")
    def test_redownload_direct_ofd_download_should_not_call_pdf_parser(self, mock_parser_cls, mock_dl_cls):
        mock_dl = mock_dl_cls.return_value
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        ofd_file = Path(temp_dir.name) / "test.ofd"
        ofd_file.write_bytes(b"OFD content")

        class FakeDownloadedFile:
            file_path = str(ofd_file)

        mock_dl._download_url.return_value = FakeDownloadedFile()

        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_pdf.side_effect = AssertionError("parse_pdf should not be called for OFD")

        window = self._make_window([
            {
                "invoice_number": "OFD123",
                "download_url": "http://example.com/inv.ofd",
                "mail_uid": 1001,
                "mail_date": "2026-06-19",
                "attachment_path": "",
            }
        ])

        window.table.selectRow(0)

        with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            window._redownload_selected_invoices()

        mock_parser.parse_pdf.assert_not_called()

    @patch("scripts.invoice_fetch.link_downloader.LinkDownloader")
    @patch("scripts.invoice_fetch.invoice_parser.InvoiceParser")
    def test_redownload_direct_ofd_download_should_keep_original_and_mark_manual_required(self, mock_parser_cls, mock_dl_cls):
        mock_dl = mock_dl_cls.return_value
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        ofd_file = Path(temp_dir.name) / "test.ofd"
        ofd_file.write_bytes(b"OFD content")

        class FakeDownloadedFile:
            file_path = str(ofd_file)

        mock_dl._download_url.return_value = FakeDownloadedFile()
        mock_parser = mock_parser_cls.return_value

        window = self._make_window([
            {
                "invoice_number": "OFD456",
                "download_url": "http://example.com/inv.ofd",
                "mail_uid": 1002,
                "mail_date": "2026-06-19",
                "attachment_path": "",
            }
        ])
        inv_id = window.invoices_list[0]["id"]

        window.table.selectRow(0)

        with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            window._redownload_selected_invoices()

        refreshed = window.db.get_invoice(inv_id)
        att_path = refreshed.get("attachment_path")
        self.assertTrue(att_path.endswith(".ofd"))

        resolved_path = Path(window._resolve_attachment_path(att_path))
        self.assertTrue(resolved_path.exists())
        self.assertEqual(resolved_path.read_bytes(), b"OFD content")

        self.assertIn("OFD 原件已恢复，需手动处理/转换后再解析。", refreshed.get("parse_note"))
        mock_warn.assert_not_called()
        mock_info.assert_called_once()
        summary_msg = mock_info.call_args[0][2]
        self.assertIn("仅刷新元数据/待手动下载: 1 张", summary_msg)
        self.assertIn("下载失败: 0 张", summary_msg)

    @patch("scripts.invoice_fetch.link_downloader.LinkDownloader")
    @patch("scripts.invoice_fetch.invoice_parser.InvoiceParser")
    def test_redownload_direct_pdf_parse_failure_should_keep_failure_bucket(self, mock_parser_cls, mock_dl_cls):
        mock_dl = mock_dl_cls.return_value
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        pdf_file = Path(temp_dir.name) / "test.pdf"
        pdf_file.write_bytes(b"invalid pdf content")

        class FakeDownloadedFile:
            file_path = str(pdf_file)

        mock_dl._download_url.return_value = FakeDownloadedFile()

        mock_parser = mock_parser_cls.return_value
        class FakeParsedInfo:
            parse_success = False
            parse_note = "corrupted pdf structure"
        mock_parser.parse_pdf.return_value = FakeParsedInfo()

        window = self._make_window([
            {
                "invoice_number": "PDF789",
                "download_url": "http://example.com/inv.pdf",
                "mail_uid": None,
                "mail_date": "2026-06-19",
                "attachment_path": "",
            }
        ])

        window.table.selectRow(0)

        with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            window._redownload_selected_invoices()

        self.assertFalse(pdf_file.exists())
        mock_warn.assert_called_once()
        summary_msg = mock_warn.call_args[0][2]
        self.assertIn("下载失败: 1 张", summary_msg)
        self.assertIn("链接下载后解析失败: corrupted pdf structure", summary_msg)

    @patch("scripts.invoice_fetch.link_downloader.LinkDownloader")
    @patch("scripts.invoice_fetch.mail_fetcher.MailFetcher")
    @patch("scripts.invoice_fetch.__main__._handle_pending_email")
    @patch("scripts.invoice_fetch.credentials.has_auth_code", return_value=True)
    @patch("scripts.invoice_fetch.credentials.get_auth_code", return_value="fake_code")
    @patch("scripts.invoice_fetch.config.get_email_accounts")
    def test_redownload_duplicate_missing_file_should_still_report_not_restored(
        self, mock_get_accounts, mock_has_auth, mock_get_auth, mock_handle_email, mock_mail_fetcher, mock_dl_cls
    ):
        mock_get_accounts.return_value = [{"address": "test@example.com", "mailbox_key": "legacy"}]
        mock_dl = mock_dl_cls.return_value
        mock_dl._download_url.return_value = None

        class FakeRereadResult:
            status = "duplicate"
        mock_handle_email.return_value = FakeRereadResult()

        window = self._make_window([
            {
                "invoice_number": "DUP999",
                "download_url": "",
                "mail_uid": 1003,
                "mail_date": "2026-06-19",
                "attachment_path": "non_existent_file.pdf",
            }
        ])

        window.table.selectRow(0)

        with patch("PySide6.QtWidgets.QMessageBox.information") as mock_info, \
             patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
            window._redownload_selected_invoices()

        mock_warn.assert_called_once()
        summary_msg = mock_warn.call_args[0][2]
        self.assertIn("下载失败: 1 张", summary_msg)
        self.assertNotIn("仅命中已有重复记录: 1 张", summary_msg)

    def test_column_header_minimum_widths_and_label_visibility(self):
        window = self._make_window([
            {"invoice_number": "A", "seller_name": "Alpha"},
        ])
        window.resize(1200, 800)
        window.show()
        self.app.processEvents()

        # 1. Verify minimum widths
        expected_min_widths = {
            0: 76,   # 状态
            1: 100,  # 费用日期
            2: 80,   # 金额
            3: 260,  # 销售方
            4: 160,  # 发票号
        }
        for index, min_w in expected_min_widths.items():
            self.assertGreaterEqual(
                window.table.columnWidth(index), min_w,
                f"Column {index} width is {window.table.columnWidth(index)}, expected at least {min_w}"
            )

        # 2. Verify that resizing below minimum width is blocked/corrected
        for index, min_w in expected_min_widths.items():
            if index == 3:
                continue
            window.table.setColumnWidth(index, 20)
            self.app.processEvents()
            self.assertEqual(
                window.table.columnWidth(index), min_w,
                f"Column {index} width did not revert to minimum {min_w}"
            )


if __name__ == "__main__":
    unittest.main()
