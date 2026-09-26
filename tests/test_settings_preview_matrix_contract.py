import unittest

from scripts.dev.run_settings_preview_matrix import CASES, SIZES, STATES


class SettingsPreviewMatrixContractTests(unittest.TestCase):
    def test_matrix_covers_all_states_at_both_target_scales(self):
        self.assertEqual(SIZES, ((1920, 1080, 1.0), (1366, 768, 1.5)))
        self.assertEqual(len(STATES), 8)
        self.assertEqual(len(CASES), 16)
        self.assertEqual(len(set(CASES)), len(CASES))


if __name__ == "__main__":
    unittest.main()
