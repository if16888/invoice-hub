import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_claim_reason_gui import _window


class ClaimFilenameGuiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        generator = _window(Path(temporary.name))
        self.window, _, _ = next(generator)
        self.addCleanup(generator.close)

    def test_template_saved_without_overwriting_other_configuration(self):
        cfg = {'reimbursement': {'buyer_name': 'Buyer'}, 'mail': {'account': 'synthetic'}}
        self.window._desktop_settings_cfg = {'reimbursement': {'buyer_name': 'Unsaved'}, 'draft': True}
        with patch('scripts.invoice_fetch.gui.app.QInputDialog.getText', return_value=('{部门}_{姓名}.xlsx', True)), \
             patch('scripts.invoice_fetch.gui.app.load_config_safe', return_value=cfg), \
             patch('scripts.invoice_fetch.gui.app.save_config') as save:
            self.window._configure_export_filename()
            save.assert_called_once()
        self.assertEqual(cfg['reimbursement']['filename_template'], '{部门}_{姓名}.xlsx')
        self.assertEqual(cfg['reimbursement']['buyer_name'], 'Buyer')
        self.assertEqual(cfg['mail']['account'], 'synthetic')
        self.assertEqual(self.window._desktop_settings_cfg['reimbursement']['filename_template'], '{部门}_{姓名}.xlsx')
        self.assertEqual(self.window._desktop_settings_cfg['reimbursement']['buyer_name'], 'Unsaved')

    def test_invalid_or_cancelled_template_does_not_save(self):
        for value, accepted in [('{bad}.xlsx', True), ('ignored', False)]:
            with patch('scripts.invoice_fetch.gui.app.QInputDialog.getText', return_value=(value, accepted)), \
                 patch('scripts.invoice_fetch.gui.app.QMessageBox.warning'), \
                 patch('scripts.invoice_fetch.gui.app.save_config') as save:
                self.window._configure_export_filename()
                self.assertFalse(save.called)
