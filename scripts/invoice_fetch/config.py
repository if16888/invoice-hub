"""Configuration loader — reads config.json (no credentials)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

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

    preset = _EMAIL_PROVIDER_PRESETS[provider]
    source_server = source_imap_cfg.get("server") if isinstance(source_imap_cfg, dict) else None
    has_explicit_server = bool(str(source_server or "").strip())
    if provider == "custom":
        if not has_explicit_server:
            raise SystemExit("请在 config.json 中设置 imap.server，或选择非 custom 的 email.provider")
    elif not has_explicit_server:
        imap_cfg["server"] = preset["server"]

    source_port = source_imap_cfg.get("port") if isinstance(source_imap_cfg, dict) else None
    has_explicit_port = source_port not in {None, ""}
    if not has_explicit_port:
        imap_cfg["port"] = preset["port"]

    has_explicit_ssl = isinstance(source_imap_cfg, dict) and "ssl" in source_imap_cfg
    if not has_explicit_ssl:
        imap_cfg["ssl"] = preset["ssl"]


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

    # Validate
    email_addr = cfg.get("email", {}).get("address", "")
    if not email_addr or email_addr in {"your_email@qq.com", "your_email@example.com"}:
        _log.error("请在 config.json 中设置真实的 email.address")
        raise SystemExit(1)

    imap_server = cfg.get("imap", {}).get("server", "")
    if not imap_server:
        _log.error("请在 config.json 中设置 imap.server，或选择非 custom 的 email.provider")
        raise SystemExit(1)

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
        return _normalize_config(_deep_merge(_DEFAULTS, raw), raw)
    except Exception:
        return defaults_with_presets()


def validate_config_gui(cfg: dict) -> None:
    """Validate configuration fields for GUI settings. Raises ValueError if invalid."""
    try:
        cfg = _normalize_config(_deep_merge(_DEFAULTS, cfg), cfg)
    except SystemExit as exc:
        raise ValueError(str(exc) or "邮箱配置无效。") from None

    email_cfg = cfg.get("email", {})
    email_addr = email_cfg.get("address", "")
    if not email_addr:
        raise ValueError("邮箱地址不能为空。")
    if email_addr in {"your_email@qq.com", "your_email@example.com"}:
        raise ValueError("邮箱地址不能使用默认示例值（如 your_email@qq.com / your_email@example.com），请输入真实的邮箱地址。")

    provider = email_cfg.get("provider", "qq")
    if provider not in _VALID_EMAIL_PROVIDERS:
        raise ValueError("邮箱类型必须是 qq, netease_163, netease_126, gmail, outlook 或 custom 之一。")

    imap_server = cfg.get("imap", {}).get("server", "")
    if not imap_server:
        raise ValueError("IMAP 服务器不能为空。")

    imap_port = cfg.get("imap", {}).get("port")
    try:
        port_num = int(imap_port)
    except (TypeError, ValueError):
        raise ValueError("IMAP 端口必须是有效的整数。")
    if not (1 <= port_num <= 65535):
        raise ValueError("IMAP 端口范围必须在 1 到 65535 之间。")

    months_back = cfg.get("search", {}).get("months_back")
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
