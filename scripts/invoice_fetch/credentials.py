"""Credential management — reads mailbox app password/auth code from OS keyring.

The credential must be pre-stored via, for example:
    cmdkey /generic:invoice_mail_auth_code /user:your_email@example.com /pass:<app-password-or-auth-code>

This module NEVER logs, prints, or returns any part of the credential
beyond a boolean "loaded" / "not found" status.
"""

import logging

import keyring

from .log_privacy import mask_email

_log = logging.getLogger(__name__)

KEYRING_SERVICE = "invoice_mail_auth_code"


def get_auth_code(email: str) -> str:
    """Retrieve the mailbox app password/auth code for *email* from OS keyring.

    Raises ``SystemExit`` if the credential is not found.
    """
    secret = keyring.get_password(KEYRING_SERVICE, email)
    if not secret:
        _log.error(
            "未找到邮箱授权码/应用密码。请先运行:\n"
            "  cmdkey /generic:%s /user:%s /pass:<邮箱授权码或应用密码>",
            KEYRING_SERVICE,
            mask_email(email),
        )
        raise SystemExit(1)
    _log.debug("凭据已加载 (service=%s, user=%s)", KEYRING_SERVICE, mask_email(email))
    return secret


def get_ai_api_key(provider: str) -> str:
    """Retrieve the AI API key for *provider* from OS keyring or env fallback."""
    if not provider or provider.lower() in {"", "none"}:
        raise ValueError("AI 分类未启用，无法获取 API Key")

    service = f"invoice-hub:ai:{provider}"
    try:
        secret = keyring.get_password(service, "default")
        if secret:
            _log.debug("AI API key 已从系统 Keyring 加载 (provider=%s)", provider)
            return secret
    except Exception:
        pass

    # Fallback to environment variable
    import os
    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = env_map.get(provider)
    if not env_var:
        raise ValueError(f"未知 AI 提供商: {provider}")
    key = os.environ.get(env_var, "")
    if not key:
        _log.error(
            "未找到 AI API 密匙。请在系统设置中配置，或者设置环境变量 %s。请运行:\n"
            "  $env:%s = 'your-api-key'",
            env_var, env_var,
        )
        raise SystemExit(1)
    _log.debug("AI API key 已从环境变量加载 (provider=%s)", provider)
    return key


def set_ai_api_key(provider: str, api_key: str) -> None:
    """Store the AI API key for *provider* in OS keyring."""
    service = f"invoice-hub:ai:{provider}"
    keyring.set_password(service, "default", api_key)
    _log.info("AI API 凭据已安全更新到系统 Keyring Store (provider=%s)", provider)


def has_ai_api_key(provider: str) -> bool:
    """Check if the AI API key for *provider* exists in OS keyring."""
    if not provider:
        return False
    service = f"invoice-hub:ai:{provider}"
    try:
        secret = keyring.get_password(service, "default")
        return bool(secret)
    except Exception:
        return False


def delete_ai_api_key(provider: str) -> None:
    """Delete the AI API key for *provider* from OS keyring."""
    service = f"invoice-hub:ai:{provider}"
    try:
        keyring.delete_password(service, "default")
        _log.info("AI API 凭据已从系统 Keyring Store 中删除 (provider=%s)", provider)
    except Exception:
        pass


def set_auth_code(email: str, auth_code: str) -> None:
    """Store the mailbox app password/auth code for *email* in OS keyring."""
    keyring.set_password(KEYRING_SERVICE, email, auth_code)
    _log.info("邮箱凭据已安全更新到系统 Keyring Store")


def has_auth_code(email: str) -> bool:
    """Check if the mailbox app password/auth code for *email* exists in OS keyring."""
    if not email:
        return False
    try:
        secret = keyring.get_password(KEYRING_SERVICE, email)
        return bool(secret)
    except Exception:
        return False


def delete_auth_code(email: str) -> None:
    """Delete the mailbox app password/auth code for *email* from OS keyring.

    This operation is idempotent and does not raise errors if the credential does not exist.
    """
    if not email:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, email)
        _log.info("邮箱凭据已从系统 Keyring Store 中删除")
    except Exception as e:
        err_msg = str(e)
        if "not found" in err_msg.lower() or "passworddeleteerror" in type(e).__name__.lower():
            pass
        else:
            _log.warning("从凭据管理器移除邮箱凭证失败: %s", err_msg)
