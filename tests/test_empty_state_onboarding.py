from pathlib import Path

from PySide6.QtWidgets import QApplication

from scripts.invoice_fetch.gui.app import InvoiceReviewApp


_APP = QApplication.instance() or QApplication([])
_APP.setQuitOnLastWindowClosed(False)


def test_empty_review_state_shows_three_steps_and_routes_actions(tmp_path: Path):
    window = InvoiceReviewApp(tmp_path / "empty.db", splash=None)
    window.show()
    _APP.processEvents()
    try:
        window._load_invoices()
        _APP.processEvents()

        assert window.lbl_empty_title.text() == "当前没有发票记录"
        assert window.left_stack.currentWidget() is window.empty_widget
        assert window.empty_onboarding_widget.isVisible()
        assert not window.empty_filter_actions.isVisible()
        assert len(window.empty_step_cards) == 3
        assert [card.findChildren(type(window.lbl_empty_title))[0].text() for card in window.empty_step_cards] == [
            "01  导入票据", "02  核对发票", "03  归组并导出",
        ]
        assert "扫码上传" in window.lbl_guide.text()

        window.empty_btn_review.click()
        _APP.processEvents()
        assert window.center_stack.currentWidget() is window.review_page

        window.empty_btn_export.click()
        _APP.processEvents()
        assert window.center_stack.currentWidget() is window.export_page
    finally:
        window._splitter_save_timer.stop()
        window.close()
        _APP.processEvents()


def test_filtered_no_match_uses_filter_recovery_actions_not_onboarding(tmp_path: Path):
    window = InvoiceReviewApp(tmp_path / "filtered.db", splash=None)
    window.show()
    _APP.processEvents()
    try:
        window.db.insert_invoice({
            "invoice_number": "EMPTY-STATE-RECOVERY",
            "total_amount": "10.00",
            "seller_name": "Example Seller",
        })
        window.txt_search.setText("not a match")
        window._load_invoices()
        _APP.processEvents()

        assert window.lbl_empty_title.text() == "没有符合条件的发票"
        assert not window.empty_onboarding_widget.isVisible()
        assert window.empty_filter_actions.isVisible()
        assert window.empty_btn_clear_search.isVisible()
        assert window.empty_btn_reset_filters.isVisible()
    finally:
        window._splitter_save_timer.stop()
        window.close()
        _APP.processEvents()
