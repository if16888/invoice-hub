import importlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.invoice_fetch.config import load_config, validate_config_gui


class AIProfileAdapterTests(unittest.TestCase):
    def _adapter(self):
        try:
            return importlib.import_module("scripts.invoice_fetch.ai_profiles")
        except ModuleNotFoundError as exc:
            self.fail(f"AI profile adapter is missing: {exc}")

    @staticmethod
    def _profile(**overrides):
        profile = {
            "profile_id": "deepseek-primary",
            "name": "Primary DeepSeek",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
        profile.update(overrides)
        return profile

    def test_legacy_enabled_ai_becomes_enabled_profile(self):
        adapter = self._adapter()
        cfg = {
            "ai": {
                "provider": "deepseek",
                "model": "deepseek-reasoner",
                "batch_size": 12,
            }
        }

        profiles = adapter.get_ai_profiles(cfg, source_cfg=cfg)

        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["profile_id"], "legacy-deepseek")
        self.assertTrue(profiles[0]["enabled"])
        self.assertEqual(profiles[0]["model"], "deepseek-reasoner")

    def test_legacy_provider_none_creates_no_profile(self):
        adapter = self._adapter()
        cfg = {"ai": {"provider": "none", "model": "", "batch_size": 20}}

        self.assertEqual(adapter.get_ai_profiles(cfg, source_cfg=cfg), [])

    def test_legacy_gemini_uses_gemini_2_5_flash_default(self):
        adapter = self._adapter()
        cfg = {"ai": {"provider": "gemini", "model": "", "batch_size": 20}}

        profiles = adapter.get_ai_profiles(cfg, source_cfg=cfg)

        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["model"], "gemini-2.5-flash")

    def test_explicit_empty_profiles_override_legacy_ai(self):
        adapter = self._adapter()
        source_cfg = {
            "ai_profiles": [],
            "ai": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "batch_size": 9,
            },
        }
        cfg = dict(source_cfg)

        profiles = adapter.get_ai_profiles(cfg, source_cfg=source_cfg)
        result = adapter.apply_active_ai_profile(cfg, profiles)

        self.assertEqual(profiles, [])
        self.assertEqual(result["ai"]["provider"], "none")
        self.assertEqual(result["ai"]["model"], "")
        self.assertEqual(result["ai"]["batch_size"], 9)

    def test_zero_enabled_profiles_disable_ai_and_preserve_batch_size(self):
        adapter = self._adapter()
        cfg = {"ai": {"provider": "gemini", "model": "old", "batch_size": 7}}
        profiles = [self._profile(enabled=False)]

        result = adapter.apply_active_ai_profile(cfg, profiles)

        self.assertEqual(result["ai"]["provider"], "none")
        self.assertEqual(result["ai"]["model"], "")
        self.assertEqual(result["ai"]["batch_size"], 7)

    def test_enabled_profile_projects_runtime_ai_fields(self):
        adapter = self._adapter()
        cfg = {"ai": {"provider": "none", "model": "", "batch_size": 15}}
        profiles = [self._profile(
            profile_id=" gemini-fast ",
            name=" Gemini Fast ",
            provider="GEMINI",
            model=" gemini-2.5-flash ",
            batch_size=99,
        )]

        result = adapter.apply_active_ai_profile(cfg, profiles)

        self.assertEqual(result["ai"]["provider"], "gemini")
        self.assertEqual(result["ai"]["model"], "gemini-2.5-flash")
        self.assertEqual(result["ai"]["profile_id"], "gemini-fast")
        self.assertEqual(result["ai"]["batch_size"], 15)

    def test_multiple_enabled_profiles_are_rejected(self):
        adapter = self._adapter()
        profiles = [
            self._profile(),
            self._profile(
                profile_id="gemini-primary",
                name="Primary Gemini",
                provider="gemini",
                model="gemini-2.5-flash",
            ),
        ]

        with self.assertRaisesRegex(ValueError, "^最多只能启用一个 AI 配置。$"):
            adapter.validate_ai_profiles(profiles)

    def test_duplicate_profile_ids_are_rejected(self):
        adapter = self._adapter()
        profiles = [
            self._profile(enabled=False),
            self._profile(name="Duplicate", enabled=False),
        ]

        with self.assertRaisesRegex(ValueError, "^AI 配置 ID 不能重复。$"):
            adapter.validate_ai_profiles(profiles)

    def test_invalid_required_profile_fields_are_rejected(self):
        adapter = self._adapter()
        invalid_profiles = (
            self._profile(profile_id=""),
            self._profile(name=""),
            self._profile(provider="none"),
            self._profile(model=""),
            self._profile(enabled=1),
        )

        for profile in invalid_profiles:
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    adapter.validate_ai_profiles([profile])

    def test_config_normalization_migrates_raw_legacy_ai_despite_default_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps({
                "email": {"provider": "qq", "address": "user@qq.com"},
                "ai": {
                    "provider": "deepseek",
                    "model": "legacy-custom-model",
                    "batch_size": 6,
                },
            }), encoding="utf-8")

            cfg = load_config(path)

        self.assertIn("ai_profiles", cfg)
        self.assertEqual(len(cfg["ai_profiles"]), 1)
        self.assertEqual(cfg["ai_profiles"][0]["profile_id"], "legacy-deepseek")
        self.assertEqual(cfg["ai"]["provider"], "deepseek")
        self.assertEqual(cfg["ai"]["model"], "legacy-custom-model")
        self.assertEqual(cfg["ai"]["batch_size"], 6)

    def test_gui_validation_surfaces_profile_adapter_error(self):
        profiles = [
            self._profile(),
            self._profile(
                profile_id="gemini-primary",
                name="Primary Gemini",
                provider="gemini",
                model="gemini-2.5-flash",
            ),
        ]
        cfg = {
            "email": {"provider": "qq", "address": "user@qq.com"},
            "ai_profiles": profiles,
        }

        with self.assertRaisesRegex(ValueError, "^最多只能启用一个 AI 配置。$"):
            validate_config_gui(cfg)


if __name__ == "__main__":
    unittest.main()
