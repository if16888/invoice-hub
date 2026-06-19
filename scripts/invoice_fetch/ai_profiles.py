"""AI profile validation, legacy migration, and runtime projection."""

from __future__ import annotations

from typing import Any


VALID_AI_PROVIDERS = {"deepseek", "gemini"}

_DEFAULT_AI_MODELS = {
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash",
}

_LEGACY_PROFILE_NAMES = {
    "deepseek": "旧 DeepSeek 配置",
    "gemini": "旧 Gemini 配置",
}


def _required_string(profile: dict[str, Any], field: str, message: str) -> str:
    value = profile.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value.strip()


def validate_ai_profiles(profiles) -> list[dict[str, Any]]:
    """Validate and normalize an AI profile list."""
    if not isinstance(profiles, list):
        raise ValueError("AI 配置列表必须是数组。")

    normalized = []
    profile_ids = set()
    enabled_count = 0

    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("AI 配置项必须是对象。")

        normalized_profile = dict(profile)
        profile_id = _required_string(profile, "profile_id", "AI 配置 ID 不能为空。")
        name = _required_string(profile, "name", "AI 配置名称不能为空。")
        provider = _required_string(profile, "provider", "AI 服务提供商不能为空。").lower()
        model = _required_string(profile, "model", "AI 模型不能为空。")
        enabled = profile.get("enabled")

        if provider not in VALID_AI_PROVIDERS:
            raise ValueError(
                f"AI 服务提供商不支持: {provider}。"
                f"支持: {', '.join(sorted(VALID_AI_PROVIDERS))}。"
            )
        if not isinstance(enabled, bool):
            raise ValueError("AI 配置 enabled 必须是布尔值。")
        if profile_id in profile_ids:
            raise ValueError("AI 配置 ID 不能重复。")

        profile_ids.add(profile_id)
        enabled_count += int(enabled)
        normalized_profile.update({
            "profile_id": profile_id,
            "name": name,
            "provider": provider,
            "model": model,
            "enabled": enabled,
        })
        normalized.append(normalized_profile)

    if enabled_count > 1:
        raise ValueError("最多只能启用一个 AI 配置。")

    return normalized


def get_ai_profiles(
    cfg: dict[str, Any],
    source_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read explicit profiles or migrate the legacy top-level AI config."""
    source = source_cfg if isinstance(source_cfg, dict) else cfg
    if "ai_profiles" in source:
        return validate_ai_profiles(source["ai_profiles"])

    legacy_ai = cfg.get("ai", {})
    if not isinstance(legacy_ai, dict):
        legacy_ai = {}

    provider = str(legacy_ai.get("provider") or "none").strip().lower()
    if provider == "none":
        return []
    if provider not in VALID_AI_PROVIDERS:
        raise ValueError(
            f"AI 服务提供商不支持: {provider}。"
            f"支持: none, {', '.join(sorted(VALID_AI_PROVIDERS))}。"
        )

    model = str(legacy_ai.get("model") or _DEFAULT_AI_MODELS[provider]).strip()
    profile = {
        "profile_id": f"legacy-{provider}",
        "name": _LEGACY_PROFILE_NAMES[provider],
        "provider": provider,
        "model": model,
        "enabled": True,
    }
    if "batch_size" in legacy_ai:
        profile["batch_size"] = legacy_ai["batch_size"]
    return validate_ai_profiles([profile])


def apply_active_ai_profile(
    cfg: dict[str, Any],
    profiles,
) -> dict[str, Any]:
    """Project the active profile onto the legacy runtime AI config."""
    normalized = validate_ai_profiles(profiles)
    cfg["ai_profiles"] = normalized

    ai_cfg = cfg.get("ai")
    if not isinstance(ai_cfg, dict):
        ai_cfg = {}
        cfg["ai"] = ai_cfg
    batch_size = ai_cfg.get("batch_size", 20)
    active = next((profile for profile in normalized if profile["enabled"]), None)

    if active is None:
        ai_cfg.update({
            "provider": "none",
            "model": "",
            "profile_id": "",
            "batch_size": batch_size,
        })
        return cfg

    ai_cfg.update({
        "provider": active["provider"],
        "model": active["model"],
        "profile_id": active["profile_id"],
        "batch_size": active.get("batch_size", batch_size),
    })
    return cfg
