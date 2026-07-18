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


def get_auth_code(email: str) -> str:
    """Retrieve the mailbox app password/auth code for *email* from OS keyring."""
    secret = keyring.get_password(KEYRING_SERVICE, email)
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
        try:
            secret = keyring.get_password(service, "default")
            if secret:
                _log.debug("Loaded AI key from keyring (service=%s)", service)
                return secret, source
        except Exception:
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
    if not provider or not profile_id:
        return False
    try:
        secret = keyring.get_password(_ai_keyring_service(provider, profile_id), "default")
        return bool(secret)
    except Exception:
        return False


def set_ai_api_key(provider: str, api_key: str, profile_id: str = "") -> None:
    """Store the AI API key in OS keyring."""
    service = _ai_keyring_service(provider, profile_id)
    keyring.set_password(service, "default", api_key)
    _log.info("Stored AI key in keyring (service=%s)", service)


def has_ai_api_key(provider: str, profile_id: str = "") -> bool:
    """Check if any usable AI API key exists for the provider/profile."""
    if not provider:
        return False
    return get_ai_api_key_source(provider, profile_id=profile_id) != "missing"


def delete_ai_api_key(provider: str, profile_id: str = "") -> None:
    """Delete the AI API key from OS keyring."""
    service = _ai_keyring_service(provider, profile_id)
    try:
        keyring.delete_password(service, "default")
        _log.info("Deleted AI key from keyring (service=%s)", service)
    except Exception:
        pass


def set_auth_code(email: str, auth_code: str) -> None:
    """Store the mailbox app password/auth code for *email* in OS keyring."""
    keyring.set_password(KEYRING_SERVICE, email, auth_code)
    _log.info("Stored mailbox credential in keyring")


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
    """Delete the mailbox app password/auth code for *email* from OS keyring."""
    if not email:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, email)
        _log.info("Deleted mailbox credential from keyring")
    except Exception as e:
        err_msg = str(e)
        if "not found" in err_msg.lower() or "passworddeleteerror" in type(e).__name__.lower():
            pass
        else:
            _log.warning("Failed to remove mailbox credential: %s", err_msg)
