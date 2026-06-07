import unittest
from unittest.mock import patch, MagicMock
import shutil
import tempfile
from pathlib import Path

from scripts.invoice_fetch.db import InvoiceDB
from scripts.invoice_fetch.__main__ import (
    _reprocess_email_records,
    _cmd_email_reprocess,
)

class TestEmailReprocess(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test_reprocess.db"
        self.db = InvoiceDB(self.db_path)
        self.db.__enter__()

        # Mock config
        self.cfg = {
            "email": {"address": "test@example.com"},
            "email_accounts": [
                {
                    "name": "Test Account",
                    "enabled": True,
                    "address": "test@example.com",
                    "mailbox_key": "test@example.com",
                    "auth_code": "dummycode",
                },
                {
                    "name": "Mailbox A",
                    "enabled": True,
                    "address": "a@example.com",
                    "mailbox_key": "a",
                    "auth_code": "dummycode",
                },
                {
                    "name": "Mailbox B",
                    "enabled": True,
                    "address": "b@example.com",
                    "mailbox_key": "b",
                    "auth_code": "dummycode",
                }
            ]
        }

    def tearDown(self):
        self.db.__exit__(None, None, None)
        shutil.rmtree(self.temp_dir)

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    @patch('scripts.invoice_fetch.__main__._handle_pending_email')
    def test_1_dry_run_no_modifications(self, mock_handle, mock_fetcher):
        # 1. 插入 email 和 invoice
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('a', 100, 'Test Invoice', 'sender', '2026-06-01', 1, 1)"
        )
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, review_status, is_deleted) "
            "VALUES ('a', 100, 'INV-100', '100.00', 'to_review', 0)"
        )
        self.db._conn.commit()

        # 2. 查询候选
        records = self.db.find_emails_for_reprocess(mailbox_key='a', uids=[100])
        self.assertEqual(len(records), 1)

        # 3. 调用 dry-run
        _reprocess_email_records(
            db=self.db,
            cfg=self.cfg,
            records=records,
            dry_run=True,
        )

        # 4. 断言仍存在且下载状态没变
        invoices = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertEqual(len(invoices), 1)

        email = self.db._conn.execute("SELECT downloaded FROM emails WHERE mailbox_key='a' AND uid=100").fetchone()
        self.assertEqual(email["downloaded"], 1)

    @patch('scripts.invoice_fetch.__main__.get_auth_code')
    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    @patch('scripts.invoice_fetch.__main__._handle_pending_email')
    def test_2_apply_deletes_and_resets(self, mock_handle, mock_fetcher, mock_get_auth):
        mock_get_auth.return_value = "dummycode"
        mock_handle.return_value = True

        # 1. 插入 email 和 invoice
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('a', 100, 'Test Invoice', 'sender', '2026-06-01', 1, 1)"
        )
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, review_status, is_deleted) "
            "VALUES ('a', 100, 'INV-100', '100.00', 'to_review', 0)"
        )
        self.db._conn.commit()

        records = self.db.find_emails_for_reprocess(mailbox_key='a', uids=[100])

        # 2. 调用 apply 重处理
        _reprocess_email_records(
            db=self.db,
            cfg=self.cfg,
            records=records,
            dry_run=False,
        )

        # 3. 断言旧 invoice 被删除 (因为重新下载 mock 了且返回 True，可能会生成新的发票记录。
        # 这里为了验证 apply 时的“物理删除旧发票记录”，我们可以直接看在重处理前后的动作。
        # 事实上，删除旧记录在下载前就已经发生，而由于 mock 了下载但并没有真的插入新记录，
        # 所以最终数据库里旧的发票应该为 0)
        invoices = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertEqual(len(invoices), 0)

        # 4. 重新下载成功了，所以 downloaded 状态重置为 0 后，被 _handle_pending_email 内部又标记为 1 了。
        # 我们可以验证 reset_email_for_reprocess 单独调用时的 downloaded 为 0。
        self.db.reset_email_for_reprocess('a', 100)
        email = self.db._conn.execute("SELECT downloaded FROM emails WHERE mailbox_key='a' AND uid=100").fetchone()
        self.assertEqual(email["downloaded"], 0)

    def test_3_default_skips_approved(self):
        # 1. 插入 approved 发票
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('a', 100, 'Test Invoice', 'sender', '2026-06-01', 1, 1)"
        )
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, review_status, is_deleted) "
            "VALUES ('a', 100, 'INV-100', '100.00', 'approved', 0)"
        )
        self.db._conn.commit()

        # 2. apply 不带 include_approved
        stats = self.db.delete_invoices_for_reprocess('a', 100, include_approved=False)
        self.assertEqual(stats["skipped_approved"], 1)
        self.assertEqual(stats["deleted"], 0)

        # 3. 发票未被删除
        invoices = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertEqual(len(invoices), 1)

    def test_4_include_approved_deletes(self):
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, review_status, is_deleted) "
            "VALUES ('a', 100, 'INV-100', '100.00', 'approved', 0)"
        )
        self.db._conn.commit()

        # apply 带 include_approved=True
        stats = self.db.delete_invoices_for_reprocess('a', 100, include_approved=True)
        self.assertEqual(stats["deleted"], 1)

        invoices = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertEqual(len(invoices), 0)

    def test_5_mailbox_key_isolation(self):
        # 1. mailbox a uid=1 有 invoice A
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, is_deleted) "
            "VALUES ('a', 1, 'INV-A', '10.00', 0)"
        )
        # 2. mailbox b uid=1 有 invoice B
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, is_deleted) "
            "VALUES ('b', 1, 'INV-B', '20.00', 0)"
        )
        self.db._conn.commit()

        # 3. 只删除 mailbox a
        stats = self.db.delete_invoices_for_reprocess('a', 1)
        self.assertEqual(stats["deleted"], 1)

        # 4. A 没了，B 还在
        inv_a = self.db.get_invoices_by_mail_identity('a', 1)
        self.assertEqual(len(inv_a), 0)
        inv_b = self.db.get_invoices_by_mail_identity('b', 1)
        self.assertEqual(len(inv_b), 1)

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    def test_6_legacy_fallback(self, mock_fetcher):
        # email mailbox_key='test@example.com' uid=10
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('test@example.com', 10, 'Test Invoice', 'sender', '2026-06-01', 1, 1)"
        )
        # invoice mailbox_key='legacy' uid=10
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, is_deleted) "
            "VALUES ('legacy', 10, 'INV-LEGACY', '50.00', 0)"
        )
        self.db._conn.commit()

        # 查找发票应该能 fallback 命中
        invs = self.db.get_invoices_by_mail_identity('test@example.com', 10)
        self.assertEqual(len(invs), 1)
        self.assertTrue(invs[0].get("is_legacy_fallback"))

        # apply 时删除 legacy
        stats = self.db.delete_invoices_for_reprocess('test@example.com', 10)
        self.assertEqual(stats["deleted"], 1)

        # 验证彻底没了
        invs_after = self.db.get_invoices_by_mail_identity('test@example.com', 10)
        self.assertEqual(len(invs_after), 0)

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    @patch('scripts.invoice_fetch.__main__._handle_pending_email')
    def test_7_reclassify_github(self, mock_handle, mock_fetcher):
        # 1. 插入 GitHub 误判发票的 email 和 invoice
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('test@example.com', 500, 'GitHub invoice-hub issue updated', 'notifications@github.com', '2026-06-01', 1, 1)"
        )
        self.db._conn.execute(
            "INSERT INTO invoices (mailbox_key, mail_uid, invoice_number, total_amount, is_deleted) "
            "VALUES ('test@example.com', 500, 'INV-500', '10.00', 0)"
        )
        self.db._conn.commit()

        records = self.db.find_emails_for_reprocess(mailbox_key='test@example.com', uids=[500])

        # 2. 执行 apply 重分类。规则分类会自动把 GitHub 邮件归为 is_invoice = 0（非发票）。
        # 因为我们上面的 cfg 里面配置了 test@example.com 账号。
        _reprocess_email_records(
            db=self.db,
            cfg=self.cfg,
            records=records,
            reclassify=True,
            dry_run=False,
        )

        # 3. 验证 classify 之后 is_invoice = 0
        email = self.db._conn.execute("SELECT is_invoice FROM emails WHERE mailbox_key='test@example.com' AND uid=500").fetchone()
        self.assertEqual(email["is_invoice"], 0)

        # 4. 验证不属于 pending download
        pending = self.db.get_invoice_emails_to_download('test@example.com')
        self.assertNotIn(500, [row["uid"] for row in pending])

    @patch('scripts.invoice_fetch.__main__.get_auth_code')
    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    @patch('scripts.invoice_fetch.__main__._handle_pending_email')
    def test_8_only_process_selected_uids(self, mock_handle, mock_fetcher, mock_get_auth):
        mock_get_auth.return_value = "dummycode"
        mock_handle.return_value = True

        # 1. 同邮箱有 uid=1、uid=2 都 pending
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('test@example.com', 1, 'Inv 1', 'sender', '2026-06-01', 1, 0)"
        )
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('test@example.com', 2, 'Inv 2', 'sender', '2026-06-01', 1, 0)"
        )
        self.db._conn.commit()

        # 2. 调用 reprocess 只指定 uid=1
        records = self.db.find_emails_for_reprocess(mailbox_key='test@example.com', uids=[1], only_downloaded=False)
        self.assertEqual(len(records), 1)

        _reprocess_email_records(
            db=self.db,
            cfg=self.cfg,
            records=records,
            dry_run=False,
        )

        # 3. 验证 mock_handle (也就是 _handle_pending_email) 只被调用了一次且其 uid 确实是 1
        # (因为只有 uid=1 才是被选中的)
        self.assertEqual(mock_handle.call_count, 1)
        args, kwargs = mock_handle.call_args
        self.assertEqual(kwargs['row']['uid'], 1)

    def test_9_apply_reject_missing_mailbox(self):
        # 1. 构造一个缺少 mailbox 的 args 命名空间，以及 mock db
        args = MagicMock()
        args.apply = True
        args.mailbox = None
        args.uid = [100]
        args.limit = 50

        # 验证会调用 sys.exit(1)
        with self.assertRaises(SystemExit) as cm:
            _cmd_email_reprocess(args, self.db)
        self.assertEqual(cm.exception.code, 1)

    def test_10_apply_reject_missing_filters(self):
        # 仅有 mailbox，无 any 筛选范围
        args = MagicMock()
        args.apply = True
        args.mailbox = "a"
        args.uid = []
        args.uid_range = None
        args.since = None
        args.until = None
        args.subject_contains = None
        args.sender_contains = None
        args.limit = 50

        with self.assertRaises(SystemExit) as cm:
            _cmd_email_reprocess(args, self.db)
        self.assertEqual(cm.exception.code, 1)

    def test_11_limit_validation(self):
        # limit <= 0 拒绝
        args = MagicMock()
        args.apply = False
        args.limit = 0
        args.uid_range = None
        args.since = None
        args.until = None

        with self.assertRaises(SystemExit) as cm:
            _cmd_email_reprocess(args, self.db)
        self.assertEqual(cm.exception.code, 1)

    def test_12_uid_range_validation_start_gt_end(self):
        # START > END 拒绝
        args = MagicMock()
        args.apply = False
        args.limit = 50
        args.uid_range = "200-100"
        args.since = None
        args.until = None

        with self.assertRaises(SystemExit) as cm:
            _cmd_email_reprocess(args, self.db)
        self.assertEqual(cm.exception.code, 1)

    def test_13_date_range_validation_since_gt_until(self):
        # since > until 拒绝，或格式错拒绝
        args = MagicMock()
        args.apply = False
        args.limit = 50
        args.uid_range = None
        args.since = "2026-06-07"
        args.until = "2026-05-07"

        with self.assertRaises(SystemExit) as cm:
            _cmd_email_reprocess(args, self.db)
        self.assertEqual(cm.exception.code, 1)

    def test_14_claimed_invoice_transation_delete(self):
        # 往 claim_groups，claim_group_items，invoices 插入关联发票
        self.db._conn.execute(
            "INSERT INTO invoices (id, mailbox_key, mail_uid, invoice_number, total_amount, is_deleted) "
            "VALUES (1000, 'a', 100, 'INV-1000', '100.00', 0)"
        )
        self.db._conn.execute(
            "INSERT INTO claim_group_items (claim_id, invoice_id) "
            "VALUES (5, 1000)"
        )
        self.db._conn.commit()

        # include_claimed=True 删除它
        stats = self.db.delete_invoices_for_reprocess('a', 100, include_claimed=True)
        self.assertEqual(stats["deleted"], 1)

        # 检查 invoices 已经物理删除
        invs = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertEqual(len(invs), 0)

        # 检查 claim_group_items 也被彻底清理
        row = self.db._conn.execute("SELECT COUNT(*) AS cnt FROM claim_group_items WHERE invoice_id = 1000").fetchone()
        self.assertEqual(row["cnt"], 0)

    def test_15_claimed_invoice_deduplication(self):
        # 模拟一个发票被多个报销组关联的情况（产生了多条 claim_group_items 关联）
        self.db._conn.execute(
            "INSERT INTO invoices (id, mailbox_key, mail_uid, invoice_number, total_amount, is_deleted) "
            "VALUES (1001, 'a', 100, 'INV-1001', '100.00', 0)"
        )
        self.db._conn.execute(
            "INSERT INTO claim_group_items (claim_id, invoice_id) "
            "VALUES (5, 1001)"
        )
        self.db._conn.execute(
            "INSERT INTO claim_group_items (claim_id, invoice_id) "
            "VALUES (6, 1001)"
        )
        self.db._conn.commit()

        # 验证 get_invoices_by_mail_identity 会返回多条行（因为 JOIN 了多次）
        invs = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertTrue(len(invs) > 1)

        # 验证 delete_invoices_for_reprocess 在 include_claimed=True 下只删除了 1 条（不会统计重复），并且干净清理
        stats = self.db.delete_invoices_for_reprocess('a', 100, include_claimed=True)
        self.assertEqual(stats["deleted"], 1)

        # 检查 invoices 物理删除
        invs_after = self.db.get_invoices_by_mail_identity('a', 100)
        self.assertEqual(len(invs_after), 0)

        # 检查 claim_group_items 中 1001 的记录为 0 条
        row = self.db._conn.execute("SELECT COUNT(*) AS cnt FROM claim_group_items WHERE invoice_id = 1001").fetchone()
        self.assertEqual(row["cnt"], 0)

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    def test_16_missing_auth_code_skips_fetcher(self, mock_fetcher):
        # 配置中没有 auth_code 的账号，但有 pending 邮件
        cfg_no_auth = {
            "email": {"address": "test@example.com"},
            "email_accounts": [
                {
                    "name": "No Auth Account",
                    "enabled": True,
                    "address": "test@example.com",
                    "mailbox_key": "test@example.com",
                    "auth_code": "",  # 空 auth_code
                }
            ]
        }

        # 插入一封 pending 邮件
        self.db._conn.execute(
            "INSERT INTO emails (mailbox_key, uid, subject, sender, mail_date, is_invoice, downloaded) "
            "VALUES ('test@example.com', 1, 'Test Title', 'sender', '2026-06-01', 1, 0)"
        )
        self.db._conn.commit()

        # 对其运行 reprocess (apply=True, reclassify=False, dry_run=False)
        records = [{"mailbox_key": "test@example.com", "uid": 1}]

        # 为了防备测试环境读取真实 keyring，我们 patch get_auth_code
        with patch('scripts.invoice_fetch.__main__.get_auth_code', side_effect=SystemExit(1)):
            _reprocess_email_records(
                db=self.db,
                cfg=cfg_no_auth,
                records=records,
                dry_run=False,
            )

        # 验证 MailFetcher 绝对没有被实例化
        self.assertFalse(mock_fetcher.called)

    def test_17_process_email_keeps_unmatched_extra_files(self):
        from scripts.invoice_fetch.__main__ import _process_email
        from scripts.invoice_fetch.attachment_handler import Attachment
        from scripts.invoice_fetch.invoice_parser import InvoiceInfo
        from scripts.invoice_fetch.mail_fetcher import MailMessage

        # 1. 准备文件和 mock
        att_dir = self.temp_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)

        attachments = []

        # 创建 5 个 invoice 附件
        for i in range(1, 6):
            f_path = att_dir / f"invoice_{i}.pdf"
            f_path.write_bytes(f"invoice_pdf_content_{i}".encode('utf-8'))
            attachments.append(Attachment(
                file_path=str(f_path),
                original_name=f"invoice_{i}.pdf",
                content_type="application/pdf",
                size=len(f_path.read_bytes()),
                is_invoice=True,
                is_extra=False
            ))

        # 创建 5 个 extra 附件
        for i in range(1, 6):
            f_path = att_dir / f"extra_{i}.pdf"
            f_path.write_bytes(f"extra_pdf_content_{i}".encode('utf-8'))
            attachments.append(Attachment(
                file_path=str(f_path),
                original_name=f"extra_{i}.pdf",
                content_type="application/pdf",
                size=len(f_path.read_bytes()),
                is_invoice=False,
                is_extra=True
            ))

        mock_att_handler = MagicMock()
        mock_att_handler._base = att_dir
        mock_att_handler.extract.return_value = attachments

        mock_parser = MagicMock()
        def mock_parse_pdf(file_path):
            name = Path(file_path).name
            if "invoice" in name:
                num = name.split("_")[1].split(".")[0]
                return InvoiceInfo(
                    parse_success=True,
                    invoice_number=f"INV-{num}",
                    invoice_code=f"CODE-{num}",
                    invoice_date="2026-06-01",
                    amount="100.00",
                    total_amount="100.00",
                    seller_name=f"Seller {num}",
                    buyer_name="Buyer",
                    invoice_type="增值税电子普通发票",
                    parse_note=""
                )
            return InvoiceInfo(parse_success=False)
        mock_parser.parse_pdf.side_effect = mock_parse_pdf

        mock_link_dl = MagicMock()
        mock_link_dl.download_from_email.return_value = []

        from email.message import Message
        raw_msg = Message()
        raw_msg["Subject"] = "Test Multilingual Multi-Invoices"
        raw_msg["From"] = "sender@example.com"
        raw_msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"

        msg = MailMessage(uid=999, raw_msg=raw_msg)

        with patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', self.temp_dir):
            recorded = _process_email(
                msg=msg,
                att_handler=mock_att_handler,
                parser=mock_parser,
                link_dl=mock_link_dl,
                db=self.db,
                categories={},
                mailbox_key="test_mailbox"
            )

        # 5 个 invoice + 5 个待关联证明材料 = 10
        self.assertEqual(recorded, 10)

        invoices = self.db._conn.execute(
            "SELECT * FROM invoices WHERE invoice_type != '待关联证明材料' AND is_deleted = 0"
        ).fetchall()
        self.assertEqual(len(invoices), 5)

        evidence = self.db._conn.execute(
            "SELECT * FROM invoices WHERE invoice_type = '待关联证明材料' AND is_deleted = 0"
        ).fetchall()
        self.assertEqual(len(evidence), 5)

        for i in range(1, 6):
            f_path = att_dir / f"extra_{i}.pdf"
            self.assertTrue(f_path.exists())

    @patch('scripts.invoice_fetch.__main__._log')
    def test_18_process_email_log_timing(self, mock_log):
        from scripts.invoice_fetch.__main__ import _process_email
        from scripts.invoice_fetch.attachment_handler import Attachment
        from scripts.invoice_fetch.invoice_parser import InvoiceInfo
        from scripts.invoice_fetch.mail_fetcher import MailMessage

        att_dir = self.temp_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)

        attachments = []

        # 写入 2 个 invoice pdf
        for i in range(1, 3):
            f_path = att_dir / f"invoice_{i}.pdf"
            f_path.write_bytes(b"invoice_content")
            attachments.append(Attachment(
                file_path=str(f_path),
                original_name=f"invoice_{i}.pdf",
                content_type="application/pdf",
                size=len(f_path.read_bytes()),
                is_invoice=True,
                is_extra=False
            ))

        f_path_extra = att_dir / "extra.pdf"
        f_path_extra.write_bytes(b"extra_content")

        attachments.append(Attachment(
            file_path=str(f_path_extra),
            original_name="extra.pdf",
            content_type="application/pdf",
            size=len(f_path_extra.read_bytes()),
            is_invoice=False,
            is_extra=True
        ))

        mock_att_handler = MagicMock()
        mock_att_handler._base = att_dir
        mock_att_handler.extract.return_value = attachments

        mock_parser = MagicMock()
        def mock_parse_pdf(file_path):
            name = Path(file_path).name
            if "invoice" in name:
                num = name.split("_")[1].split(".")[0]
                return InvoiceInfo(
                    parse_success=True,
                    invoice_number=f"INV-{num}",
                    invoice_code=f"CODE-{num}",
                    invoice_date="2026-06-01",
                    amount="100.00",
                    total_amount="100.00",
                    seller_name=f"Seller {num}",
                    buyer_name="Buyer",
                    invoice_type="增值税电子普通发票",
                    parse_note=""
                )
            return InvoiceInfo(parse_success=False)
        mock_parser.parse_pdf.side_effect = mock_parse_pdf

        mock_link_dl = MagicMock()
        mock_link_dl.download_from_email.return_value = []

        from email.message import Message
        raw_msg = Message()
        raw_msg["Subject"] = "Test Log"
        raw_msg["From"] = "sender@example.com"
        raw_msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"

        msg = MailMessage(uid=1001, raw_msg=raw_msg)

        info_calls = []
        def log_info_side_effect(msg, *args):
            formatted = msg % args
            info_calls.append(formatted)
        mock_log.info.side_effect = log_info_side_effect

        with patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', self.temp_dir):
            _process_email(
                msg=msg,
                att_handler=mock_att_handler,
                parser=mock_parser,
                link_dl=mock_link_dl,
                db=self.db,
                categories={},
                mailbox_key="test_mailbox"
            )

        prep_idx = -1
        keep_idx = -1
        for idx, call_str in enumerate(info_calls):
            if "准备保留为待关联" in call_str:
                prep_idx = idx
            elif "已保留待关联证明材料" in call_str:
                keep_idx = idx

        self.assertNotEqual(prep_idx, -1)
        self.assertNotEqual(keep_idx, -1)
        self.assertTrue(prep_idx < keep_idx)

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    def test_19_evidence_repair_dry_run(self, mock_fetcher_cls):
        from scripts.invoice_fetch.__main__ import _cmd_evidence_repair
        from scripts.invoice_fetch.mail_fetcher import MailMessage
        from email.message import Message

        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value.__enter__.return_value = mock_fetcher

        raw_msg = Message()
        raw_msg["Subject"] = "Test Repair"
        raw_msg["From"] = "sender@example.com"
        raw_msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"

        att_dir = self.temp_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        f_path = att_dir / "extra.pdf"
        f_path.write_bytes(b"extra_content")

        from scripts.invoice_fetch.attachment_handler import Attachment
        att = Attachment(
            file_path=str(f_path),
            original_name="extra.pdf",
            content_type="application/pdf",
            size=len(f_path.read_bytes()),
            is_invoice=False,
            is_extra=True
        )

        mock_fetcher.fetch_by_uid.return_value = MailMessage(uid=123, raw_msg=raw_msg)

        with patch('scripts.invoice_fetch.__main__.AttachmentHandler') as mock_handler_cls, \
             patch('scripts.invoice_fetch.__main__.load_config', return_value=self.cfg), \
             patch('scripts.invoice_fetch.__main__.get_auth_code', return_value="dummycode"):
            mock_handler = MagicMock()
            mock_handler_cls.return_value = mock_handler
            mock_handler.extract.return_value = [att]

            args = MagicMock()
            args.mailbox = "a"
            args.uid = 123
            args.dry_run = True
            args.apply = False
            args.config = None

            with self.assertRaises(SystemExit) as cm, \
                 patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', self.temp_dir):
                _cmd_evidence_repair(args, self.db)

            self.assertEqual(cm.exception.code, 0)

        evidence = self.db._conn.execute(
            "SELECT * FROM invoices WHERE invoice_type = '待关联证明材料'"
        ).fetchall()
        self.assertEqual(len(evidence), 0)

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    def test_20_evidence_repair_apply(self, mock_fetcher_cls):
        from scripts.invoice_fetch.__main__ import _cmd_evidence_repair
        from scripts.invoice_fetch.mail_fetcher import MailMessage
        from email.message import Message

        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value.__enter__.return_value = mock_fetcher

        raw_msg = Message()
        raw_msg["Subject"] = "Test Repair Apply"
        raw_msg["From"] = "sender@example.com"
        raw_msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"

        att_dir = self.temp_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        f_path = att_dir / "extra.pdf"
        f_path.write_bytes(b"extra_content")

        from scripts.invoice_fetch.attachment_handler import Attachment
        att = Attachment(
            file_path=str(f_path),
            original_name="extra.pdf",
            content_type="application/pdf",
            size=len(f_path.read_bytes()),
            is_invoice=False,
            is_extra=True
        )

        mock_fetcher.fetch_by_uid.return_value = MailMessage(uid=123, raw_msg=raw_msg)

        with patch('scripts.invoice_fetch.__main__.AttachmentHandler') as mock_handler_cls, \
             patch('scripts.invoice_fetch.__main__.load_config', return_value=self.cfg), \
             patch('scripts.invoice_fetch.__main__.get_auth_code', return_value="dummycode"):
            mock_handler = MagicMock()
            mock_handler_cls.return_value = mock_handler
            mock_handler.extract.return_value = [att]

            args = MagicMock()
            args.mailbox = "a"
            args.uid = 123
            args.dry_run = False
            args.apply = True
            args.config = None

            with self.assertRaises(SystemExit) as cm, \
                 patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', self.temp_dir):
                _cmd_evidence_repair(args, self.db)

            self.assertEqual(cm.exception.code, 0)

        evidence = self.db._conn.execute(
            "SELECT * FROM invoices WHERE invoice_type = '待关联证明材料' AND is_deleted = 0"
        ).fetchall()
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["mail_uid"], 123)
        self.assertEqual(evidence[0]["mailbox_key"], "a")

    @patch('scripts.invoice_fetch.__main__.MailFetcher')
    def test_21_evidence_repair_deduplication(self, mock_fetcher_cls):
        from scripts.invoice_fetch.__main__ import _cmd_evidence_repair
        from scripts.invoice_fetch.mail_fetcher import MailMessage
        from email.message import Message

        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value.__enter__.return_value = mock_fetcher

        raw_msg = Message()
        raw_msg["Subject"] = "Test Repair Dedup"
        raw_msg["From"] = "sender@example.com"
        raw_msg["Date"] = "Mon, 01 Jun 2026 12:00:00 +0800"

        att_dir = self.temp_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)
        f_path = att_dir / "extra.pdf"
        f_path.write_bytes(b"extra_content")

        from scripts.invoice_fetch.attachment_handler import Attachment
        att = Attachment(
            file_path=str(f_path),
            original_name="extra.pdf",
            content_type="application/pdf",
            size=len(f_path.read_bytes()),
            is_invoice=False,
            is_extra=True
        )

        mock_fetcher.fetch_by_uid.return_value = MailMessage(uid=123, raw_msg=raw_msg)

        with patch('scripts.invoice_fetch.__main__.AttachmentHandler') as mock_handler_cls, \
             patch('scripts.invoice_fetch.__main__.load_config', return_value=self.cfg), \
             patch('scripts.invoice_fetch.__main__.get_auth_code', return_value="dummycode"):
            mock_handler = MagicMock()
            mock_handler_cls.return_value = mock_handler
            mock_handler.extract.return_value = [att]

            args = MagicMock()
            args.mailbox = "a"
            args.uid = 123
            args.dry_run = False
            args.apply = True
            args.config = None

            with self.assertRaises(SystemExit) as cm, \
                 patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', self.temp_dir):
                _cmd_evidence_repair(args, self.db)

            self.assertEqual(cm.exception.code, 0)

            with self.assertRaises(SystemExit) as cm, \
                 patch('scripts.invoice_fetch.__main__.RUNTIME_DIR', self.temp_dir):
                _cmd_evidence_repair(args, self.db)

            self.assertEqual(cm.exception.code, 0)

        evidence = self.db._conn.execute(
            "SELECT * FROM invoices WHERE invoice_type = '待关联证明材料' AND is_deleted = 0"
        ).fetchall()
        self.assertEqual(len(evidence), 1)

    def test_22_gui_queries_correct_unassociated_count(self):
        self.db._conn.execute(
            "INSERT INTO invoices (id, mailbox_key, mail_uid, invoice_number, total_amount, review_status, is_deleted, extra_paths) "
            "VALUES (5000, 'a', 100, 'INV-5000', '100.00', 'to_review', 0, '[]')"
        )
        self.db._conn.execute(
            "INSERT INTO invoices (id, mailbox_key, mail_uid, invoice_type, is_deleted, attachment_path) "
            "VALUES (5001, 'a', 100, '待关联证明材料', 0, 'attachments/extra_1.pdf')"
        )
        self.db._conn.execute(
            "INSERT INTO invoices (id, mailbox_key, mail_uid, invoice_type, is_deleted, attachment_path) "
            "VALUES (5002, 'a', 100, '待关联证明材料', 0, 'attachments/extra_2.pdf')"
        )
        self.db._conn.commit()

        mailbox_key = 'a'
        mail_uid = 100

        sql = "SELECT id, attachment_path FROM invoices WHERE mailbox_key = ? AND mail_uid = ? AND invoice_type = '待关联证明材料' AND is_deleted = 0"
        rows = self.db._conn.execute(sql, (mailbox_key, mail_uid)).fetchall()

        self.assertEqual(len(rows), 2)
        paths = [r["attachment_path"] for r in rows]
        self.assertIn("attachments/extra_1.pdf", paths)
        self.assertIn("attachments/extra_2.pdf", paths)

if __name__ == '__main__':
    unittest.main()
