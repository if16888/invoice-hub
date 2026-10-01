"""User-flow and external-input regressions from the September product audit."""

import json
import multiprocessing
import socket
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.invoice_fetch.ai_classifier import AIClassifier
from scripts.invoice_fetch.complete_backup import create_complete_backup, restore_complete_backup
from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.mobile_upload import MobileUploadServer, _parse_multipart_upload
from scripts.invoice_fetch.pdf_boundary import run_pdf_operation
from scripts.invoice_fetch.url_utils import _mask_url


@pytest.fixture
def window(tmp_path):
    from PySide6.QtWidgets import QApplication
    from scripts.invoice_fetch.gui.app import InvoiceReviewApp
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "invoices.db"
    with InvoiceDB(path) as db:
        for i in range(2):
            db.insert_invoice({"invoice_number": f"AUDIT-{i}", "total_amount": "100.00", "seller_name": "Synthetic", "invoice_date": f"2026-09-{29-i}"})
    view = InvoiceReviewApp(path)
    view.show()
    view._switch_main_page("review")
    view._ensure_single_row_selection(0)
    app.processEvents()
    yield view, app
    view.close()
    view.deleteLater()
    app.processEvents()


def test_note_survives_selection_refresh_and_restart(window):
    view, app = window
    invoice_id = view.current_invoice["id"]
    view._detail_panel.btn_toggle_note.click()
    view.txt_note.setPlainText("合成项目：调试设备的出差说明")
    assert view.db.get_invoice(invoice_id)["confirmed_note"] == "合成项目：调试设备的出差说明"
    view._ensure_single_row_selection(1)
    view._load_invoices()
    view._switch_main_page("settings")
    app.processEvents()
    with InvoiceDB(view.db_path) as reopened:
        assert reopened.get_invoice(invoice_id)["confirmed_note"] == "合成项目：调试设备的出差说明"


def test_note_write_failure_preserves_editor_and_selection(window):
    view, app = window
    invoice_id = view.current_invoice["id"]
    with patch.object(view.db, "update_invoice_note", return_value=False):
        view.txt_note.setPlainText("必须保留的合成备注")
        view._ensure_single_row_selection(1)
        view._load_invoices()
        app.processEvents()
        assert view.current_invoice["id"] == invoice_id
        assert view.txt_note.toPlainText() == "必须保留的合成备注"
        assert "保存失败" in view._detail_panel.lbl_note_save_status.text()
    assert view._persist_invoice_note()


def test_partial_draft_and_first_claim_are_actionable(window):
    from PySide6.QtWidgets import QInputDialog
    from scripts.invoice_fetch.gui.invoice_detail_panel import EditFieldsDialog
    view, app = window
    dialog = EditFieldsDialog(view._detail_panel, "", "2026-09-30", "", "交通", "合成购买方", "")
    assert dialog.values()["amount"] == ""
    assert dialog.values()["buyer"] == "合成购买方"
    dialog.deleteLater()
    view._switch_main_page("export")
    assert view.btn_export_create_group.isVisible()
    assert view.btn_export_choose_invoices.isVisible()
    with patch.object(QInputDialog, "getText", return_value=("合成九月差旅", True)):
        view.btn_export_create_group.click()
    assert view.db.list_claim_groups()[0]["name"] == "合成九月差旅"
    assert view.center_stack.currentWidget() is view.review_page


def test_ai_and_export_do_not_send_free_form_secrets():
    ai = AIClassifier(provider="none")
    prompt = ai._build_user_message([{"uid": 1, "subject": "张三 南京秘密项目发票订单123456789012 下载 https://example.invalid/tokenABC", "sender": '"张三" <private.account@example.invalid>'}])
    uncertain = ai._parse_response('["invalid"]', [{"uid": 1}])
    assert uncertain[0]["is_invoice"] is None
    uncertain = ai._parse_response('[{"uid": 1, "is_invoice": null}]', [{"uid": 1}])
    assert uncertain[0]["is_invoice"] is None
    assert "发票" in prompt and "下载" in prompt
    for secret in ("张三", "南京", "秘密项目", "123456789012", "tokenABC", "example.invalid", "private.account"):
        assert secret not in prompt
    assert "12****12" in ai._mask_sensitive_info("订单123456789012")
    assert _mask_url("https://person:password@example.invalid/secret-token?api_key=secret#secret") == "https://example.invalid/<redacted>"
    assert _mask_url("https://[invalid") == "<url:redacted>"


def _request(server, session, headers, body=b"", half_close=False):
    with socket.create_connection(("127.0.0.1", session.port), timeout=3) as client:
        client.sendall(f"POST /api/upload/{session.token} HTTP/1.0\r\nHost: localhost\r\n{headers}\r\n\r\n".encode() + body)
        if half_close:
            client.shutdown(socket.SHUT_WR)
        return client.recv(65536).decode()


def test_mobile_rejects_negative_duplicate_chunked_and_slow_bodies(tmp_path):
    server = MobileUploadServer(runtime_dir=tmp_path, host="127.0.0.1", bind_host="127.0.0.1", read_timeout_seconds=0.2)
    session = server.start()
    try:
        for headers in ("Content-Length: -1", "Content-Length: 0", "Content-Length: 1\r\nContent-Length: 1", "Transfer-Encoding: chunked", ""):
            assert "400" in _request(server, session, headers)
        assert "408" in _request(server, session, "Content-Length: 100", b"partial")
        deadline = time.monotonic() + 1
        while server._request_bytes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server._request_bytes == 0
        assert server.status()["accepted"] == 0
    finally:
        server.stop()


def test_multipart_preserves_binary_file_identity():
    original = b"\r\n%PDF synthetic\x00\r\n\r\n"
    body = b'--audit\r\nContent-Disposition: form-data; name="files"; filename="sample.pdf"\r\n\r\n' + original + b"\r\n--audit--\r\n"
    files = _parse_multipart_upload(body, "multipart/form-data; boundary=audit")
    assert files[0].content == original
    with pytest.raises(ValueError):
        _parse_multipart_upload(body[:-12], "multipart/form-data; boundary=audit")


def _backup_source(tmp_path):
    runtime = tmp_path / "source"
    (runtime / "attachments").mkdir(parents=True)
    (runtime / "attachments" / "original.pdf").write_bytes(b"Synthetic original")
    (runtime / "attachments" / "proof.txt").write_bytes(b"Synthetic proof")
    (runtime / "config.json").write_text('{"secret":"not-for-backup"}')
    path = runtime / "invoices.db"
    with InvoiceDB(path) as db:
        invoice_id = db.insert_invoice({"invoice_number": "BACKUP", "total_amount": "100", "attachment_path": "attachments/original.pdf", "extra_paths": ["attachments/proof.txt"]})
        db.update_invoice_note(invoice_id, "Synthetic note")
        claim = db.create_claim_group("Synthetic claim")
        db.add_invoice_to_claim(claim, invoice_id)
    return runtime, path, invoice_id


def test_complete_backup_restores_materials_notes_and_claims_on_another_machine(tmp_path):
    runtime, path, invoice_id = _backup_source(tmp_path)
    archive = create_complete_backup(path, runtime)
    with zipfile.ZipFile(archive) as packed:
        assert "config.json" not in packed.namelist()
    target = tmp_path / "other-machine"
    target_db = target / "invoices.db"
    with InvoiceDB(target_db):
        pass
    restore_complete_backup(archive, target_db, target)
    with InvoiceDB(target_db) as db:
        invoice = db.get_invoice(invoice_id)
        assert (target / invoice["attachment_path"]).read_bytes() == b"Synthetic original"
        assert (target / json.loads(invoice["extra_paths"])[0]).read_bytes() == b"Synthetic proof"
        assert invoice["confirmed_note"] == "Synthetic note"
        assert db.get_claim_invoices(db.list_claim_groups()[0]["id"])[0]["id"] == invoice_id


def test_corrupted_complete_backup_keeps_existing_database_and_originals(tmp_path):
    runtime, path, invoice_id = _backup_source(tmp_path)
    archive = create_complete_backup(path, runtime)
    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(damaged, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith(".pdf"):
                data = b"X" * len(data)
            target.writestr(name, data)
    with pytest.raises(ValueError, match="校验失败"):
        restore_complete_backup(damaged, path, runtime)
    with InvoiceDB(path) as db:
        assert db.get_invoice(invoice_id)["attachment_path"] == "attachments/original.pdf"
    assert (runtime / "attachments" / "original.pdf").read_bytes() == b"Synthetic original"
    assert not list((runtime / "attachments").glob("complete-restore-*"))


def test_complete_restore_validates_schema_before_path_writes_or_material_install(tmp_path):
    runtime, path, invoice_id = _backup_source(tmp_path)
    archive = create_complete_backup(path, runtime)
    before = path.read_bytes()
    with patch("scripts.invoice_fetch.complete_backup.validate_current_database", side_effect=ValueError("数据库包含非应用触发器")) as validate, \
            patch("scripts.invoice_fetch.complete_backup.sqlite3.connect") as connect, \
            patch("scripts.invoice_fetch.complete_backup.restore_verified_database_backup") as restore:
        with pytest.raises(ValueError, match="非应用触发器"):
            restore_complete_backup(archive, path, runtime)
    validate.assert_called_once()
    connect.assert_not_called()
    restore.assert_not_called()
    assert path.read_bytes() == before
    assert (runtime / "attachments" / "original.pdf").read_bytes() == b"Synthetic original"
    assert not list((runtime / "attachments").glob("complete-restore-*"))
    assert not list(runtime.glob("ih-restore-*"))


def _hung_parser(connection, path, mode):
    time.sleep(10)


def test_pdf_timeout_and_cancellation_leave_no_parser_process(tmp_path):
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"%PDF synthetic")
    before = {child.pid for child in multiprocessing.active_children()}
    ok, reason = run_pdf_operation(sample, timeout=0.15, child_target=_hung_parser)
    assert not ok and "超时" in reason
    ok, reason = run_pdf_operation(sample, cancel_check=lambda: True, child_target=_hung_parser)
    assert not ok and "取消" in reason
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_real_pdf_is_read_in_isolated_process(tmp_path):
    import pdfplumber
    from scripts.invoice_fetch.pdf_boundary import extract_pdf_text
    sample = tmp_path / "synthetic.pdf"
    # Use actual PDF text operators and a standard font, independently of the
    # runner's native fonts and Qt's platform-specific PDF drawing backend.
    stream = b"BT /F1 12 Tf 72 720 Td (SYNTHETIC invoice 100.00) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode("ascii") + content + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    sample.write_bytes(document)
    with pdfplumber.open(sample) as pdf:
        assert "SYNTHETIC" in pdf.pages[0].extract_text()
    ok, text = run_pdf_operation(sample, mode="text")
    assert ok, text
    assert "SYNTHETIC" in text
    assert "SYNTHETIC" in extract_pdf_text(sample)
    ok, result = run_pdf_operation(sample)
    assert ok and isinstance(result, dict) and "parse_success" in result
    assert sample.is_file()


def test_download_response_rejects_unknown_compressed_or_oversized_before_read():
    from unittest.mock import Mock
    from scripts.invoice_fetch.link_downloader import MAX_DOWNLOAD_BYTES, _bounded_response_body
    for headers in ({}, {"content-length": "3", "transfer-encoding": "chunked"}, {"content-length": str(MAX_DOWNLOAD_BYTES + 1)}, {"content-length": "100", "content-encoding": "gzip"}):
        response = Mock(headers=headers)
        assert _bounded_response_body(response) == b""
        response.body.assert_not_called()
    response = Mock(headers={"content-length": "3"})
    response.body.return_value = b"abc"
    assert _bounded_response_body(response) == b"abc"


def test_complete_backup_rejects_traversal_and_cancel_without_replacing_data(tmp_path):
    runtime, path, invoice_id = _backup_source(tmp_path)
    archive = create_complete_backup(path, runtime)
    with pytest.raises(ValueError, match="取消"):
        restore_complete_backup(archive, path, runtime, cancel_check=lambda: True)
    damaged = tmp_path / "traversal.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(damaged, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
        target.writestr("../outside.txt", "synthetic")
    with pytest.raises(ValueError, match="不一致"):
        restore_complete_backup(damaged, path, runtime)
    assert not (tmp_path / "outside.txt").exists()
    with InvoiceDB(path) as db:
        assert db.get_invoice(invoice_id)["attachment_path"] == "attachments/original.pdf"


def test_restore_database_failure_cleans_new_materials_and_keeps_originals(tmp_path):
    runtime, path, invoice_id = _backup_source(tmp_path)
    archive = create_complete_backup(path, runtime)
    with patch("scripts.invoice_fetch.complete_backup.restore_verified_database_backup", side_effect=OSError("synthetic disk failure")):
        with pytest.raises(OSError):
            restore_complete_backup(archive, path, runtime)
    assert not list((runtime / "attachments").glob("complete-restore-*"))
    assert (runtime / "attachments" / "original.pdf").read_bytes() == b"Synthetic original"
    with InvoiceDB(path) as db:
        assert db.get_invoice(invoice_id)["attachment_path"] == "attachments/original.pdf"


def test_complete_backup_gui_reopens_database_and_releases_operation_gate(window):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    import scripts.invoice_fetch.gui.app as gui_module
    view, app = window
    invoice_id = view.current_invoice["id"]
    view.txt_note.setPlainText("Synthetic before backup")

    def finish_worker():
        deadline = time.monotonic() + 10
        while view._complete_backup_worker.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not view._complete_backup_worker.isRunning()
        for _ in range(10):
            app.processEvents()

    with patch.object(gui_module, "RUNTIME_DIR", Path(view.db_path).parent), \
            patch.object(QMessageBox, "information"), \
            patch.object(QMessageBox, "warning") as warning, \
            patch.object(QMessageBox, "critical") as critical:
        view._start_complete_backup("create")
        finish_worker()
        archive = view._complete_backup_result_path
        assert archive.is_file()
        view.db.update_invoice_note(invoice_id, "Synthetic after backup")
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(archive), "")), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            page = view.center_stack.currentWidget()
            view._start_complete_backup("restore")
            view._switch_main_page("overview")
            assert view.center_stack.currentWidget() is page
            finish_worker()
        assert view.db.is_open
        assert view.center_stack.isEnabled()
        assert view.db.get_invoice(invoice_id)["confirmed_note"] == "Synthetic before backup"
        assert not view._data_operation_busy_reason()
        warning.assert_not_called()
        critical.assert_not_called()


def _partial_result_parser(output, path, mode):
    Path(output).with_suffix('.part').write_text('[true, "unfinished')
    time.sleep(3)


def test_partial_pdf_result_does_not_suspend_deadline_or_cancel(tmp_path):
    sample = tmp_path / 'partial.pdf'
    sample.write_bytes(b'%PDF synthetic')
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    ok, reason = run_pdf_operation(sample, timeout=0.3, child_target=_partial_result_parser)
    assert not ok and '超时' in reason
    assert time.monotonic() - started < 2
    started = time.monotonic()
    ok, reason = run_pdf_operation(sample, timeout=5, cancel_check=lambda: time.monotonic() - started > 0.3, child_target=_partial_result_parser)
    assert not ok and '取消' in reason
    assert time.monotonic() - started < 2
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_slow_headers_release_connection_slot_by_absolute_deadline(tmp_path):
    server = MobileUploadServer(runtime_dir=tmp_path, host='127.0.0.1', bind_host='127.0.0.1', max_connections=1, read_timeout_seconds=0.3)
    session = server.start()
    try:
        with socket.create_connection(('127.0.0.1', session.port), timeout=2) as slow:
            slow.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\nX-Synthetic: ')
            start = time.monotonic()
            for _ in range(12):
                time.sleep(0.08)
                try:
                    slow.sendall(b'x')
                except OSError:
                    break
            assert time.monotonic() - start < 0.95
        with socket.create_connection(('127.0.0.1', session.port), timeout=2) as valid:
            valid.sendall(f'GET /u/{session.token} HTTP/1.0\r\nHost: localhost\r\n\r\n'.encode())
            assert '200' in valid.recv(1024).decode()
    finally:
        server.stop()


def test_missing_backup_materials_list_affected_invoices_without_private_paths(tmp_path):
    from scripts.invoice_fetch.complete_backup import MissingMaterialsError
    runtime, path, invoice_id = _backup_source(tmp_path)
    (runtime / 'attachments' / 'original.pdf').unlink()
    (runtime / 'attachments' / 'proof.txt').unlink()
    with pytest.raises(MissingMaterialsError) as captured:
        create_complete_backup(path, runtime)
    error = captured.value
    assert len(error.issues) == 2
    assert {issue['invoice_id'] for issue in error.issues} == {invoice_id}
    assert 'BACKUP' in str(error) and '原件' in str(error) and '证明材料' in str(error)
    assert str(runtime) not in str(error)
    assert '数据库备份' in str(error)
    assert not list((runtime / 'backups').glob('*.zip'))


def test_header_deadline_does_not_cut_off_valid_server_work():
    import threading
    from http.server import BaseHTTPRequestHandler
    from scripts.invoice_fetch.mobile_upload import BoundedUploadHTTPServer
    class SlowWork(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.5)
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = BoundedUploadHTTPServer(('127.0.0.1', 0), SlowWork, read_timeout=0.2)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=2) as client:
            client.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
            assert '200' in client.recv(1024).decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


def _oversize_result_parser(output, path, mode):
    from scripts.invoice_fetch.pdf_boundary import MAX_RESULT_BYTES
    with Path(output).open('wb') as stream:
        stream.truncate(MAX_RESULT_BYTES + 1)


def test_pdf_result_size_is_checked_before_read(tmp_path):
    sample = tmp_path / 'oversized-result.pdf'
    sample.write_bytes(b'%PDF synthetic')
    ok, reason = run_pdf_operation(sample, child_target=_oversize_result_parser)
    assert not ok and '预算' in reason
    assert sample.is_file()


def test_backup_missing_list_uses_scrollable_dialog_details(window):
    from PySide6.QtWidgets import QMessageBox
    view, app = window
    captured = []
    with patch.object(QMessageBox, 'exec', new=lambda box: captured.append((box.text(), box.detailedText())) or 0):
        view._complete_backup_error('完整备份未创建，可先创建数据库备份。\n发票 ID 1：原件缺失\n发票 ID 2：证明材料缺失')
    assert len(captured) == 1
    summary, details = captured[0]
    assert '\n' not in summary
    assert '发票 ID 1' in details and '发票 ID 2' in details
