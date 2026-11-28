"""User interaction regressions found in the desktop workflow audit."""
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog
from scripts.invoice_fetch import ai_classifier, credentials
from scripts.dev.capture_design_v1 import _synthetic_config
from . import test_desktop_visual_integration as visual


class DesktopWorkflowRefinementsTests(unittest.TestCase):
    setUpClass = classmethod(visual.DesktopVisualIntegrationTests.setUpClass.__func__)
    settle = visual.DesktopVisualIntegrationTests.settle
    window = visual.DesktopVisualIntegrationTests.window

    def _click_visible(self, widget):
        self.assertTrue(widget.isVisible() and widget.isEnabled())
        QTest.mouseClick(widget, Qt.LeftButton)
        self.settle()

    def _enter_export(self, window):
        self._click_visible(window.workbench_nav_buttons['export'])
        self.assertIs(window.center_stack.currentWidget(), window.export_page)

    def _select_export_group(self, window, claim_id):
        groups = window.export_group_list
        item = next(groups.item(i) for i in range(groups.count()) if groups.item(i).data(Qt.UserRole) == claim_id)
        groups.scrollToItem(item)
        self.settle()
        rect = groups.visualItemRect(item).intersected(groups.viewport().rect())
        self.assertFalse(rect.isEmpty())
        QTest.mouseClick(groups.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        self.settle()
        self.assertEqual(groups.currentItem().data(Qt.UserRole), claim_id)

    def _select_invoice(self, window, invoice_id, modifiers=Qt.NoModifier):
        row = next(i for i, inv in enumerate(window.invoices_list) if inv['id'] == invoice_id)
        index = window.table.model().index(row, 0)
        window.table.scrollTo(index)
        self.settle()
        rect = window.table.visualRect(index).intersected(window.table.viewport().rect())
        self.assertFalse(rect.isEmpty())
        QTest.mouseClick(window.table.viewport(), Qt.LeftButton, modifiers, rect.center())
        self.settle()

    def _members_by_group(self, window):
        return {group['id']: {inv['id'] for inv in window.db.get_claim_invoices(group['id'])}
                for group in window.db.list_claim_groups()}

    def _seed_assignment_records(self, window, count=3):
        ids = [window.db.insert_invoice({
            'invoice_number': f'SYNTH-ASSIGN-{i}', 'invoice_date': '2026-11-06', 'expense_date': '2026-11-06',
            'seller_name': 'Synthetic supplier', 'buyer_name': 'Synthetic buyer', 'total_amount': '12.00',
            'review_status': 'to_review', 'attachment_path': str(window.db_path.parent / 'original.xml'),
        }) for i in range(count)]
        self.assertTrue(all(invoice_id is not None for invoice_id in ids))
        return ids

    def _create_export_group(self, window, name, accepted=True):
        # The actual visible button enters the production creation path. Only
        # the modal text result is controlled (no native modal left in CI).
        with patch.object(QInputDialog, 'getText', return_value=(name, accepted)) as dialog:
            self._click_visible(window.btn_export_create_group)
        dialog.assert_called_once()

    def _assert_review_target(self, window, claim_id):
        self.assertIs(window.center_stack.currentWidget(), window.review_page)
        self.assertTrue(window.review_claim_target.isVisible())
        self.assertEqual(window.review_claim_target.currentData(), claim_id)
        self.assertEqual(window.combo_claims.currentData(), claim_id)
        self.assertEqual(window._quick_claim_target_id, claim_id)

    def _assign_current_with_key(self, window, invoice_id):
        window.activateWindow()
        QTest.qWait(30)
        self._select_invoice(window, invoice_id)
        window.table.setFocus(Qt.OtherFocusReason)
        self.settle()
        self.assertIs(self.app.focusWidget(), window.table)
        QTest.keyClick(window.table, Qt.Key_G, Qt.ControlModifier)
        self.settle()

    def test_export_creation_targets_new_id_for_single_and_batch_manual_assignment(self):
        with self.window() as w:
            old_a = w.db.list_claim_groups()[0]['id']
            old_b = w.db.create_claim_group('Existing B')
            unassigned = self._seed_assignment_records(w)
            before = self._members_by_group(w)
            w._load_claims()
            self._enter_export(w)
            self._select_export_group(w, old_a)

            self._create_export_group(w, 'New Period C')
            after_create = self._members_by_group(w)
            new_ids = set(after_create) - set(before)
            self.assertEqual(len(new_ids), 1)
            new_id = new_ids.pop()
            self.assertEqual(after_create, {**before, new_id: set()})
            self._assert_review_target(w, new_id)
            self.assertTrue(w.export_dirty)
            self.assertEqual(w.current_filter_status, None)
            self.assertEqual(w.txt_search.text(), '')
            self.assertEqual(w._detail_panel.detail_tabs.currentIndex(), 1)

            self._assign_current_with_key(w, unassigned[0])
            self.assertEqual(w.db.get_invoice_claim_id(unassigned[0]), new_id)
            self._assert_review_target(w, new_id)
            self._select_invoice(w, unassigned[1])
            self._select_invoice(w, unassigned[2], Qt.ControlModifier)
            self.assertEqual({w.invoices_list[i.row()]['id'] for i in w.table.selectionModel().selectedRows()}, set(unassigned[1:]))
            self._click_visible(w.batch_review_bar.link)
            self.assertEqual(self._members_by_group(w), {**before, new_id: set(unassigned)})
            self.assertEqual(before[old_b], set())

            # Preserve the existing export selection policy on return; an
            # explicit click on C must show exactly the manually added rows.
            self._enter_export(w)
            self.assertEqual(w.export_group_list.currentItem().data(Qt.UserRole), old_a)
            self._select_export_group(w, new_id)
            self.assertEqual({w.export_invoice_list.item(i).data(Qt.UserRole) for i in range(w.export_invoice_list.count())}, set(unassigned))
            self.assertEqual({w.db.get_invoice(invoice_id)['review_status'] for invoice_id in unassigned}, {'to_review'})

    def test_export_creation_same_name_from_locked_group_and_cancel_are_id_safe(self):
        with self.window() as w:
            old = w.db.list_claim_groups()[0]
            w.db.create_claim_group('Existing B')
            w.db._conn.execute("UPDATE claim_groups SET status='exported' WHERE id=?", (old['id'],))
            w.db._conn.commit()
            invoice_id = self._seed_assignment_records(w, 1)[0]
            before = self._members_by_group(w)
            w._load_claims()
            self._enter_export(w)
            self._select_export_group(w, old['id'])
            for name, accepted in (('Cancelled', False), ('   ', True)):
                self._create_export_group(w, name, accepted)
                self.assertIs(w.center_stack.currentWidget(), w.export_page)
                self.assertEqual(w.export_group_list.currentItem().data(Qt.UserRole), old['id'])
                self.assertEqual(self._members_by_group(w), before)

            self._create_export_group(w, old['name'])
            new_id, = set(self._members_by_group(w)) - set(before)
            self.assertEqual(self._members_by_group(w), {**before, new_id: set()})
            self.assertEqual(next(group['name'] for group in w.db.list_claim_groups() if group['id'] == new_id), old['name'])
            self._assert_review_target(w, new_id)
            self._assign_current_with_key(w, invoice_id)
            self.assertEqual(self._members_by_group(w), {**before, new_id: {invoice_id}})
            self.assertEqual(next(group['status'] for group in w.db.list_claim_groups() if group['id'] == old['id']), 'exported')

    def test_export_choose_existing_and_missing_target_never_fall_back(self):
        with self.window() as w:
            selected = w.db.create_claim_group('Existing B')
            invoice_id = self._seed_assignment_records(w, 1)[0]
            before = self._members_by_group(w)
            w._load_claims()
            self._enter_export(w)
            self._select_export_group(w, selected)
            self._click_visible(w.btn_export_choose_invoices)
            self._assert_review_target(w, selected)
            self.assertEqual(self._members_by_group(w), before)

            self._enter_export(w)
            self._select_export_group(w, selected)
            # Simulate another window deleting an empty group after the
            # export list was populated, without changing the visible row.
            self.assertTrue(w.db.delete_claim_group_if_empty(selected))
            self._click_visible(w.btn_export_choose_invoices)
            self._assert_review_target(w, None)
            self._assign_current_with_key(w, invoice_id)
            self.assertIsNone(w.db.get_invoice_claim_id(invoice_id))
            QTest.keyClick(w.review_claim_target.view(), Qt.Key_Escape)
            w.review_claim_target.hidePopup()
            self.settle()
            QTest.qWait(20)
            self.assertFalse(w.review_claim_target.view().isVisible())
            self.assertIsNone(self.app.activePopupWidget())
            self.assertEqual(self._members_by_group(w), {group: members for group, members in before.items() if group != selected})

    def test_export_creation_keeps_new_group_visible_when_navigation_is_blocked(self):
        with self.window() as w:
            old = w.db.list_claim_groups()[0]['id']
            w.db.create_claim_group('Existing B')
            before = self._members_by_group(w)
            w._load_claims()
            self._enter_export(w)
            self._select_export_group(w, old)

            def refuse_save():
                w.statusBar().showMessage('备注未能保存，请重试。')
                return False

            with patch.object(w, '_persist_invoice_note', side_effect=refuse_save), \
                    patch.object(w, '_reset_invoice_filters', wraps=w._reset_invoice_filters) as reset:
                self._create_export_group(w, 'Created but blocked')
            reset.assert_not_called()
            new_id, = set(self._members_by_group(w)) - set(before)
            self.assertIs(w.center_stack.currentWidget(), w.export_page)
            self.assertEqual(self._members_by_group(w), {**before, new_id: set()})
            self.assertEqual(w.export_group_list.currentItem().data(Qt.UserRole), old)
            self.assertIn(new_id, {w.export_group_list.item(i).data(Qt.UserRole) for i in range(w.export_group_list.count())})
            self.assertIn('已创建', w.statusBar().currentMessage())
            self.assertIn('备注未能保存', w.statusBar().currentMessage())
            self._select_export_group(w, new_id)
            self._click_visible(w.btn_export_choose_invoices)
            self._assert_review_target(w, new_id)

    def test_first_export_group_and_committed_creation_list_failure(self):
        with self.window() as w:
            for group, members in self._members_by_group(w).items():
                for invoice_id in members:
                    self.assertTrue(w.db.remove_invoice_from_claim(group, invoice_id))
                self.assertTrue(w.db.delete_claim_group_if_empty(group))
            unassigned = self._seed_assignment_records(w, 2)
            w._load_claims()
            self._enter_export(w)
            self.assertFalse(w.btn_export_choose_invoices.isVisible())
            self._create_export_group(w, 'First group')
            first_id, = self._members_by_group(w)
            self._assert_review_target(w, first_id)
            self.assertEqual(self._members_by_group(w), {first_id: set()})
            self._assign_current_with_key(w, unassigned[0])
            self.assertEqual(w.db.get_invoice_claim_id(unassigned[0]), first_id)

            self._enter_export(w)
            self._select_export_group(w, first_id)
            # The INSERT commits, but the subsequent target list cannot be
            # read. Never silently assign to the previously selected group.
            with patch.object(w.db, 'list_claim_groups', side_effect=RuntimeError('synthetic read failure')):
                self._create_export_group(w, 'Committed but unreadable target')
            new_id, = set(self._members_by_group(w)) - {first_id}
            self._assert_review_target(w, None)
            self.assertIn('已创建', w.statusBar().currentMessage())
            self.assertIn('重新选择', w.statusBar().currentMessage())
            # Selecting a different invoice must not restore a default
            # target. The deleted-target case separately exercises Ctrl+G
            # opening and dismissing the native choice popup.
            w.activateWindow()
            QTest.qWait(30)
            self._select_invoice(w, unassigned[1])
            self.assertEqual(w.current_invoice['id'], unassigned[1])
            self._assert_review_target(w, None)
            self.assertIsNone(w.db.get_invoice_claim_id(unassigned[1]))
            self.assertEqual(self._members_by_group(w), {first_id: {unassigned[0]}, new_id: set()})

    def test_ai_menu_actions_render_current_status_without_page_refresh(self):
        cfg = _synthetic_config()
        cfg['ai_profiles'] = [dict(profile_id='one', name='First', provider='deepseek', model='deepseek-chat', enabled=True),
                              dict(profile_id='two', name='Second', provider='openai', model='gpt-4.1-mini', enabled=False)]
        source = ['profile']
        ai_classifier.clear_all_session_paused()
        try:
            with patch('scripts.invoice_fetch.gui.app.load_config_safe', return_value=cfg), \
                 patch.object(credentials, 'get_ai_api_key_source', side_effect=lambda *args: source[0]), \
                 patch.object(credentials, 'delete_ai_api_key', side_effect=lambda *args, **kw: source.__setitem__(0, 'missing')), self.window() as w:
                w._switch_main_page('settings'); w.settings_tabs.setCurrentIndex(1); self.settle()
                for name, expected in [('暂停当前会话','已暂停'), ('恢复会话','已启用'), ('清除 Key','待补 Key')]:
                    next(action for action in w.settings_ai_more_menu.actions() if action.text() == name).trigger()
                    self.assertEqual(w.lbl_settings_ai_status_badge.text(), expected)
                    self.assertEqual(w.lbl_settings_ai_enabled.text(), expected)
                    row=w.settings_ai_profile_list.itemWidget(w.settings_ai_profile_list.item(0))
                    from PySide6.QtWidgets import QLabel
                    badges=[label.text() for label in row.findChildren(QLabel) if label.property('class')=='StatusBadge']
                    self.assertIn(expected, badges)
                    self.assertNotIn('401', w.lbl_settings_ai_failure_status.text())
                self.assertTrue(cfg['ai_profiles'][0]['enabled'])
        finally:
            ai_classifier.clear_all_session_paused()

    def test_small_initial_window_fits_filters_with_large_counts(self):
        with self.window((1040,700), deferred=False) as w:
            w._switch_main_page('review'); self.settle()
            for key in w.filter_buttons:
                w.status_segment_control.set_value(key, 99999)
            self.settle()
            previous=None
            for card in w.filter_buttons.values():
                bounds=QRect(card.mapTo(w.filter_bar_widget,QPoint()),card.size())
                self.assertTrue(w.filter_bar_widget.rect().contains(bounds))
                if previous is not None:
                    self.assertLessEqual(previous.right(), bounds.left())
                previous=bounds
                for label in (card._lbl_title,card._lbl_value):
                    self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
            w.table.selectRow(1); self.settle()
            self.assertEqual(w.current_invoice['id'], w.invoices_list[1]['id'])
            self.assertLess(w.left_upper_widget.height(), 276)
            self.assertGreater(w.preview_panel.height(), 200)

    def test_export_enter_opens_invoice_once_without_approving(self):
        with self.window() as w:
            w._switch_main_page('export'); self.settle()
            row=next(i for i in range(w.export_invoice_list.count())
                     if w.db.get_invoice(w.export_invoice_list.item(i).data(Qt.UserRole))['review_status']=='to_review')
            invoice_id=w.export_invoice_list.item(row).data(Qt.UserRole)
            w.export_invoice_list.setCurrentRow(row); w.export_invoice_list.setFocus(Qt.TabFocusReason); self.settle()
            QTest.keyClick(w.export_invoice_list, Qt.Key_Return); self.settle()
            self.assertIs(w.center_stack.currentWidget(),w.review_page)
            self.assertEqual(w.current_invoice['id'],invoice_id)
            self.assertEqual(w.db.get_invoice(invoice_id)['review_status'],'to_review')

    def test_review_amount_rows_show_currency_without_changing_numeric_filter(self):
        with self.window() as w:
            w._switch_main_page('review'); w._change_filter('all'); self.settle()
            invoice_id=w.invoices_list[0]['id']
            w.db._conn.execute("UPDATE invoices SET currency='USD',total_amount='100.00' WHERE id=?",(invoice_id,))
            w.db._conn.commit(); w._load_invoices(preserve_invoice_id=invoice_id); self.settle()
            row=w._row_for_invoice_id(invoice_id)
            self.assertEqual(w.table.item(row,3).text(),'USD 100.00')
            self.assertEqual(w.db.get_invoice(invoice_id)['total_amount'],'100.00')

    def test_quick_assignment_undo_preserves_a_newer_relation_and_locked_groups(self):
        with self.window() as w:
            w._switch_main_page('review'); w._change_filter('all'); self.settle()
            claim=w.combo_claims.currentData()
            invoice_id=w.db.insert_invoice(dict(invoice_number='NEW-ASSIGN',total_amount='15.00',review_status='to_review'))
            w._load_invoices(preserve_invoice_id=invoice_id); self.settle()
            self.assertTrue(w.review_claim_target.isVisible())
            w._add_current_invoice_to_claim(); self.settle()
            self.assertEqual(w.db.get_invoice_claim_id(invoice_id),claim)
            w.btn_undo_claim_assignment.click(); self.settle()
            self.assertIsNone(w.db.get_invoice_claim_id(invoice_id))
            w._add_current_invoice_to_claim(); self.settle()
            self.assertTrue(w.db.remove_invoice_from_claim(claim,invoice_id))
            self.assertTrue(w.db.add_invoice_to_claim(claim,invoice_id))
            w._undo_claim_assignment(); self.settle()
            self.assertEqual(w.db.get_invoice_claim_id(invoice_id),claim)
            self.assertTrue(w.db.remove_invoice_from_claim(claim,invoice_id))
            w._add_current_invoice_to_claim(); self.settle()
            w.db._conn.execute("UPDATE claim_groups SET status='exported' WHERE id=?",(claim,));w.db._conn.commit()
            w._undo_claim_assignment(); self.settle()
            self.assertEqual(w.db.get_invoice_claim_id(invoice_id),claim)

    def test_multiple_targets_require_a_choice_without_changing_invoice_ownership(self):
        with self.window() as w:
            w._switch_main_page('review'); w._change_filter('all'); self.settle()
            invoice_id=w.current_invoice['id']
            owner=w.db.get_invoice_claim_id(invoice_id)
            w.db.create_claim_group('Another target')
            w.combo_claims.setCurrentIndex(-1)
            w._load_claims(); self.settle()
            self.assertEqual(w.combo_claims.currentIndex(),-1)
            self.assertTrue(w._detail_panel.lbl_claim_assignment.text())
            w._add_current_invoice_to_claim(); self.settle()
            self.assertTrue(w.review_claim_target.view().isVisible())
            self.assertEqual(w.db.get_invoice_claim_id(invoice_id),owner)
            w.review_claim_target.hidePopup()

    def test_reopening_database_invalidates_assignment_undo(self):
        with self.window() as w:
            w._switch_main_page('review'); w._change_filter('all'); self.settle()
            invoice_id=w.db.insert_invoice(dict(invoice_number='UNDO-REOPEN',total_amount='12.00'))
            w._load_invoices(preserve_invoice_id=invoice_id); self.settle()
            w._add_current_invoice_to_claim(); self.settle()
            owner=w.db.get_invoice_claim_id(invoice_id)
            self.assertIsNotNone(w._claim_assignment_undo)
            w.db.close(); w._open_database()
            self.assertIsNone(w._claim_assignment_undo)
            self.assertFalse(w.claim_assignment_feedback.isVisible())
            w._undo_claim_assignment()
            self.assertEqual(w.db.get_invoice_claim_id(invoice_id),owner)

    def test_focus_ticket_returns_to_the_same_invoice_and_scroll_position(self):
        with self.window((1040,700)) as w:
            w._switch_main_page('review'); w._change_filter('all'); self.settle()
            w.table.selectRow(1); self.settle()
            invoice_id=w.current_invoice['id']
            scroll=w.table.verticalScrollBar().value()
            QTest.keyClick(w, Qt.Key_F11); self.settle()
            self.assertIsNotNone(w.preview_focus_dialog)
            QTest.keyClick(w.preview_focus_dialog,Qt.Key_Escape); self.settle()
            self.assertIsNone(w.preview_focus_dialog)
            self.assertEqual(w.current_invoice['id'],invoice_id)
            self.assertEqual(w.table.verticalScrollBar().value(),scroll)

    def test_ctrl_g_works_after_choosing_a_target_without_moving_focus(self):
        with self.window() as w:
            w._switch_main_page('review'); w._change_filter('all'); self.settle()
            second=w.db.create_claim_group('Second target')
            invoice_id=w.db.insert_invoice(dict(invoice_number='TARGET-CHOICE',total_amount='18.00'))
            w._load_claims(); w._load_invoices(preserve_invoice_id=invoice_id); self.settle()
            index=w.review_claim_target.findData(second)
            w.review_claim_target.setCurrentIndex(index)
            w.review_claim_target.activated.emit(index)
            w.review_claim_target.setFocus(); self.settle()
            QTest.keyClick(w.review_claim_target,Qt.Key_G,Qt.ControlModifier); self.settle()
            self.assertEqual(w.db.get_invoice_claim_id(invoice_id),second)

    def test_export_issue_action_keeps_group_context_and_rechecks_on_return(self):
        with self.window() as w:
            w._switch_main_page('export'); self.settle()
            claim=w.export_group_list.currentItem().data(Qt.UserRole)
            invoice_id=next(inv['id'] for inv in w.db.get_claim_invoices(claim) if inv['review_status']=='approved')
            w.db._conn.execute("UPDATE invoices SET total_amount='' WHERE id=?",(invoice_id,));w.db._conn.commit()
            w._sync_export_claim_selection(); self.settle()
            self.assertEqual(w._export_issue_ids['missing_amount'],[invoice_id])
            w.export_fix_buttons['missing_amount'].click(); self.settle()
            self.assertEqual([inv['id'] for inv in w.invoices_list],[invoice_id])
            self.assertEqual(w._review_scope_origin,'export')
            w.db._conn.execute("UPDATE invoices SET total_amount='50.00' WHERE id=?",(invoice_id,));w.db._conn.commit()
            w.btn_return_claim.click(); self.settle()
            self.assertIs(w.center_stack.currentWidget(),w.export_page)
            self.assertEqual(w.export_group_list.currentItem().data(Qt.UserRole),claim)
            self.assertFalse(w.export_fix_buttons['missing_amount'].isVisible())
            self.assertEqual(w._export_issue_ids['missing_amount'],[])

    def test_export_unchanged_rows_reuse_items_and_preserve_keyboard_selection(self):
        with self.window() as w:
            w._switch_main_page('export'); self.settle()
            item=w.export_invoice_list.item(1)
            w.export_invoice_list.setCurrentRow(1)
            w._performance_probe.enabled=True
            w._performance_probe.records.clear()
            w._performance_probe.set_sink(lambda line: None)
            w._sync_export_claim_selection(); self.settle()
            self.assertIs(w.export_invoice_list.item(1),item)
            self.assertIs(w.export_invoice_list.currentItem(),item)
            self.assertEqual(w._performance_probe.summary('export_selection')['count'],1)

    def test_export_confirmation_matches_page_scope_and_can_cancel(self):
        from scripts.invoice_fetch.gui import app as app_module
        with self.window() as w:
            w._switch_main_page('export'); self.settle()
            w.export_scope.setCurrentIndex(1); self.settle()
            boxes=[]
            def cancel(box):
                boxes.append((box.text(), box.informativeText(), [button.text() for button in box.buttons()]))
                return 0
            with patch.object(app_module.QMessageBox,'exec',cancel), patch.object(app_module.ClaimExportWorker,'start') as start:
                w._export_claim_package()
                start.assert_not_called()
            text, info, buttons=boxes[0]
            self.assertIn('共 2 张',text)
            self.assertIn('已通过和待审核',text)
            self.assertNotIn('approved',text)
            self.assertIn('锁定',info)
            self.assertEqual(set(buttons),{'确认导出','取消'})
