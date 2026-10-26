"""Credential management helpers for mailbox auth codes and AI keys."""

from __future__ import annotations

import logging

try:
    import keyring
except ImportError:
    keyring = None

from .log_privacy import mask_email

_log = logging.getLogger(__name__)

KEYRING_SERVICE = "invoice_mail_auth_code"

# The credential store is a hard dependency of the shipped builds, but the
# import is deliberately tolerant so a broken/stripped install does not fail at
# import time.  Every entry point therefore has to report a missing store
# explicitly instead of raising ``AttributeError: 'NoneType' ...``.
CREDENTIAL_STORE_UNAVAILABLE_MESSAGE = (
    "系统凭据管理器不可用（keyring 组件未安装或加载失败）。"
    "请重新安装应用；若从源码运行，请先执行 pip install -r requirements.txt。"
)


class CredentialStoreUnavailable(RuntimeError):
    """The OS credential store backend is not available on this install."""


class CredentialStoreError(RuntimeError):
    """The credential store rejected an operation.

    The message is safe to show to the user: backend messages can contain
    account or key material and are only ever logged as an exception type.
    """


def _credential_store():
    """Return the keyring module, failing with a clear message when missing."""
    if keyring is None:
        _log.error("Credential store unavailable: keyring import failed")
        raise CredentialStoreUnavailable(CREDENTIAL_STORE_UNAVAILABLE_MESSAGE)
    return keyring


def _is_password_not_found_error(exc: BaseException) -> bool:
    """Return whether a delete failure only means "nothing stored"."""
    return (
        "not found" in str(exc).lower()
        or "passworddeleteerror" in type(exc).__name__.lower()
    )


def get_auth_code(email: str) -> str:
    """Retrieve the mailbox app password/auth code for *email* from OS keyring."""
    store = _credential_store()
    try:
        secret = store.get_password(KEYRING_SERVICE, email)
    except Exception as exc:
        # Backend messages may contain account material: log the type only.
        _log.error(
            "Mailbox credential lookup failed: error_type=%s",
            type(exc).__name__,
        )
        raise CredentialStoreError(
            "无法从系统凭据管理器读取该邮箱的授权码。请在设置中重新填写授权码后重试。"
        ) from None
    if not secret:
        _log.error(
            "Missing mailbox auth code. Run:\n"
            "  cmdkey /generic:%s /user:%s /pass:<mailbox-auth-code>",
            KEYRING_SERVICE,
            mask_email(email),
        )
        raise SystemExit(1)
    _log.debug("Loaded mailbox credential (service=%s, user=%s)", KEYRING_SERVICE, mask_email(email))
    return secret


def _ai_keyring_service(provider: str, profile_id: str = "") -> str:
    provider = str(provider or "").strip().lower()
    profile_id = str(profile_id or "").strip()
    if profile_id:
        return f"invoice-hub:ai-profile:{profile_id}:{provider}"
    return f"invoice-hub:ai:{provider}"


def _get_ai_key_from_environment(provider: str) -> str:
    import os

    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = env_map.get(str(provider or "").strip().lower())
    if not env_var:
        raise ValueError(f"Unknown AI provider: {provider}")
    key = os.environ.get(env_var, "")
    if not key:
        _log.error(
            "Missing AI API key. Configure %s in the system environment.\n"
            "  $env:%s = 'your-api-key'",
            env_var,
            env_var,
        )
        raise SystemExit(1)
    return key


def _get_ai_key_from_environment_if_any(provider: str) -> str:
    import os

    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    env_var = env_map.get(str(provider or "").strip().lower())
    if not env_var:
        return ""
    return os.environ.get(env_var, "")


def _resolve_ai_api_key(provider: str, profile_id: str = "") -> tuple[str, str]:
    provider = str(provider or "").strip().lower()
    if not provider or provider == "none":
        raise ValueError("AI classification is disabled; no API key is available")

    services: list[tuple[str, str]] = []
    if profile_id:
        services.append((_ai_keyring_service(provider, profile_id), "profile"))
    services.append((_ai_keyring_service(provider), "provider"))

    for service, source in services:
        if keyring is None:
            break
        try:
            secret = keyring.get_password(service, "default")
            if secret:
                _log.debug("Loaded AI key from keyring (service=%s)", service)
                return secret, source
        except Exception as exc:
            _log.debug("AI credential lookup unavailable: error_type=%s", type(exc).__name__)
            continue

    env_key = _get_ai_key_from_environment_if_any(provider)
    if env_key:
        _log.debug("Loaded AI key from environment (provider=%s)", provider)
        return env_key, "env"

    return "", "missing"


def get_ai_api_key(provider: str, profile_id: str = "") -> str:
    """Resolve the AI API key for runtime use."""
    key, source = _resolve_ai_api_key(provider, profile_id=profile_id)
    if source == "missing":
        return _get_ai_key_from_environment(provider)
    return key


def get_ai_api_key_source(provider: str, profile_id: str = "") -> str:
    """Return the source of the resolved AI key for UI display."""
    try:
        _, source = _resolve_ai_api_key(provider, profile_id=profile_id)
    except ValueError:
        return "missing"
    return source


def has_ai_profile_api_key(provider: str, profile_id: str = "") -> bool:
    """Strictly check for a profile-scoped AI key for the exact provider."""
    if not provider or not profile_id or keyring is None:
        return False
    try:
        secret = keyring.get_password(_ai_keyring_service(provider, profile_id), "default")
        return bool(secret)
    except Exception:
        return False


def set_ai_api_key(provider: str, api_key: str, profile_id: str = "") -> None:
    """Store the AI API key in OS keyring."""
    store = _credential_store()
    service = _ai_keyring_service(provider, profile_id)
    try:
        store.set_password(service, "default", api_key)
    except Exception as exc:
        # Never log the backend message: it may echo the key or account data.
        _log.error("AI credential write failed: error_type=%s", type(exc).__name__)
        raise CredentialStoreError(
            "无法将 AI API Key 写入系统凭据管理器。请检查 Windows 凭据管理器是否可用后重试。"
        ) from None
    _log.info("Stored AI key in keyring (service=%s)", service)


def has_ai_api_key(provider: str, profile_id: str = "") -> bool:
    """Check if any usable AI API key exists for the provider/profile."""
    if not provider:
        return False
    return get_ai_api_key_source(provider, profile_id=profile_id) != "missing"


def delete_ai_api_key(provider: str, profile_id: str = "") -> None:
    """Delete the AI API key from OS keyring.

    Best-effort by contract (the UI refreshes its own state afterwards), but a
    missing credential store must not raise a bare ``AttributeError``.
    """
    if keyring is None:
        _log.warning("AI credential deletion skipped: credential store unavailable")
        return
    service = _ai_keyring_service(provider, profile_id)
    try:
        keyring.delete_password(service, "default")
        _log.info("Deleted AI key from keyring (service=%s)", service)
    except Exception as exc:
        # Do not log backend messages, which may contain account/key material.
        _log.warning("AI credential deletion failed: error_type=%s", type(exc).__name__)


def set_auth_code(email: str, auth_code: str) -> None:
    """Store the mailbox app password/auth code for *email* in OS keyring."""
    store = _credential_store()
    try:
        store.set_password(KEYRING_SERVICE, email, auth_code)
    except Exception as exc:
        _log.error("Mailbox credential write failed: error_type=%s", type(exc).__name__)
        raise CredentialStoreError(
            "无法将邮箱授权码写入系统凭据管理器。请检查 Windows 凭据管理器是否可用后重试。"
        ) from None
    _log.info("Stored mailbox credential in keyring")


def has_auth_code(email: str) -> bool:
    """Check if the mailbox app password/auth code for *email* exists in OS keyring."""
    if not email or keyring is None:
        return False
    try:
        secret = keyring.get_password(KEYRING_SERVICE, email)
        return bool(secret)
    except Exception:
        return False


def delete_auth_code(email: str) -> None:
    """Delete the mailbox app password/auth code for *email* from OS keyring.

    A missing credential store or a rejected deletion raises a sanitized
    :class:`CredentialStoreError` so the caller can tell the user the truth.
    "Nothing stored" is not an error (the desired end state already holds).
    """
    if not email:
        return
    store = _credential_store()
    try:
        store.delete_password(KEYRING_SERVICE, email)
    except Exception as exc:
        if _is_password_not_found_error(exc):
            _log.debug(
                "Mailbox credential already absent: error_type=%s",
                type(exc).__name__,
            )
            return
        # Backend messages can contain account material: log the type only.
        _log.warning(
            "Mailbox credential deletion failed: error_type=%s",
            type(exc).__name__,
        )
        raise CredentialStoreError(
            "无法从系统凭据管理器删除该邮箱授权码。"
            "请稍后重试，或在 Windows 凭据管理器中手动删除。"
        ) from None
    _log.info("Deleted mailbox credential from keyring")
