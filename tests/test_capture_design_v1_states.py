import unittest

from scripts.dev.capture_design_v1 import SUPPORTED_PAGE_STATES, _validate_page_state
from scripts.dev.run_design_v1_matrix import CASES


class CaptureDesignStateTests(unittest.TestCase):
    def test_matrix_only_contains_implemented_page_state_pairs(self):
        for page, state, _width, _height, _scale in CASES:
            with self.subTest(page=page, state=state):
                self.assertIn(state, SUPPORTED_PAGE_STATES[page])
                _validate_page_state(page, state)

    def test_valid_global_state_cannot_fall_through_on_wrong_page(self):
        for page, state in (
            ("review", "export-ready"),
            ("export", "buyer-mismatch"),
            ("imports", "default"),
            ("settings-mailbox", "error"),
        ):
            with self.subTest(page=page, state=state):
                with self.assertRaisesRegex(RuntimeError, "unsupported capture state"):
                    _validate_page_state(page, state)


if __name__ == "__main__":
    unittest.main()
