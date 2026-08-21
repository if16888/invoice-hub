"""Safe, explicit Windows Firewall integration for mobile upload.

The mobile upload listener deliberately remains independent from this module.
Starting an upload session never changes firewall state.  A packaged user may
request a narrowly scoped rule after an explicit confirmation and UAC prompt.
Source/dev runs are intentionally read-only so tests and developer builds do
not leave persistent Windows Firewall rules behind.
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


def _programs(value: object) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        values: Iterable[object] = value
    else:
        values = str(value or "").replace("\r", "\n").replace(";", "\n").split("\n")
    return {_path_key(item) for item in values if _path_key(item)}


def _query_environment() -> dict[str, str]:
    # Values travel through the process environment rather than being
    # interpolated into PowerShell source.  This keeps paths with spaces and
    # shell metacharacters data, not executable command text.
    return {
        **os.environ,
        "INVOICE_HUB_FIREWALL_RULE_NAME": FIREWALL_RULE_NAME,
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


def _query_firewall_rules() -> list[dict[str, Any]]:
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
        env=_query_environment(),
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


def _status_from_rule(rule: dict[str, Any], executable: Path) -> FirewallStatus:
    return FirewallStatus(
        state=FirewallState.RULE_PRESENT,
        executable_path=str(executable),
        enabled=_is_enabled(rule.get("Enabled")),
        direction=_as_text(rule.get("Direction")),
        action=_as_text(rule.get("Action")),
        protocol=_as_text(rule.get("Protocol")),
        profile=_as_text(rule.get("Profile")),
        program=_as_text(rule.get("Program")),
    )


def get_mobile_upload_firewall_status(
    executable_path: Path | str | None = None,
) -> FirewallStatus:
    """Inspect only the stable Invoice Hub mobile-upload rule.

    ``executable_path`` is optional so source/dev builds can be represented in
    the UI without ever querying or mutating a developer machine's firewall.
    """
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
    for rule in rules:
        programs = _programs(rule.get("Program"))
        # The application filter must be exactly the current packaged
        # executable.  A rule that also targets another program is broader
        # than the consent text and is not accepted.
        if programs != {executable_key}:
            continue
        if not _is_enabled(rule.get("Enabled")):
            return FirewallStatus(
                FirewallState.RULE_DISABLED,
                executable_path=str(executable),
                enabled=False,
                direction=_as_text(rule.get("Direction")),
                action=_as_text(rule.get("Action")),
                protocol=_as_text(rule.get("Protocol")),
                profile=_as_text(rule.get("Profile")),
                program=_as_text(rule.get("Program")),
            )
        if (
            _is_inbound(rule.get("Direction"))
            and _is_allow(rule.get("Action"))
            and _is_tcp(rule.get("Protocol"))
            and _is_private_only_profile(rule.get("Profile"))
        ):
            return _status_from_rule(rule, executable)

    return FirewallStatus(
        FirewallState.RULE_MISSING,
        executable_path=str(executable),
        reason="no enabled private inbound TCP rule targets the current executable",
    )


def build_firewall_add_rule_args(executable_path: Path | str) -> list[str]:
    """Build the exact netsh argument vector used after UAC confirmation."""
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
        # The listener deliberately uses a random port.  The rule is therefore
        # program-scoped, Private-only, and never a Program=Any global rule.
        "localport=Any",
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
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _run_elevated_netsh(executable_path: Path) -> tuple[bool, str]:
    """Run netsh through ShellExecuteExW so Windows presents a UAC prompt."""
    if not is_windows():
        return False, "non-Windows platform"
    try:
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        arguments = subprocess.list2cmdline(build_firewall_add_rule_args(executable_path))
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


def request_mobile_upload_firewall_access(
    executable_path: Path | str | None = None,
) -> FirewallActionResult:
    """Request a Private-only program-scoped rule after the caller's UAC UX."""
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
    "FIREWALL_RULE_NAME",
    "FirewallActionResult",
    "FirewallState",
    "FirewallStatus",
    "build_firewall_add_rule_args",
    "get_current_invoicehub_executable",
    "get_mobile_upload_firewall_status",
    "is_windows",
    "request_mobile_upload_firewall_access",
]
