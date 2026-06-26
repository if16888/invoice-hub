import unittest

from scripts.invoice_fetch.gui.workbench_state import IncrementalWindow, is_keyboard_input_target


class IncrementalWindowTests(unittest.TestCase):
    def test_next_query_blocks_concurrent_fetch_and_tracks_batch_progress(self):
        state = IncrementalWindow(batch_size=100)

        self.assertEqual(state.next_query(), (100, 0))
        self.assertTrue(state.loading)

        with self.assertRaises(RuntimeError):
            state.next_query()

        state.accept_batch(count=100, total=240, generation=state.generation)

        self.assertEqual(state.offset, 100)
        self.assertEqual(state.total, 240)
        self.assertFalse(state.loading)
        self.assertTrue(state.has_more)

    def test_reset_bumps_generation_and_clears_progress(self):
        state = IncrementalWindow(batch_size=100)
        state.next_query()
        state.accept_batch(count=50, total=50, generation=state.generation)

        generation = state.generation
        state.reset()

        self.assertEqual(state.generation, generation + 1)
        self.assertEqual(state.offset, 0)
        self.assertEqual(state.total, 0)
        self.assertFalse(state.loading)
        self.assertTrue(state.has_more)

    def test_stale_generation_results_are_ignored(self):
        state = IncrementalWindow(batch_size=100)
        state.next_query()
        current_generation = state.generation
        state.reset()

        state.accept_batch(count=100, total=200, generation=current_generation)
        self.assertEqual(state.offset, 0)
        self.assertFalse(state.loading)
        self.assertTrue(state.has_more)

        state.next_query()
        next_generation = state.generation
        state.fail_batch(generation=current_generation)
        self.assertTrue(state.loading)

        state.fail_batch(generation=next_generation)
        self.assertFalse(state.loading)


class KeyboardInputTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import sys
            from PySide6.QtWidgets import QApplication
            cls.app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError) as exc:
            raise unittest.SkipTest(str(exc))

    def test_text_editors_and_editable_combo_own_workbench_keys(self):
        from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

        combo = QComboBox()
        combo.setEditable(True)
        for widget in (QLineEdit(), QTextEdit(), QPlainTextEdit(), combo):
            self.assertTrue(is_keyboard_input_target(widget))

    def test_table_and_noneditable_combo_do_not_own_workbench_keys(self):
        from PySide6.QtWidgets import QComboBox, QTableWidget

        self.assertFalse(is_keyboard_input_target(QTableWidget()))
        self.assertFalse(is_keyboard_input_target(QComboBox()))


if __name__ == "__main__":
    unittest.main()
