"""Safe, explicit Windows Firewall integration for mobile upload.

The mobile upload listener deliberately remains independent from this module.
Starting or stopping an upload session never changes firewall state. A packaged
user may request a narrowly scoped rule after an explicit confirmation and UAC
prompt. Source/dev runs may opt in to a current-port-only rule, but every
firewall mutation remains an explicit user action.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


FIREWALL_RULE_NAME = "Invoice Hub Mobile Upload"
DEV_FIREWALL_RULE_NAME = "Invoice Hub Mobile Upload Dev Session"
_DEVELOPMENT_EXECUTABLE_NAMES = {"python.exe", "pythonw.exe", "pytest.exe"}
_POWERSHELL = "powershell.exe"
_NETSH = "netsh.exe"
_POWERSHELL_TIMEOUT_SECONDS = 8
_ELEVATED_TIMEOUT_SECONDS = 30
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102


class FirewallState(str, Enum):
    """User-facing firewall capability/rule state."""

    SUPPORTED = "supported"
    RULE_PRESENT = "rule_present"
    RULE_MISSING = "rule_missing"
    RULE_DISABLED = "rule_disabled"
    NON_WINDOWS = "non_windows"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FirewallStatus:
    state: FirewallState
    executable_path: str = ""
    development_mode: bool = False
    reason: str = ""
    rule_name: str = FIREWALL_RULE_NAME
    enabled: bool | None = None
    direction: str = ""
    action: str = ""
    protocol: str = ""
    profile: str = ""
    program: str = ""
    local_port: str = ""

    @property
    def is_allowed(self) -> bool:
        return self.state is FirewallState.RULE_PRESENT

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "executable_path": self.executable_path,
            "development_mode": self.development_mode,
            "reason": self.reason,
            "rule_name": self.rule_name,
            "enabled": self.enabled,
            "direction": self.direction,
            "action": self.action,
            "protocol": self.protocol,
            "profile": self.profile,
            "program": self.program,
            "local_port": self.local_port,
            "is_allowed": self.is_allowed,
        }


@dataclass(frozen=True)
class FirewallActionResult:
    success: bool
    status: FirewallStatus
    message: str = ""
    uac_requested: bool = False


def is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_invoicehub_executable(path: Path | str | None) -> bool:
    if path is None:
        return False
    return Path(path).name.casefold() == "invoicehub.exe"


def get_current_invoicehub_executable() -> Path | None:
    """Return the formal packaged executable, never ``python.exe``/pytest."""
    if not is_windows() or not bool(getattr(sys, "frozen", False)):
        return None
    candidate = Path(sys.executable)
    if not _is_invoicehub_executable(candidate):
        return None
    return candidate.resolve(strict=False)


def get_current_development_executable() -> Path | None:
    """Return the interpreter eligible for a current-port-only dev rule."""
    if not is_windows():
        return None
    candidate = Path(sys.executable)
    if candidate.name.casefold() not in _DEVELOPMENT_EXECUTABLE_NAMES:
        return None
    return candidate.resolve(strict=False)


def _path_key(value: object) -> str:
    text = os.path.expandvars(str(value or "")).strip().strip('"')
    if not text:
        return ""
    try:
        text = str(Path(text).resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        text = os.path.abspath(text)
    return text.casefold()


def _as_text(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    return str(value or "").strip()


def _is_enabled(value: object) -> bool:
    return str(value or "").strip().casefold() in {"true", "yes", "enabled", "1"}


def _is_private_only_profile(value: object) -> bool:
    profile = _as_text(value).replace(" ", "").casefold()
    return profile in {"private", "2"}


def _is_tcp(value: object) -> bool:
    return _as_text(value).casefold() in {"tcp", "6"}


def _is_inbound(value: object) -> bool:
    return _as_text(value).casefold() in {"inbound", "1"}


def _is_allow(value: object) -> bool:
    return _as_text(value).casefold() in {"allow", "2"}


def _is_any_local_port(value: object) -> bool:
    """Accept only the exact any-port value used by the packaged contract."""
    return _as_text(value).replace(" ", "").casefold() == "any"


def _programs(value: object) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        values: Iterable[object] = value
    else:
        values = str(value or "").replace("\r", "\n").replace(";", "\n").split("\n")
    return {_path_key(item) for item in values if _path_key(item)}


def _query_environment(rule_name: str = FIREWALL_RULE_NAME) -> dict[str, str]:
    return {
        **os.environ,
        "INVOICE_HUB_FIREWALL_RULE_NAME": rule_name,
    }


_QUERY_SCRIPT = r"""
$ruleName = $env:INVOICE_HUB_FIREWALL_RULE_NAME
$rules = @(Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)
$result = foreach ($rule in $rules) {
    $application = @(Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue)
    $port = @(Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule -ErrorAction SilentlyContinue)
    [PSCustomObject]@{
        DisplayName = [string]$rule.DisplayName
        Enabled = [string]$rule.Enabled
        Direction = [string]$rule.Direction
        Action = [string]$rule.Action
        Profile = [string]$rule.Profile
        Program = @($application.Program) -join ';'
        Protocol = @($port.Protocol) -join ';'
        LocalPort = @($port.LocalPort) -join ';'
    }
}
if ($null -eq $result) { '[]' } else { @($result) | ConvertTo-Json -Compress }
"""


def _query_firewall_rules(rule_name: str = FIREWALL_RULE_NAME) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [
            _POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _QUERY_SCRIPT,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_POWERSHELL_TIMEOUT_SECONDS,
        env=_query_environment(rule_name),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PowerShell exited with code {completed.returncode}")
    raw = (completed.stdout or "").strip()
    if not raw:
        return []
    payload = json.loads(raw)
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _status_from_rule(
    rule: dict[str, Any],
    executable: Path,
    state: FirewallState = FirewallState.RULE_PRESENT,
    *,
    development_mode: bool = False,
    reason: str = "",
    rule_name: str = FIREWALL_RULE_NAME,
) -> FirewallStatus:
    return FirewallStatus(
        state=state,
        executable_path=str(executable),
        development_mode=development_mode,
        reason=reason,
        rule_name=rule_name,
        enabled=_is_enabled(rule.get("Enabled")),
        direction=_as_text(rule.get("Direction")),
        action=_as_text(rule.get("Action")),
        protocol=_as_text(rule.get("Protocol")),
        profile=_as_text(rule.get("Profile")),
        program=_as_text(rule.get("Program")),
        local_port=_as_text(rule.get("LocalPort")),
    )


def get_mobile_upload_firewall_status(
    executable_path: Path | str | None = None,
) -> FirewallStatus:
    """Inspect only the stable Invoice Hub mobile-upload rule."""
    if not is_windows():
        return FirewallStatus(FirewallState.NON_WINDOWS)

    executable = Path(executable_path) if executable_path is not None else get_current_invoicehub_executable()
    if executable is None or not _is_invoicehub_executable(executable):
        return FirewallStatus(
            FirewallState.SUPPORTED,
            development_mode=True,
            reason="development executable; persistent firewall authorization is disabled",
        )

    executable = executable.resolve(strict=False)
    try:
        rules = _query_firewall_rules()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return FirewallStatus(
            FirewallState.UNKNOWN,
            executable_path=str(executable),
            reason=f"firewall query unavailable: {type(exc).__name__}",
        )

    executable_key = _path_key(executable)
    disabled_current_executable_rule: dict[str, Any] | None = None
    for rule in rules:
        programs = _programs(rule.get("Program"))
        if programs != {executable_key}:
            continue
        if not _is_enabled(rule.get("Enabled")):
            if disabled_current_executable_rule is None:
                disabled_current_executable_rule = rule
            continue
        if (
            _is_inbound(rule.get("Direction"))
            and _is_allow(rule.get("Action"))
            and _is_tcp(rule.get("Protocol"))
            and _is_private_only_profile(rule.get("Profile"))
            and _is_any_local_port(rule.get("LocalPort"))
        ):
            return _status_from_rule(rule, executable)

    if disabled_current_executable_rule is not None:
        return _status_from_rule(
            disabled_current_executable_rule,
            executable,
            FirewallState.RULE_DISABLED,
        )

    return FirewallStatus(
        FirewallState.RULE_MISSING,
        executable_path=str(executable),
        reason="no enabled private inbound TCP any-port rule targets the current executable",
    )


def build_firewall_add_rule_args(executable_path: Path | str) -> list[str]:
    executable = Path(executable_path).resolve(strict=False)
    return [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={FIREWALL_RULE_NAME}",
        "dir=in",
        "action=allow",
        f"program={executable}",
        "enable=yes",
        "profile=Private",
        "protocol=TCP",
        "localport=Any",
    ]


def _development_executable_path(executable_path: Path | str | None) -> Path | None:
    if executable_path is None:
        return get_current_development_executable()
    executable = Path(executable_path).resolve(strict=False)
    if executable.name.casefold() not in _DEVELOPMENT_EXECUTABLE_NAMES:
        return None
    return executable


def _validated_mobile_port(port: int | str | None) -> int | None:
    try:
        value = int(port)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 65535 else None


def build_development_firewall_add_rule_args(
    executable_path: Path | str,
    port: int,
) -> list[str]:
    executable = _development_executable_path(executable_path)
    validated_port = _validated_mobile_port(port)
    if executable is None:
        raise ValueError("development firewall rules require python.exe/pythonw.exe/pytest.exe")
    if validated_port is None:
        raise ValueError("mobile upload port must be between 1 and 65535")
    return [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={DEV_FIREWALL_RULE_NAME}",
        "dir=in",
        "action=allow",
        f"program={executable}",
        "enable=yes",
        "profile=Private",
        "protocol=TCP",
        f"localport={validated_port}",
    ]


def build_development_firewall_delete_rule_args() -> list[str]:
    return [
        "advfirewall",
        "firewall",
        "delete",
        "rule",
        f"name={DEV_FIREWALL_RULE_NAME}",
    ]


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_wchar_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _run_elevated_netsh_args(args: list[str]) -> tuple[bool, str]:
    if not is_windows():
        return False, "non-Windows platform"
    try:
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        arguments = subprocess.list2cmdline(args)
        info = _ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = _SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = _NETSH
        info.lpParameters = arguments
        info.nShow = 1
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error_code = ctypes.get_last_error()
            return False, f"UAC rejected or ShellExecuteExW failed ({error_code})"
        wait_result = kernel32.WaitForSingleObject(
            info.hProcess,
            int(_ELEVATED_TIMEOUT_SECONDS * 1000),
        )
        if wait_result == _WAIT_TIMEOUT:
            kernel32.CloseHandle(info.hProcess)
            return False, "firewall command timed out"
        if wait_result != _WAIT_OBJECT_0:
            kernel32.CloseHandle(info.hProcess)
            return False, "firewall command wait failed"
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            kernel32.CloseHandle(info.hProcess)
            return False, "firewall command exit status unavailable"
        kernel32.CloseHandle(info.hProcess)
        if int(exit_code.value) != 0:
            return False, f"netsh exited with code {int(exit_code.value)}"
        return True, ""
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        return False, f"{type(exc).__name__}"


def _run_elevated_netsh(executable_path: Path) -> tuple[bool, str]:
    return _run_elevated_netsh_args(build_firewall_add_rule_args(executable_path))


def _development_status(
    state: FirewallState,
    executable: Path | None = None,
    *,
    enabled: bool | None = None,
    reason: str = "",
    local_port: str = "",
) -> FirewallStatus:
    return FirewallStatus(
        state=state,
        executable_path=str(executable) if executable is not None else "",
        development_mode=True,
        reason=reason,
        rule_name=DEV_FIREWALL_RULE_NAME,
        enabled=enabled,
        local_port=local_port,
    )


def _is_owned_development_rule(rule: dict[str, Any]) -> bool:
    if _as_text(rule.get("DisplayName")) != DEV_FIREWALL_RULE_NAME:
        return False
    programs = _programs(rule.get("Program"))
    if not programs:
        return False
    return all(Path(program).name.casefold() in _DEVELOPMENT_EXECUTABLE_NAMES for program in programs)


def _is_valid_development_rule(rule: dict[str, Any], executable: Path) -> bool:
    port = _validated_mobile_port(_as_text(rule.get("LocalPort")))
    return (
        _is_owned_development_rule(rule)
        and _programs(rule.get("Program")) == {_path_key(executable)}
        and _is_enabled(rule.get("Enabled"))
        and _is_inbound(rule.get("Direction"))
        and _is_allow(rule.get("Action"))
        and _is_tcp(rule.get("Protocol"))
        and _is_private_only_profile(rule.get("Profile"))
        and port is not None
    )


def get_mobile_upload_dev_firewall_status(
    executable_path: Path | str | None = None,
    current_port: int | str | None = None,
) -> FirewallStatus:
    """Read development-rule state without mutating Windows Firewall.

    Any Invoice Hub-owned development marker remains visible even when it was
    created by another Python path or a previous random port. That prevents a
    new rule from being stacked on top of stale state without explicit cleanup.
    """
    if not is_windows():
        return _development_status(FirewallState.NON_WINDOWS)
    executable = _development_executable_path(executable_path)
    if executable is None:
        return _development_status(
            FirewallState.SUPPORTED,
            reason="current process is not a supported development executable",
        )
    try:
        rules = _query_firewall_rules(DEV_FIREWALL_RULE_NAME)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return _development_status(
            FirewallState.UNKNOWN,
            executable,
            reason=f"development firewall query unavailable: {type(exc).__name__}",
        )

    marker_rules = [
        rule for rule in rules
        if _as_text(rule.get("DisplayName")) == DEV_FIREWALL_RULE_NAME
    ]
    if not marker_rules:
        return _development_status(FirewallState.RULE_MISSING, executable)
    if not all(_is_owned_development_rule(rule) for rule in marker_rules):
        return _development_status(
            FirewallState.UNKNOWN,
            executable,
            reason="marker rule contains an unrelated program",
        )

    executable_key = _path_key(executable)
    current_rules = [
        rule for rule in marker_rules
        if _programs(rule.get("Program")) == {executable_key}
    ]
    if not current_rules:
        stale = marker_rules[0]
        return _status_from_rule(
            stale,
            executable,
            FirewallState.RULE_PRESENT,
            development_mode=True,
            reason="stale development executable",
            rule_name=DEV_FIREWALL_RULE_NAME,
        )

    disabled_rule: dict[str, Any] | None = None
    for rule in current_rules:
        if not _is_enabled(rule.get("Enabled")):
            disabled_rule = disabled_rule or rule
            continue
        if _is_valid_development_rule(rule, executable):
            local_port = _as_text(rule.get("LocalPort"))
            requested_port = _validated_mobile_port(current_port)
            stale = requested_port is not None and local_port != str(requested_port)
            return _status_from_rule(
                rule,
                executable,
                development_mode=True,
                reason="stale development session port" if stale else "",
                rule_name=DEV_FIREWALL_RULE_NAME,
            )

    if disabled_rule is not None:
        return _status_from_rule(
            disabled_rule,
            executable,
            FirewallState.RULE_DISABLED,
            development_mode=True,
            reason="development rule is disabled",
            rule_name=DEV_FIREWALL_RULE_NAME,
        )
    return _development_status(
        FirewallState.UNKNOWN,
        executable,
        reason="development marker rule does not match the Private/TCP/current-executable contract",
    )


def clear_mobile_upload_dev_firewall_access(
    executable_path: Path | str | None = None,
) -> FirewallActionResult:
    """Explicitly delete only Invoice Hub-owned development marker rules."""
    if not is_windows():
        return FirewallActionResult(
            True,
            _development_status(FirewallState.NON_WINDOWS),
            "非 Windows，无需清理开发测试规则。",
        )

    executable = _development_executable_path(executable_path)
    if executable is None:
        return FirewallActionResult(
            False,
            _development_status(
                FirewallState.UNKNOWN,
                reason="current process is not a supported development executable",
            ),
            "无法安全识别当前开发解释器，未清理防火墙规则。",
        )

    try:
        rules = _query_firewall_rules(DEV_FIREWALL_RULE_NAME)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return FirewallActionResult(
            False,
            _development_status(
                FirewallState.UNKNOWN,
                executable,
                reason=f"development firewall cleanup query unavailable: {type(exc).__name__}",
            ),
            f"无法确认开发测试规则归属，未清理：{type(exc).__name__}",
        )

    marker_rules = [
        rule for rule in rules
        if _as_text(rule.get("DisplayName")) == DEV_FIREWALL_RULE_NAME
    ]
    if not marker_rules:
        return FirewallActionResult(
            True,
            _development_status(FirewallState.RULE_MISSING, executable),
            "无遗留开发测试规则。",
        )
    if not all(_is_owned_development_rule(rule) for rule in marker_rules):
        return FirewallActionResult(
            False,
            _development_status(
                FirewallState.UNKNOWN,
                executable,
                reason="marker rule contains an unrelated program",
            ),
            "发现同名但无法确认由 Invoice Hub 开发测试创建的规则，未执行删除。",
        )

    success, reason = _run_elevated_netsh_args(build_development_firewall_delete_rule_args())
    if not success:
        return FirewallActionResult(
            False,
            _development_status(FirewallState.RULE_PRESENT, executable, reason=reason),
            f"开发测试规则未清理：{reason or 'UAC 未完成'}",
            uac_requested=True,
        )
    try:
        remaining = _query_firewall_rules(DEV_FIREWALL_RULE_NAME)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return FirewallActionResult(
            False,
            _development_status(
                FirewallState.UNKNOWN,
                executable,
                reason=f"cleanup verification unavailable: {type(exc).__name__}",
            ),
            f"开发测试规则删除后无法复核：{type(exc).__name__}",
            uac_requested=True,
        )
    if any(_as_text(rule.get("DisplayName")) == DEV_FIREWALL_RULE_NAME for rule in remaining):
        return FirewallActionResult(
            False,
            _development_status(
                FirewallState.RULE_PRESENT,
                executable,
                reason="marker rule remains after delete",
            ),
            "开发测试规则仍然存在，未将清理标记为成功。",
            uac_requested=True,
        )
    return FirewallActionResult(
        True,
        _development_status(FirewallState.RULE_MISSING, executable),
        "开发测试规则已清理。",
        uac_requested=True,
    )


def request_mobile_upload_dev_firewall_access(
    executable_path: Path | str | None,
    port: int,
) -> FirewallActionResult:
    """Explicitly create a Private/TCP rule for the current dev port only."""
    if not is_windows():
        return FirewallActionResult(
            False,
            _development_status(FirewallState.NON_WINDOWS),
            "Windows 防火墙集成仅支持 Windows。",
        )
    executable = _development_executable_path(executable_path)
    validated_port = _validated_mobile_port(port)
    if executable is None or validated_port is None:
        return FirewallActionResult(
            False,
            _development_status(
                FirewallState.SUPPORTED,
                executable,
                reason="development executable and one valid mobile port are required",
            ),
            "仅允许对当前开发解释器和当前手机上传端口授权。",
        )

    existing = get_mobile_upload_dev_firewall_status(executable, validated_port)
    if existing.state is FirewallState.RULE_PRESENT:
        if not existing.reason and existing.local_port == str(validated_port):
            return FirewallActionResult(
                True,
                existing,
                f"本次开发测试已允许 · Private · TCP {validated_port}",
                uac_requested=False,
            )
        return FirewallActionResult(
            False,
            existing,
            "检测到旧开发测试授权，请先显式清理后再允许当前端口。",
            uac_requested=False,
        )
    if existing.state is FirewallState.RULE_DISABLED:
        return FirewallActionResult(
            False,
            existing,
            "检测到已禁用的开发测试授权，请先显式清理后再允许当前端口。",
            uac_requested=False,
        )
    if existing.state is FirewallState.UNKNOWN:
        return FirewallActionResult(
            False,
            existing,
            "无法安全确认现有开发测试授权，请先检查或显式清理。",
            uac_requested=False,
        )

    success, reason = _run_elevated_netsh_args(
        build_development_firewall_add_rule_args(executable, validated_port)
    )
    if not success:
        return FirewallActionResult(
            False,
            _development_status(FirewallState.RULE_MISSING, executable, reason=reason),
            f"开发测试规则未创建：{reason or 'UAC 未完成'}",
            uac_requested=True,
        )

    status = get_mobile_upload_dev_firewall_status(executable, validated_port)
    if (
        status.state is not FirewallState.RULE_PRESENT
        or status.reason
        or status.local_port != str(validated_port)
    ):
        return FirewallActionResult(
            False,
            status,
            "开发测试规则创建后未通过当前端口复核。",
            uac_requested=True,
        )
    return FirewallActionResult(
        True,
        status,
        f"本次开发测试已允许 · Private · TCP {validated_port}",
        uac_requested=True,
    )


def request_mobile_upload_firewall_access(
    executable_path: Path | str | None = None,
) -> FirewallActionResult:
    if not is_windows():
        status = FirewallStatus(FirewallState.NON_WINDOWS)
        return FirewallActionResult(False, status, "Windows 防火墙集成仅支持 Windows。")

    executable = Path(executable_path) if executable_path is not None else get_current_invoicehub_executable()
    if executable is None or not _is_invoicehub_executable(executable):
        status = FirewallStatus(
            FirewallState.SUPPORTED,
            development_mode=True,
            reason="development executable; persistent firewall authorization is disabled",
        )
        return FirewallActionResult(False, status, "开发运行模式不会自动创建持久防火墙规则。")
    executable = executable.resolve(strict=False)
    if not executable.is_file():
        status = FirewallStatus(
            FirewallState.UNKNOWN,
            executable_path=str(executable),
            reason="packaged executable is not present",
        )
        return FirewallActionResult(False, status, "未找到正式 InvoiceHub.exe，未请求防火墙授权。")

    success, reason = _run_elevated_netsh(executable)
    status = get_mobile_upload_firewall_status(executable)
    if success and status.state is FirewallState.RULE_PRESENT:
        return FirewallActionResult(True, status, "已允许手机访问 · 仅私人网络", uac_requested=True)
    message = "未授权"
    if reason:
        message = f"未授权：{reason}"
    return FirewallActionResult(False, status, message, uac_requested=True)


__all__ = [
    "DEV_FIREWALL_RULE_NAME",
    "FIREWALL_RULE_NAME",
    "FirewallActionResult",
    "FirewallState",
    "FirewallStatus",
    "build_firewall_add_rule_args",
    "build_development_firewall_add_rule_args",
    "build_development_firewall_delete_rule_args",
    "clear_mobile_upload_dev_firewall_access",
    "get_current_development_executable",
    "get_current_invoicehub_executable",
    "get_mobile_upload_dev_firewall_status",
    "get_mobile_upload_firewall_status",
    "is_windows",
    "request_mobile_upload_dev_firewall_access",
    "request_mobile_upload_firewall_access",
]
