# Multi-Account Settings Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-current-config settings dialog with a list-first settings center for multiple mailboxes and multiple saved AI profiles while preserving existing configuration, credential, and classification behavior.

**Architecture:** Keep `email_accounts[]` as the mailbox source of truth and add `ai_profiles[]` as the AI source of truth. Pure adapters normalize and validate both lists, then project the first enabled mailbox and the one enabled AI profile into the existing top-level `email`/`imap`/`search` and `ai` objects so the rest of the application remains compatible. `SettingsDialog` becomes a stacked list/editor flow, while secrets remain in Windows Credential Manager and AI secrets gain profile-level isolation with legacy fallback.

**Tech Stack:** Python 3, PySide6 widgets, JSON configuration, `keyring`, `unittest`/`unittest.mock`.

---

## File Map

- Create `scripts/invoice_fetch/ai_profiles.py`: pure AI profile normalization, validation, migration, and active-profile projection.
- Modify `scripts/invoice_fetch/config.py`: default `ai_profiles`, invoke the profile adapter, validate list invariants, retain legacy `ai` projection.
- Modify `scripts/invoice_fetch/credentials.py`: profile-scoped AI credential read/write/delete with provider and environment fallbacks.
- Modify `scripts/invoice_fetch/ai_classifier.py`: accept the active profile ID when loading an API key.
- Modify `scripts/invoice_fetch/__main__.py`: pass active profile ID into `AIClassifier`.
- Modify `scripts/invoice_fetch/gui/settings_dialog.py`: add list-first navigation, mailbox CRUD routing, AI profile CRUD, and both three-step editors without discarding existing provider safety logic.
- Modify `scripts/invoice_fetch/gui/styles.py`: style list rows, status badges, empty states, and settings navigation using the current blue/white visual language.
- Create `tests/test_ai_profiles.py`: profile migration, invariants, projection, and compatibility tests.
- Modify `tests/test_credentials_and_empty_state.py`: profile credential isolation and fallback tests.
- Modify `tests/test_privacy_defaults.py`: active profile ID reaches classifier without changing disabled defaults.
- Create `tests/test_settings_center.py`: list-first GUI behavior, per-mailbox scan ranges, CRUD routing, and AI enable/disable state tests.
- Preserve and run `tests/test_settings_dialog.py`, `tests/test_generic_imap_config.py`, and `tests/test_mailbox_safety_delete.py` as regression coverage.

### Task 1: AI Profile Configuration Adapter

**Files:**
- Create: `scripts/invoice_fetch/ai_profiles.py`
- Modify: `scripts/invoice_fetch/config.py`
- Create: `tests/test_ai_profiles.py`

- [ ] **Step 1: Write failing migration and projection tests**

```python
import unittest

from scripts.invoice_fetch.ai_profiles import (
    apply_active_ai_profile,
    get_ai_profiles,
    validate_ai_profiles,
)


class AIProfileConfigTests(unittest.TestCase):
    def test_legacy_enabled_ai_becomes_one_enabled_profile(self):
        profiles = get_ai_profiles({
            "ai": {"provider": "deepseek", "model": "deepseek-chat", "batch_size": 20}
        })
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["profile_id"], "legacy-deepseek")
        self.assertTrue(profiles[0]["enabled"])

    def test_legacy_none_ai_does_not_create_fake_profile(self):
        self.assertEqual(get_ai_profiles({"ai": {"provider": "none", "model": ""}}), [])

    def test_zero_enabled_profiles_project_ai_disabled(self):
        cfg = {"ai": {"batch_size": 15}}
        apply_active_ai_profile(cfg, [{
            "profile_id": "ai-one",
            "name": "备用模型",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "enabled": False,
        }])
        self.assertEqual(cfg["ai"]["provider"], "none")
        self.assertEqual(cfg["ai"]["model"], "")
        self.assertEqual(cfg["ai"]["batch_size"], 15)

    def test_one_enabled_profile_projects_legacy_ai(self):
        cfg = {"ai": {"batch_size": 20}}
        apply_active_ai_profile(cfg, [{
            "profile_id": "ai-main",
            "name": "主模型",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "enabled": True,
        }])
        self.assertEqual(cfg["ai"], {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "batch_size": 20,
            "profile_id": "ai-main",
        })

    def test_multiple_enabled_profiles_are_rejected(self):
        profiles = [
            {"profile_id": "one", "name": "一", "provider": "deepseek", "model": "m1", "enabled": True},
            {"profile_id": "two", "name": "二", "provider": "gemini", "model": "m2", "enabled": True},
        ]
        with self.assertRaisesRegex(ValueError, "最多只能启用一个 AI 配置"):
            validate_ai_profiles(profiles)
```

- [ ] **Step 2: Run the focused test and confirm the module is missing**

Run: `python -m unittest tests.test_ai_profiles -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.invoice_fetch.ai_profiles'`.

- [ ] **Step 3: Implement the pure AI profile adapter**

```python
# scripts/invoice_fetch/ai_profiles.py
from __future__ import annotations

from typing import Any

VALID_AI_PROVIDERS = {"deepseek", "gemini"}


def _normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    provider = str(raw.get("provider") or "").strip().lower()
    profile_id = str(raw.get("profile_id") or "").strip()
    name = str(raw.get("name") or "").strip()
    model = str(raw.get("model") or "").strip()
    if not profile_id:
        raise ValueError("AI 配置 ID 不能为空。")
    if provider not in VALID_AI_PROVIDERS:
        raise ValueError(f"AI 服务提供商不支持: {provider}")
    if not name:
        raise ValueError("AI 配置名称不能为空。")
    if not model:
        raise ValueError("AI 模型名称不能为空。")
    return {
        "profile_id": profile_id,
        "name": name,
        "provider": provider,
        "model": model,
        "enabled": raw.get("enabled", False) is True,
    }


def validate_ai_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_profile(item) for item in profiles]
    ids = [item["profile_id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("AI 配置 ID 不能重复。")
    if sum(item["enabled"] for item in normalized) > 1:
        raise ValueError("最多只能启用一个 AI 配置。")
    return normalized


def get_ai_profiles(
    cfg: dict[str, Any], source_cfg: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    source = source_cfg if isinstance(source_cfg, dict) else cfg
    raw_profiles = source.get("ai_profiles")
    if "ai_profiles" in source and isinstance(raw_profiles, list):
        return validate_ai_profiles([item for item in raw_profiles if isinstance(item, dict)])
    legacy = source.get("ai") if isinstance(source.get("ai"), dict) else {}
    provider = str(legacy.get("provider") or "none").strip().lower()
    if provider in {"", "none"}:
        return []
    model = str(legacy.get("model") or "").strip()
    return validate_ai_profiles([{
        "profile_id": str(legacy.get("profile_id") or f"legacy-{provider}"),
        "name": f"{provider.title()} 默认配置",
        "provider": provider,
        "model": model,
        "enabled": True,
    }])


def apply_active_ai_profile(
    cfg: dict[str, Any], profiles: list[dict[str, Any]]
) -> dict[str, Any]:
    normalized = validate_ai_profiles(profiles)
    batch_size = int((cfg.get("ai") or {}).get("batch_size", 20))
    cfg["ai_profiles"] = normalized
    active = next((item for item in normalized if item["enabled"]), None)
    cfg["ai"] = {
        "provider": active["provider"] if active else "none",
        "model": active["model"] if active else "",
        "batch_size": batch_size,
    }
    if active:
        cfg["ai"]["profile_id"] = active["profile_id"]
    return cfg
```

- [ ] **Step 4: Integrate profiles into config defaults and normalization**

Add `"ai_profiles": []` to `_DEFAULTS`. In `_normalize_config`, call `get_ai_profiles`, then `apply_active_ai_profile`. In `validate_config_gui`, convert profile adapter `ValueError` messages into the existing GUI validation error path.

```python
from .ai_profiles import apply_active_ai_profile, get_ai_profiles


profiles = get_ai_profiles(cfg, source_cfg)
apply_active_ai_profile(cfg, profiles)
```

Do not generate random IDs during config loading. New IDs are generated only when the user creates a profile in the GUI.

- [ ] **Step 5: Run configuration tests**

Run: `python -m unittest tests.test_ai_profiles tests.test_generic_imap_config tests.test_privacy_defaults -v`

Expected: all tests PASS, including legacy `ai.provider == "none"` defaults.

- [ ] **Step 6: Commit the adapter**

```powershell
git add scripts/invoice_fetch/ai_profiles.py scripts/invoice_fetch/config.py tests/test_ai_profiles.py
git commit -m "feat(config): add multiple AI profiles"
```

### Task 2: Profile-Scoped AI Credentials

**Files:**
- Modify: `scripts/invoice_fetch/credentials.py`
- Modify: `tests/test_credentials_and_empty_state.py`

- [ ] **Step 1: Write failing credential isolation tests**

```python
class AIProfileCredentialTests(unittest.TestCase):
    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_ai_profile_keys_use_different_services(self, mock_keyring):
        set_ai_api_key("deepseek", "key-one", profile_id="ai-one")
        set_ai_api_key("deepseek", "key-two", profile_id="ai-two")
        services = [call.args[0] for call in mock_keyring.set_password.call_args_list]
        self.assertEqual(
            services,
            ["invoice-hub:ai-profile:ai-one", "invoice-hub:ai-profile:ai-two"],
        )

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_profile_key_falls_back_to_legacy_provider_key(self, mock_keyring):
        mock_keyring.get_password.side_effect = [None, "legacy-key"]
        self.assertEqual(
            get_ai_api_key("deepseek", profile_id="ai-one"), "legacy-key"
        )
        self.assertEqual(
            mock_keyring.get_password.call_args_list[1].args[0],
            "invoice-hub:ai:deepseek",
        )

    @patch("scripts.invoice_fetch.credentials.keyring")
    def test_delete_profile_key_does_not_delete_legacy_key(self, mock_keyring):
        delete_ai_api_key("deepseek", profile_id="ai-one")
        mock_keyring.delete_password.assert_called_once_with(
            "invoice-hub:ai-profile:ai-one", "default"
        )
```

- [ ] **Step 2: Run the credential tests and confirm signature failures**

Run: `python -m unittest tests.test_credentials_and_empty_state -v`

Expected: FAIL because the AI credential functions do not accept `profile_id`.

- [ ] **Step 3: Add optional profile-aware service selection**

```python
def _ai_keyring_service(provider: str, profile_id: str = "") -> str:
    if profile_id:
        return f"invoice-hub:ai-profile:{profile_id}"
    return f"invoice-hub:ai:{provider}"


def _get_ai_key_from_environment(provider: str) -> str:
    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = env_map.get(provider)
    if not env_var:
        raise ValueError(f"未知 AI 提供商: {provider}")
    key = os.environ.get(env_var, "")
    if not key:
        _log.error("未找到 AI API 密钥，请配置系统凭据或环境变量 %s。", env_var)
        raise SystemExit(1)
    return key


def get_ai_api_key(provider: str, profile_id: str = "") -> str:
    services = []
    if profile_id:
        services.append(_ai_keyring_service(provider, profile_id))
    services.append(_ai_keyring_service(provider))
    for service in services:
        try:
            secret = keyring.get_password(service, "default")
            if secret:
                return secret
        except Exception:
            continue
    return _get_ai_key_from_environment(provider)


def set_ai_api_key(provider: str, api_key: str, profile_id: str = "") -> None:
    keyring.set_password(_ai_keyring_service(provider, profile_id), "default", api_key)


def has_ai_api_key(provider: str, profile_id: str = "") -> bool:
    try:
        return bool(get_ai_api_key(provider, profile_id))
    except (ValueError, SystemExit):
        return False


def delete_ai_api_key(provider: str, profile_id: str = "") -> None:
    service = _ai_keyring_service(provider, profile_id)
    try:
        keyring.delete_password(service, "default")
    except Exception:
        pass
```

Preserve existing calls without `profile_id` and never log credential contents.

- [ ] **Step 4: Run credential and privacy tests**

Run: `python -m unittest tests.test_credentials_and_empty_state tests.test_settings_secret_privacy tests.test_log_privacy -v`

Expected: all tests PASS and no assertion observes secret text in logs.

- [ ] **Step 5: Commit profile credentials**

```powershell
git add scripts/invoice_fetch/credentials.py tests/test_credentials_and_empty_state.py
git commit -m "feat(credentials): isolate AI profile keys"
```

### Task 3: Runtime Active-Profile Compatibility

**Files:**
- Modify: `scripts/invoice_fetch/ai_classifier.py`
- Modify: `scripts/invoice_fetch/__main__.py`
- Modify: `tests/test_privacy_defaults.py`
- Modify: `tests/test_invoice_workflow.py`

- [ ] **Step 1: Write failing active profile forwarding tests**

```python
from unittest.mock import patch

from scripts.invoice_fetch.ai_classifier import AIClassifier


@patch("scripts.invoice_fetch.ai_classifier.get_ai_api_key", return_value="test-key")
def test_classifier_loads_profile_scoped_key(mock_get_key):
    AIClassifier(
        provider="deepseek",
        model="deepseek-chat",
        batch_size=20,
        profile_id="ai-main",
    )
    mock_get_key.assert_called_once_with("deepseek", profile_id="ai-main")
```

Add this `_run_classify` forwarding test:

```python
from unittest.mock import MagicMock, patch

import scripts.invoice_fetch.__main__ as invoice_main


def test_run_classify_forwards_active_profile_id(self):
    captured = {}

    class FakeClassifier:
        auth_failed = False

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def classify_batch(self, emails):
            return [{"uid": emails[0]["uid"], "is_invoice": True, "reason": "test"}]

    db = MagicMock()
    db.get_unclassified_emails.return_value = [{
        "uid": 1,
        "subject": "普通邮件",
        "sender": "sender@example.com",
        "mailbox_key": "mailbox-one",
    }]
    db.is_trusted_sender.return_value = False
    ai_cfg = {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "batch_size": 20,
        "profile_id": "ai-main",
    }
    with patch.object(invoice_main, "AIClassifier", FakeClassifier, create=True), patch.object(
        invoice_main, "rule_classify", return_value=(-1, "未命中本地规则")
    ):
        invoice_main._run_classify(db, ai_cfg, no_ai=False, mailbox_key="mailbox-one")
    self.assertEqual(captured["profile_id"], "ai-main")
```

- [ ] **Step 2: Run the focused runtime tests and confirm failures**

Run: `python -m unittest tests.test_privacy_defaults tests.test_invoice_workflow -v`

Expected: FAIL because `AIClassifier.__init__` does not accept `profile_id` and `_run_classify` does not forward it.

- [ ] **Step 3: Pass the profile ID through runtime classification**

```python
# scripts/invoice_fetch/ai_classifier.py
def __init__(
    self,
    provider: str = "none",
    model: str = "",
    batch_size: int = 20,
    profile_id: str = "",
):
    self.provider = (provider or "none").lower()
    self.model = model or _DEFAULT_MODELS.get(self.provider, "")
    self.batch_size = batch_size
    self.profile_id = str(profile_id or "")
    self.auth_failed = False
    self.api_key = ""
    if self.provider != "none":
        self.api_key = get_ai_api_key(self.provider, profile_id=self.profile_id)
```

```python
# scripts/invoice_fetch/__main__.py inside _run_classify
ai = classifier_cls(
    provider=provider,
    model=ai_cfg.get("model", ""),
    batch_size=ai_cfg.get("batch_size", 20),
    profile_id=ai_cfg.get("profile_id", ""),
)
```

- [ ] **Step 4: Run classification regression tests**

Run: `python -m unittest tests.test_privacy_defaults tests.test_ai_classifier tests.test_invoice_workflow -v`

Expected: all tests PASS; disabled AI still does not request a key.

- [ ] **Step 5: Commit runtime compatibility**

```powershell
git add scripts/invoice_fetch/ai_classifier.py scripts/invoice_fetch/__main__.py tests/test_privacy_defaults.py tests/test_invoice_workflow.py
git commit -m "feat(ai): load the active profile credential"
```

### Task 4: List-First Settings Center and Mailbox CRUD

**Files:**
- Modify: `scripts/invoice_fetch/gui/settings_dialog.py`
- Modify: `scripts/invoice_fetch/gui/styles.py`
- Create: `tests/test_settings_center.py`
- Preserve: `tests/test_settings_dialog.py`
- Preserve: `tests/test_mailbox_safety_delete.py`

- [ ] **Step 1: Write failing list-first and per-mailbox range tests**

```python
import unittest

from tests.test_settings_dialog import SettingsDialogTestMixin


class SettingsCenterMailboxTests(SettingsDialogTestMixin, unittest.TestCase):
    def test_dialog_opens_on_settings_home(self):
        dialog = self._make_dialog()
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_settings_home)

    def test_mailbox_rows_show_each_accounts_scan_range(self):
        dialog = self._make_dialog()
        dialog.cfg["email_accounts"] = [
            {
                "mailbox_key": "work@qq.com",
                "name": "工作邮箱",
                "enabled": True,
                "provider": "qq",
                "address": "work@qq.com",
                "username": "work@qq.com",
                "imap": {"server": "imap.qq.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 3},
            },
            {
                "mailbox_key": "history@163.com",
                "name": "历史邮箱",
                "enabled": True,
                "provider": "netease_163",
                "address": "history@163.com",
                "username": "history@163.com",
                "imap": {"server": "imap.163.com", "port": 993, "ssl": True},
                "search": {"folder": "INBOX", "months_back": 12},
            },
        ]
        dialog._refresh_mailbox_list()
        row_text = [row.summary_text() for row in dialog.mailbox_rows]
        self.assertIn("最近 3 个月", row_text[0])
        self.assertIn("最近 12 个月", row_text[1])

    def test_edit_routes_by_mailbox_key_not_provider(self):
        dialog = self._make_dialog()
        dialog._open_mailbox_editor("second@qq.com")
        self.assertEqual(dialog._loaded_account_mailbox_key, "second@qq.com")
        self.assertIs(dialog.settings_stack.currentWidget(), dialog.page_mailbox_editor)
```

Add tests for empty state, add action, save returning to the mailbox tab, and preventing deletion or disabling of the last enabled mailbox.

- [ ] **Step 2: Run the new GUI tests and confirm missing settings-center widgets**

Run: `python -m unittest tests.test_settings_center.SettingsCenterMailboxTests -v`

Expected: FAIL with missing `settings_stack` or `page_settings_home` attributes.

- [ ] **Step 3: Replace the top-level tabs with a stacked list/editor shell**

Build these pages in `SettingsDialog.__init__`:

```python
self.settings_stack = QStackedWidget()
self.page_settings_home = QWidget()
self.page_mailbox_editor = QWidget()
self.page_ai_editor = QWidget()
self.settings_stack.addWidget(self.page_settings_home)
self.settings_stack.addWidget(self.page_mailbox_editor)
self.settings_stack.addWidget(self.page_ai_editor)
self.main_layout.addWidget(self.settings_stack)
```

The home page contains a `QTabWidget` with mailbox and AI list tabs. Keep the existing mailbox wizard controls and methods, but attach them to `page_mailbox_editor`. Preserve provider cards, Outlook blocking, secure authorization-code input, advanced IMAP settings, connection testing, and delete safety behavior until list-owned delete replaces the old editor button.

- [ ] **Step 4: Add a focused mailbox row widget and stable-ID routing**

```python
class MailboxConfigRow(QFrame):
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    enabled_requested = Signal(str, bool)

    def __init__(self, account: dict, parent=None):
        super().__init__(parent)
        self.account = dict(account)
        self.mailbox_key = str(account.get("mailbox_key") or account.get("address") or "")

    def summary_text(self) -> str:
        months = int((self.account.get("search") or {}).get("months_back", 3))
        return f"最近 {months} 个月"
```

Use `mailbox_key` for edit, enable, and delete actions. Add `_show_settings_home(tab_name)`, `_open_new_mailbox_editor()`, `_open_mailbox_editor(mailbox_key)`, and `_refresh_mailbox_list()` methods. Editing loads exactly one matching account and never selects another account merely because it has the same provider.

- [ ] **Step 5: Make mailbox save return to the list**

Keep `_save_mailbox_settings` validation and credential writes, then replace successful `self.accept()` with:

```python
self.cfg = _load_config_safe_compat()
self.parent.config = self.cfg
self._build_saved_account_maps()
self._refresh_mailbox_list()
self._show_settings_home("mailboxes")
```

Store `name` and each account's own `search.months_back`. Continue projecting the first enabled account into top-level `email`, `imap`, and `search`. Do not add a global scan-months control.

- [ ] **Step 6: Move mailbox deletion to list actions**

Refactor `_delete_current_mailbox` into `_delete_mailbox(mailbox_key)`. Keep the existing confirmation that imported invoices and attachments remain. Before deletion or disable, count other enabled accounts; if none remain, show `至少需要保留一个启用的邮箱账号。` and leave config and credentials unchanged.

- [ ] **Step 7: Run mailbox GUI regressions**

Run: `python -m unittest tests.test_settings_center.SettingsCenterMailboxTests tests.test_settings_dialog tests.test_mailbox_safety_delete tests.test_generic_imap_config -v`

Expected: all tests PASS, including multiple accounts with the same provider and different `months_back` values.

- [ ] **Step 8: Commit the settings center mailbox flow**

```powershell
git add scripts/invoice_fetch/gui/settings_dialog.py scripts/invoice_fetch/gui/styles.py tests/test_settings_center.py
git commit -m "feat(settings): add mailbox configuration center"
```

### Task 5: AI Profile List, Wizard, and Derived Enable State

**Files:**
- Modify: `scripts/invoice_fetch/gui/settings_dialog.py`
- Modify: `scripts/invoice_fetch/gui/styles.py`
- Modify: `tests/test_settings_center.py`
- Preserve: `tests/test_settings_secret_privacy.py`

- [ ] **Step 1: Write failing AI list state tests**

```python
class SettingsCenterAIProfileTests(SettingsDialogTestMixin, unittest.TestCase):
    def test_no_enabled_profile_shows_ai_disabled(self):
        dialog = self._make_dialog()
        dialog.cfg["ai_profiles"] = [{
            "profile_id": "ai-one",
            "name": "备用模型",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": False,
        }]
        dialog._refresh_ai_profile_list()
        self.assertEqual(dialog.lbl_ai_global_status.text(), "AI 功能未启用")

    def test_set_current_disables_every_other_profile(self):
        dialog = self._make_dialog()
        dialog.cfg["ai_profiles"] = [
            {"profile_id": "one", "name": "一", "provider": "deepseek", "model": "m1", "enabled": True},
            {"profile_id": "two", "name": "二", "provider": "gemini", "model": "m2", "enabled": False},
        ]
        dialog._set_active_ai_profile("two")
        enabled = [p["profile_id"] for p in dialog.cfg["ai_profiles"] if p["enabled"]]
        self.assertEqual(enabled, ["two"])
        self.assertEqual(dialog.cfg["ai"]["profile_id"], "two")

    def test_disable_ai_keeps_profiles_and_clears_active_projection(self):
        dialog = self._make_dialog()
        before = len(dialog.cfg["ai_profiles"])
        dialog._disable_ai()
        self.assertEqual(len(dialog.cfg["ai_profiles"]), before)
        self.assertFalse(any(p["enabled"] for p in dialog.cfg["ai_profiles"]))
        self.assertEqual(dialog.cfg["ai"]["provider"], "none")

    def test_new_ai_provider_choices_do_not_include_none(self):
        dialog = self._make_dialog()
        dialog._open_new_ai_editor()
        providers = [dialog.combo_ai_provider.itemText(i) for i in range(dialog.combo_ai_provider.count())]
        self.assertEqual(providers, ["deepseek", "gemini"])
```

Add tests for `仅保存配置`, `保存并设为当前`, replacement confirmation, deleting active profile disabling AI, deleting inactive profile leaving AI unchanged, and missing Key preventing activation.

- [ ] **Step 2: Run the AI settings-center tests and confirm missing list behavior**

Run: `python -m unittest tests.test_settings_center.SettingsCenterAIProfileTests -v`

Expected: FAIL with missing AI list/status methods.

- [ ] **Step 3: Build AI profile rows and derived global status**

```python
class AIProfileRow(QFrame):
    activate_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, profile: dict, key_available: bool, parent=None):
        super().__init__(parent)
        self.profile = dict(profile)
        self.profile_id = str(profile["profile_id"])
```

`_refresh_ai_profile_list()` uses `get_ai_profiles(self.cfg)`, checks each profile with `has_ai_api_key(provider, profile_id)`, and derives the header:

```python
active = next((profile for profile in profiles if profile["enabled"]), None)
self.lbl_ai_global_status.setText(
    f"AI 功能已启用：{active['name']}" if active else "AI 功能未启用"
)
```

There is no independent enable checkbox and no `none` provider card.

- [ ] **Step 4: Convert the AI editor into a three-step wizard**

Use `QStackedWidget` and the same footer pattern as the mailbox editor:

1. Provider and configuration name.
2. Model and secure API Key input.
3. Validation summary with `仅保存配置` and `保存并设为当前`.

Generate new IDs only from the new-profile action:

```python
from uuid import uuid4

self._editing_ai_profile_id = f"ai-{uuid4().hex[:8]}"
```

Editing keeps the existing `profile_id`. A blank Key means retain the stored profile credential. Saving a new Key calls `set_ai_api_key(provider, key, profile_id=profile_id)`.

- [ ] **Step 5: Implement explicit activation, disable, and deletion**

```python
def _set_active_ai_profile(self, profile_id: str) -> None:
    profiles = get_ai_profiles(self.cfg)
    target = next(profile for profile in profiles if profile["profile_id"] == profile_id)
    if not has_ai_api_key(target["provider"], target["profile_id"]):
        QMessageBox.warning(self, "无法启用 AI", "请先为该配置保存有效的 API Key。")
        return
    for profile in profiles:
        profile["enabled"] = profile["profile_id"] == profile_id
    apply_active_ai_profile(self.cfg, profiles)
    self._persist_settings_and_refresh("ai")


def _disable_ai(self) -> None:
    profiles = get_ai_profiles(self.cfg)
    for profile in profiles:
        profile["enabled"] = False
    apply_active_ai_profile(self.cfg, profiles)
    self._persist_settings_and_refresh("ai")


def _persist_settings_and_refresh(self, tab_name: str) -> None:
    from ..config import save_config

    save_config(self.cfg)
    self.cfg = _load_config_safe_compat()
    self.parent.config = self.cfg
    self._build_saved_account_maps()
    self._refresh_mailbox_list()
    self._refresh_ai_profile_list()
    self._show_settings_home(tab_name)
```

Deleting the active profile applies the remaining list with all entries disabled; it never activates another profile automatically. Deleting a profile calls `delete_ai_api_key(provider, profile_id=profile_id)` only after configuration persistence succeeds.

- [ ] **Step 6: Run AI UI and secret privacy tests**

Run: `python -m unittest tests.test_settings_center.SettingsCenterAIProfileTests tests.test_settings_secret_privacy tests.test_generic_imap_config -v`

Expected: all tests PASS; secure inputs still block copy/cut and no API Key text appears in messages or logs.

- [ ] **Step 7: Commit the AI profile UI**

```powershell
git add scripts/invoice_fetch/gui/settings_dialog.py scripts/invoice_fetch/gui/styles.py tests/test_settings_center.py
git commit -m "feat(settings): manage multiple AI profiles"
```

### Task 6: Visual Polish, Full Regression, and Documentation Alignment

**Files:**
- Modify: `scripts/invoice_fetch/gui/styles.py`
- Modify: `config.example.json`
- Modify: `README.md`
- Modify: `docs/user-quickstart.md`
- Verify: `docs/superpowers/specs/2026-06-19-multi-account-settings-design.md`

- [ ] **Step 1: Add final style selectors without inline UI colors**

Add named Qt properties for `SettingsListRow`, `StatusBadge`, `EmptyState`, and `SettingsDangerLink`. Reuse the existing palette: `#2563EB` primary, `#F8FAFC` surface, `#E5E7EB` border, `#059669` success, `#D97706` warning, and `#B91C1C` danger. Remove newly introduced inline style strings from the settings-center code.

- [ ] **Step 2: Update example configuration**

Add an inactive example profile while keeping AI disabled by default:

```json
"ai_profiles": [
  {
    "profile_id": "ai-example-deepseek",
    "name": "DeepSeek 示例配置",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "enabled": false
  }
],
"ai": {
  "provider": "none",
  "model": "",
  "batch_size": 20
}
```

Do not include an API Key in JSON.

- [ ] **Step 3: Update user documentation**

Document these exact behaviors:

- System settings opens on mailbox/AI lists.
- Mailbox scan range is configured per account.
- Multiple mailboxes can be enabled.
- Multiple AI profiles can be saved, but only one can be current.
- No current AI profile means AI is disabled.
- Secrets remain in Windows Credential Manager.

- [ ] **Step 4: Run focused settings and configuration suites**

Run:

```powershell
python -m unittest tests.test_ai_profiles tests.test_settings_center tests.test_settings_dialog tests.test_mailbox_safety_delete tests.test_generic_imap_config tests.test_credentials_and_empty_state tests.test_settings_secret_privacy tests.test_privacy_defaults tests.test_ai_classifier -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run the complete repository verification stack**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall scripts tests
python scripts/check_public_export.py
git diff --check
```

Expected: all commands exit `0`; public-export check reports no forbidden local artifacts. If tests recreate `runtime/`, remove only that generated directory after confirming its resolved path is inside the repository.

- [ ] **Step 6: Perform manual desktop UI verification**

Launch the application using the repository's normal desktop entry point. Verify:

- `系统配置` opens on the list page.
- The default dialog size shows list actions without horizontal clipping.
- Long addresses are elided or wrapped without pushing buttons off-screen.
- Each mailbox shows its own scan-month range.
- Mailbox and AI editors scroll on smaller displays.
- Save and cancel return to the correct list.
- No current AI profile shows `AI 功能未启用`.
- Setting a profile current changes the header and row badge immediately.
- Disabling AI preserves all saved profiles.

- [ ] **Step 7: Commit polish and docs**

```powershell
git add scripts/invoice_fetch/gui/styles.py config.example.json README.md docs/user-quickstart.md
git commit -m "docs(settings): explain multi-account configuration"
```

## Execution Notes

- Before editing `scripts/invoice_fetch/gui/settings_dialog.py`, inspect the working tree and preserve any user changes; do not reset, checkout, or replace that file wholesale.
- `.superpowers/brainstorm/` contains local visual exploration artifacts and must not be staged.
- Before each commit, run `git diff --cached --name-only` and confirm only the task's files are staged.
- If concurrent user edits overlap `settings_dialog.py`, stop and reconcile with the user instead of overwriting them.
