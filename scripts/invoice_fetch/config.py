"""Configuration loader — reads config.json (no credentials)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .log_privacy import mask_email

_log = logging.getLogger(__name__)

_EMAIL_PROVIDER_PRESETS = {
    "qq": {"server": "imap.qq.com", "port": 993, "ssl": True},
    "netease_163": {"server": "imap.163.com", "port": 993, "ssl": True},
    "netease_126": {"server": "imap.126.com", "port": 993, "ssl": True},
    "gmail": {"server": "imap.gmail.com", "port": 993, "ssl": True},
    "outlook": {"server": "outlook.office365.com", "port": 993, "ssl": True},
    "custom": {"server": "", "port": 993, "ssl": True},
}
_VALID_EMAIL_PROVIDERS = set(_EMAIL_PROVIDER_PRESETS)

_DEFAULTS = {
    "email": {"provider": "qq", "address": "", "username": ""},
    "imap": {"server": "", "port": 993, "ssl": True},
    "search": {"folder": "INBOX", "months_back": 3},
    "email_accounts": [],
    "ai": {"provider": "none", "model": "", "batch_size": 20},
    "reimbursement": {"buyer_name": "", "buyer_tax_id": "", "strict_buyer_check": False},
    "playwright": {"channel": "auto"},
    "categories": {},
}

_DEFAULT_AI_MODELS = {
    "none": "",
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash",
}

_VALID_AI_PROVIDERS = set(_DEFAULT_AI_MODELS)

# Project root: two levels up from this file → d:\01_workspace\win\bill
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_runtime_dir():
    import sys
    override = os.environ.get("INVOICE_HUB_RUNTIME_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "InvoiceHub"
    return PROJECT_ROOT / "runtime"


RUNTIME_DIR = _resolve_runtime_dir()


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*."""
    import copy
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def _normalize_search_months(value: Any, default: int = 3) -> int:
    try:
        months = int(value)
    except (TypeError, ValueError):
        months = default
    return months if months > 0 else default


def _normalize_imap_for_provider(
    provider: str,
    imap_cfg: dict[str, Any] | None = None,
    fallback_imap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preset = _EMAIL_PROVIDER_PRESETS[provider]
    merged = {}
    if isinstance(fallback_imap, dict):
        merged.update(fallback_imap)
    if isinstance(imap_cfg, dict):
        merged.update(imap_cfg)

    server = str(merged.get("server") or "").strip()
    if provider == "custom":
        if not server:
            raise SystemExit("请在 config.json 中设置 imap.server，或选择非 custom 的 email.provider")
    elif not server:
        merged["server"] = preset["server"]

    port = merged.get("port")
    if port in {None, ""}:
        merged["port"] = preset["port"]
    else:
        try:
            merged["port"] = int(port)
        except (TypeError, ValueError):
            raise SystemExit("IMAP 端口必须是有效的整数")

    if "ssl" not in merged or merged.get("ssl") in {None, ""}:
        merged["ssl"] = preset["ssl"]
    else:
        merged["ssl"] = bool(merged.get("ssl"))
    return merged


def _normalize_email_account(
    account: dict[str, Any],
    *,
    source_cfg: dict[str, Any] | None = None,
    legacy: bool = False,
) -> dict[str, Any]:
    source_cfg = source_cfg or {}
    base_email = source_cfg.get("email", {}) if isinstance(source_cfg.get("email", {}), dict) else {}
    base_imap = source_cfg.get("imap", {}) if isinstance(source_cfg.get("imap", {}), dict) else {}
    base_search = source_cfg.get("search", {}) if isinstance(source_cfg.get("search", {}), dict) else {}

    merged = {}
    if isinstance(base_email, dict):
        merged.update(base_email)
    merged.update(account or {})

    provider = str(merged.get("provider") or base_email.get("provider") or "qq").lower()
    if provider not in _VALID_EMAIL_PROVIDERS:
        raise SystemExit(
            f"不支持的 email.provider: {provider}. "
            f"支持: {', '.join(sorted(_VALID_EMAIL_PROVIDERS))}"
        )

    address = str(merged.get("address") or "").strip()
    if not address:
        raise SystemExit("邮箱地址不能为空")

    username = str(merged.get("username") or "").strip() or address
    imap_cfg = _normalize_imap_for_provider(
        provider,
        merged.get("imap") if isinstance(merged.get("imap"), dict) else None,
        base_imap,
    )

    search_cfg = {}
    if isinstance(base_search, dict):
        search_cfg.update(base_search)
    if isinstance(merged.get("search"), dict):
        search_cfg.update(merged.get("search"))
    search_cfg["folder"] = str(search_cfg.get("folder") or "INBOX").strip() or "INBOX"
    search_cfg["months_back"] = _normalize_search_months(search_cfg.get("months_back"), 3)

    name = str(merged.get("name") or "").strip() or address or provider
    enabled = merged.get("enabled", True) is not False
    raw_mailbox_key = str(merged.get("mailbox_key") or "").strip()
    mailbox_key = "legacy" if legacy else (raw_mailbox_key or address.lower())

    return {
        "name": name,
        "enabled": enabled,
        "provider": provider,
        "address": address,
        "username": username,
        "imap": imap_cfg,
        "search": search_cfg,
        "mailbox_key": mailbox_key,
    }


def get_email_accounts(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized enabled mailbox accounts from config."""
    raw_accounts = cfg.get("email_accounts")
    if isinstance(raw_accounts, list) and raw_accounts:
        accounts = []
        for raw in raw_accounts:
            if not isinstance(raw, dict):
                raise SystemExit("email_accounts 中的每个账号都必须是对象")
            if raw.get("enabled", True) is False:
                continue
            accounts.append(_normalize_email_account(raw, source_cfg=cfg))
        return accounts

    email_cfg = cfg.get("email", {}) if isinstance(cfg.get("email", {}), dict) else {}
    imap_cfg = cfg.get("imap", {}) if isinstance(cfg.get("imap", {}), dict) else {}
    search_cfg = cfg.get("search", {}) if isinstance(cfg.get("search", {}), dict) else {}
    legacy_account = {
        "name": str(email_cfg.get("name") or "").strip() or str(email_cfg.get("address") or "").strip() or str(email_cfg.get("provider") or "legacy"),
        "enabled": True,
        "provider": email_cfg.get("provider") or "qq",
        "address": email_cfg.get("address") or "",
        "username": email_cfg.get("username") or "",
        "imap": imap_cfg,
        "search": search_cfg,
    }
    return [_normalize_email_account(legacy_account, source_cfg=cfg, legacy=True)]


def _apply_primary_email_account(cfg: dict[str, Any], accounts: list[dict[str, Any]]) -> dict[str, Any]:
    if not accounts:
        return cfg
    primary = accounts[0]
    cfg["email_accounts"] = accounts
    cfg["email"] = {
        "provider": primary["provider"],
        "address": primary["address"],
        "username": primary["username"],
    }
    cfg["imap"] = dict(primary["imap"])
    cfg["search"] = dict(primary["search"])
    return cfg


def _normalize_email_imap_config(
    cfg: dict[str, Any],
    source_cfg: dict[str, Any] | None = None,
) -> None:
    """Normalize mailbox provider and IMAP settings in-place.

    The MVP supports standard IMAP through provider presets. Custom and
    enterprise mailboxes can set ``email.provider = custom`` and provide
    ``imap.server`` / ``imap.port`` explicitly.
    """
    email_cfg = cfg.setdefault("email", {})
    imap_cfg = cfg.setdefault("imap", {})
    source_imap_cfg = (source_cfg or {}).get("imap", {})

    provider = (email_cfg.get("provider") or "qq").lower()
    if provider not in _VALID_EMAIL_PROVIDERS:
        raise SystemExit(
            f"不支持的 email.provider: {provider}. "
            f"支持: {', '.join(sorted(_VALID_EMAIL_PROVIDERS))}"
        )
    email_cfg["provider"] = provider

    address = (email_cfg.get("address") or "").strip()
    username = (email_cfg.get("username") or "").strip()
    if address:
        email_cfg["address"] = address
    if not username:
        email_cfg["username"] = address
    else:
        email_cfg["username"] = username

    imap_cfg.update(_normalize_imap_for_provider(provider, source_imap_cfg, imap_cfg))


def _normalize_config(
    cfg: dict[str, Any],
    source_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _normalize_email_imap_config(cfg, source_cfg)

    ai_cfg = cfg.setdefault("ai", {})
    provider = (ai_cfg.get("provider") or "none").lower()
    if provider not in _VALID_AI_PROVIDERS:
        raise SystemExit(
            f"AI 服务提供商不支持: {provider}. "
            f"支持: {', '.join(sorted(_VALID_AI_PROVIDERS))}"
        )
    ai_cfg["provider"] = provider
    if not ai_cfg.get("model"):
        ai_cfg["model"] = _DEFAULT_AI_MODELS.get(provider, "")
    return cfg


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate configuration.

    Resolution order:
        1. Explicit *path*
        2. ``config.json`` in RUNTIME_DIR (if sys.frozen is True) or PROJECT_ROOT
        3. ``config.example.json`` in project root (read-only fallback)
    """
    import sys
    if path is None:
        if getattr(sys, "frozen", False):
            path = RUNTIME_DIR / "config.json"
        else:
            path = PROJECT_ROOT / "config.json"
        if not path.exists():
            path = PROJECT_ROOT / "config.example.json"

    path = Path(path)
    if not path.exists():
        _log.error("配置文件不存在: %s", path)
        _log.error("请复制 config.example.json 为 config.json 并填写邮箱地址")
        raise SystemExit(1)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"配置文件格式错误: {exc}\n"
            f"请检查 {path} 中的 JSON 语法"
        ) from None

    cfg = _normalize_config(_deep_merge(_DEFAULTS, raw), raw)

    raw_accounts = raw.get("email_accounts")
    if isinstance(raw_accounts, list) and raw_accounts:
        accounts = get_email_accounts(cfg)
        if not accounts:
            _log.error("请至少配置一个启用的邮箱账号")
            raise SystemExit(1)
        _apply_primary_email_account(cfg, accounts)
    else:
        # Validate legacy single-account config for backward compatibility.
        email_addr = cfg.get("email", {}).get("address", "")
        if not email_addr or email_addr in {"your_email@qq.com", "your_email@example.com"}:
            _log.error("请在 config.json 中设置真实的 email.address")
            raise SystemExit(1)

        imap_server = cfg.get("imap", {}).get("server", "")
        if not imap_server:
            _log.error("请在 config.json 中设置 imap.server，或选择非 custom 的 email.provider")
            raise SystemExit(1)
        accounts = get_email_accounts(cfg)
        _apply_primary_email_account(cfg, accounts)

    _log.info("配置已加载: %s", path.name)
    if cfg.get("ai", {}).get("provider") == "none":
        _log.info("AI 分类默认关闭，仅使用本地规则/白名单；如需启用，请在 config.json 中设置 provider")
    return cfg


def load_config_safe(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration safely without raising SystemExit if validation or reading fails."""
    import copy
    import sys

    def defaults_with_presets() -> dict[str, Any]:
        return _normalize_config(copy.deepcopy(_DEFAULTS), _DEFAULTS)

    if path is None:
        if getattr(sys, "frozen", False):
            path = RUNTIME_DIR / "config.json"
        else:
            path = PROJECT_ROOT / "config.json"
        if not path.exists():
            path = PROJECT_ROOT / "config.example.json"

    path = Path(path)
    if not path.exists():
        return defaults_with_presets()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        cfg = _normalize_config(_deep_merge(_DEFAULTS, raw), raw)
        try:
            accounts = get_email_accounts(cfg)
            if accounts:
                return _apply_primary_email_account(cfg, accounts)
        except SystemExit:
            pass
        return cfg
    except Exception:
        return defaults_with_presets()


def validate_config_gui(cfg: dict) -> None:
    """Validate configuration fields for GUI settings. Raises ValueError if invalid."""
    try:
        cfg = _normalize_config(_deep_merge(_DEFAULTS, cfg), cfg)
    except SystemExit as exc:
        raise ValueError(str(exc) or "邮箱配置无效。") from None

    if not cfg.get("email_accounts"):
        email_cfg = cfg.get("email", {})
        email_addr = email_cfg.get("address", "")
        if not email_addr:
            raise ValueError("邮箱地址不能为空。")
        if email_addr in {"your_email@qq.com", "your_email@example.com"}:
            raise ValueError("邮箱地址不能使用默认示例值（如 your_email@qq.com / your_email@example.com），请输入真实的邮箱地址。")

    try:
        accounts = get_email_accounts(cfg)
    except SystemExit as exc:
        raise ValueError(str(exc) or "邮箱配置无效。") from None

    if not accounts:
        raise ValueError("至少需要配置一个启用的邮箱账号。")

    for account in accounts:
        imap_server = account.get("imap", {}).get("server", "")
        if not imap_server:
            raise ValueError(f"邮箱账号 {mask_email(account.get('address', ''))} 的 IMAP 服务器不能为空。")

        imap_port = account.get("imap", {}).get("port")
        try:
            port_num = int(imap_port)
        except (TypeError, ValueError):
            raise ValueError("IMAP 端口必须是有效的整数。")
        if not (1 <= port_num <= 65535):
            raise ValueError("IMAP 端口范围必须在 1 到 65535 之间。")

        months_back = account.get("search", {}).get("months_back")
        try:
            months_num = int(months_back)
        except (TypeError, ValueError):
            raise ValueError("搜索月份数必须是有效的整数。")
        if not (1 <= months_num <= 24):
            raise ValueError("搜索月份数必须在 1 到 24 之间。")

    ai_provider = cfg.get("ai", {}).get("provider", "none")
    if not isinstance(ai_provider, str) or ai_provider.lower() not in {"none", "deepseek", "gemini"}:
        raise ValueError("AI 服务提供商必须是 none, deepseek 或 gemini 之一。")

def save_config(cfg: dict, path: str | Path | None = None) -> None:
    """Save configuration to config.json safely, filtering out secret-like fields."""
    import copy
    clean_cfg = copy.deepcopy(cfg)

    # Recursively remove keys containing 'auth_code', 'password', 'token', or 'api_key'
    def _strip_secrets(d: Any) -> None:
        if isinstance(d, dict):
            keys_to_del = []
            for k in list(d.keys()):
                kl = k.lower()
                if "auth_code" in kl or "password" in kl or "token" in kl or "api_key" in kl:
                    keys_to_del.append(k)
                else:
                    _strip_secrets(d[k])
            for k in keys_to_del:
                del d[k]
        elif isinstance(d, list):
            for item in d:
                _strip_secrets(item)

    _strip_secrets(clean_cfg)

    import sys
    if path is None:
        if getattr(sys, "frozen", False):
            path = RUNTIME_DIR / "config.json"
        else:
            path = PROJECT_ROOT / "config.json"
    path = Path(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean_cfg, fh, ensure_ascii=False, indent=2)
