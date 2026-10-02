from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_repo_privacy.py"

spec = importlib.util.spec_from_file_location("repo_privacy_gate", SCRIPT_PATH)
privacy = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(privacy)


class RepoPrivacyPolicyTests(unittest.TestCase):
    def test_reviewed_synthetic_design_artifacts_are_exactly_scoped(self):
        self.assertTrue(privacy.should_skip_keyword_check("DESIGN.md"))
        self.assertTrue(
            privacy.should_skip_keyword_check("design-prototypes/index.html")
        )

        # No directory wildcard: a newly added prototype must still be scanned.
        self.assertFalse(
            privacy.should_skip_keyword_check("design-prototypes/real-export.html")
        )
        self.assertFalse(privacy.should_skip_keyword_check("DESIGN_COPY.md"))

    def test_sensitive_keyword_outside_allowlist_is_still_rejected(self):
        previous_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                candidate = root / "design-prototypes" / "real-export.html"
                candidate.parent.mkdir(parents=True)
                candidate.write_text(
                    "<p>纳税人识别号: REAL-COMPANY-VALUE</p>",
                    encoding="utf-8",
                )
                import os
                os.chdir(root)
                self.assertFalse(
                    privacy.check_file_leak("design-prototypes/real-export.html")
                )
        finally:
            import os
            os.chdir(previous_cwd)

    def test_reviewed_synthetic_path_still_obeys_forbidden_extension_rules(self):
        # Keyword exemptions must not become a general file-format bypass.
        self.assertFalse(
            privacy.should_skip_keyword_check("design-prototypes/index.pdf")
        )


if __name__ == "__main__":
    unittest.main()
