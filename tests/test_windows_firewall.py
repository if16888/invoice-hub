import base64
import ctypes
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.invoice_fetch.windows_firewall as firewall
from scripts.invoice_fetch.windows_firewall import (
    DEV_FIREWALL_RULE_NAME,
    FIREWALL_RULE_NAME,
    FirewallState,
    build_development_firewall_add_rule_args,
    build_development_firewall_delete_rule_args,
    build_firewall_add_rule_args,
    clear_mobile_upload_dev_firewall_access,
    get_mobile_upload_dev_firewall_status,
    get_mobile_upload_firewall_status,
    request_mobile_upload_dev_firewall_access,
    request_mobile_upload_firewall_access,
)


def _rule(
    program: str,
    *,
    enabled: str = "True",
    direction: str = "Inbound",
    action: str = "Allow",
    protocol: str = "TCP",
    profile: str = "Private",
    local_port: str = "Any",
) -> dict[str, str]:
    return {
        "DisplayName": FIREWALL_RULE_NAME,
        "Enabled": enabled,
        "Direction": direction,
        "Action": action,
        "Profile": profile,
        "Program": program,
        "Protocol": protocol,
        "LocalPort": local_port,
    }


def _dev_rule(program: str, port: str = "43210", *, enabled: str = "True") -> dict[str, str]:
    return {
        "DisplayName": DEV_FIREWALL_RULE_NAME,
        "Enabled": enabled,
        "Direction": "Inbound",
        "Action": "Allow",
        "Profile": "Private",
        "Program": program,
        "Protocol": "TCP",
        "LocalPort": port,
    }


class WindowsFirewallContractTests(unittest.TestCase):
    def make_executable(self, td: str, name: str = "InvoiceHub.exe") -> Path:
        path = Path(td) / "Invoice Hub" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic executable")
        return path

    def status_for(self, executable: Path, rules: list[dict[str, str]]):
        with patch(
            "scripts.invoice_fetch.windows_firewall.is_windows",
            return_value=True,
        ), patch(
            "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
            return_value=rules,
        ):
            return get_mobile_upload_firewall_status(executable)

    def dev_status_for(
        self,
        executable: Path,
        rules: list[dict[str, str]],
        current_port: int | None = 43210,
    ):
        with patch(
            "scripts.invoice_fetch.windows_firewall.is_windows",
            return_value=True,
        ), patch(
            "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
            return_value=rules,
        ):
            return get_mobile_upload_dev_firewall_status(executable, current_port)

    def test_private_inbound_tcp_current_executable_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            status = self.status_for(executable, [_rule(str(executable))])
            self.assertEqual(status.state, FirewallState.RULE_PRESENT)
            self.assertTrue(status.is_allowed)
            self.assertEqual(status.as_dict()["profile"], "Private")

    def test_public_or_any_profile_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            for profile in ("Public", "Any", "All", "Domain, Private"):
                with self.subTest(profile=profile):
                    status = self.status_for(executable, [_rule(str(executable), profile=profile)])
                    self.assertEqual(status.state, FirewallState.RULE_MISSING)
                    self.assertFalse(status.is_allowed)

    def test_single_port_rule_is_not_present(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            status = self.status_for(
                executable,
                [_rule(str(executable), local_port="56475")],
            )
            self.assertEqual(status.state, FirewallState.RULE_MISSING)
            self.assertFalse(status.is_allowed)

    def test_old_single_port_rule_and_new_any_rule_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            status = self.status_for(
                executable,
                [
                    _rule(str(executable), local_port="56475"),
                    _rule(str(executable), local_port="Any"),
                ],
            )
            self.assertEqual(status.state, FirewallState.RULE_PRESENT)

    def test_disabled_rule_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            status = self.status_for(executable, [_rule(str(executable), enabled="False")])
            self.assertEqual(status.state, FirewallState.RULE_DISABLED)
            self.assertFalse(status.is_allowed)

    def test_disabled_rule_before_enabled_valid_rule_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            status = self.status_for(
                executable,
                [
                    _rule(str(executable), enabled="False"),
                    _rule(str(executable), enabled="True", local_port="Any"),
                ],
            )
            self.assertEqual(status.state, FirewallState.RULE_PRESENT)

    def test_enabled_valid_rule_before_disabled_rule_is_present(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            status = self.status_for(
                executable,
                [
                    _rule(str(executable), enabled="True", local_port="Any"),
                    _rule(str(executable), enabled="False"),
                ],
            )
            self.assertEqual(status.state, FirewallState.RULE_PRESENT)

    def test_stale_or_wrong_program_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            stale = self.make_executable(td, "OldInvoiceHub.exe")
            wrong = self.make_executable(td, "Other.exe")
            for program in (str(stale), str(wrong), "Any", f"{executable};{wrong}"):
                with self.subTest(program=program):
                    status = self.status_for(executable, [_rule(program)])
                    self.assertEqual(status.state, FirewallState.RULE_MISSING)

    def test_wrong_direction_action_or_protocol_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            for overrides in (
                {"direction": "Outbound"},
                {"action": "Block"},
                {"protocol": "UDP"},
            ):
                with self.subTest(overrides=overrides):
                    status = self.status_for(executable, [_rule(str(executable), **overrides)])
                    self.assertEqual(status.state, FirewallState.RULE_MISSING)

    def test_rule_command_is_private_tcp_program_scoped_and_space_safe(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            args = build_firewall_add_rule_args(executable)
            self.assertIn(f"name={FIREWALL_RULE_NAME}", args)
            self.assertIn(f"program={executable.resolve()}", args)
            self.assertIn("profile=Private", args)
            self.assertIn("protocol=TCP", args)
            self.assertIn("localport=Any", args)
            self.assertNotIn("program=Any", args)
            self.assertNotIn("profile=Any", args)
            self.assertNotIn("profile=Public", args)

    def test_source_or_dev_mode_never_requests_persistent_rule(self):
        with patch(
            "scripts.invoice_fetch.windows_firewall.is_windows",
            return_value=True,
        ), patch(
            "scripts.invoice_fetch.windows_firewall._run_elevated_netsh",
        ) as run_elevated:
            for name in ("python.exe", "pythonw.exe", "pytest.exe"):
                with self.subTest(name=name):
                    result = request_mobile_upload_firewall_access(Path(name))
                    self.assertFalse(result.success)
                    self.assertEqual(result.status.state, FirewallState.SUPPORTED)
                    self.assertTrue(result.status.development_mode)
        run_elevated.assert_not_called()

    def test_dev_rule_is_current_port_only_and_never_any_port(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            args = build_development_firewall_add_rule_args(executable, 43210)
            self.assertIn(f"name={DEV_FIREWALL_RULE_NAME}", args)
            self.assertIn(f"program={executable.resolve()}", args)
            self.assertIn("localport=43210", args)
            self.assertNotIn("localport=Any", args)
            self.assertIn("profile=Private", args)
            self.assertIn("protocol=TCP", args)
            self.assertEqual(
                build_development_firewall_delete_rule_args(),
                ["advfirewall", "firewall", "delete", "rule", f"name={DEV_FIREWALL_RULE_NAME}"],
            )

    def test_dev_status_marks_previous_random_port_as_stale(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            status = self.dev_status_for(
                executable,
                [_dev_rule(str(executable), "40000")],
                current_port=43210,
            )
        self.assertEqual(status.state, FirewallState.RULE_PRESENT)
        self.assertEqual(status.local_port, "40000")
        self.assertEqual(status.reason, "stale development session port")

    def test_dev_status_marks_other_python_path_as_unknown_stale(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "current" / "python.exe"
            old_executable = Path(td) / "old" / "python.exe"
            status = self.dev_status_for(
                executable,
                [_dev_rule(str(old_executable), "40000")],
                current_port=43210,
            )
        self.assertEqual(status.state, FirewallState.UNKNOWN)
        self.assertEqual(status.reason, "stale development executable")
        self.assertEqual(status.local_port, "40000")

    def test_dev_request_replaces_stale_rule_with_single_elevation_powershell(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[
                    [_dev_rule(str(executable), "40000")],
                    [_dev_rule(str(executable), "43210")],
                ],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(True, ""),
            ) as run_elevated:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertTrue(result.success)
        self.assertTrue(result.uac_requested)
        self.assertEqual(result.status.local_port, "43210")
        self.assertEqual(run_elevated.call_count, 1)
        script_arg = run_elevated.call_args.args[0]
        self.assertIn("$ErrorActionPreference = 'Stop'", script_arg)
        self.assertIn("Remove-NetFirewallRule", script_arg)
        self.assertIn("New-NetFirewallRule", script_arg)
        self.assertIn("43210", script_arg)
        self.assertIn("Private", script_arg)
        self.assertIn("TCP", script_arg)

    def test_dev_request_replace_failure_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[
                    [_dev_rule(str(executable), "40000")],
                    [_dev_rule(str(executable), "40000")],  # delete failed, still stale
                ],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(True, ""),
            ) as run_elevated:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertFalse(result.success)
        self.assertIn("未通过严格规则契约复核", result.message)

    def test_dev_request_elevation_failure_fails_immediately(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                return_value=[_dev_rule(str(executable), "40000")],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(False, "powershell.exe exited with code 1"),
            ) as run_elevated:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertFalse(result.success)
        self.assertTrue(result.uac_requested)
        self.assertIn("开发测试规则配置未完成", result.message)

    def test_dev_request_fails_if_stale_and_current_rules_coexist(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[
                    [_dev_rule(str(executable), "40000")],
                    [
                        _dev_rule(str(executable), "40000"),
                        _dev_rule(str(executable), "43210"),
                    ],
                ],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(True, ""),
            ):
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertFalse(result.success)
        self.assertIn("规则数量不符", result.message)

    def test_dev_request_refuses_marker_rule_with_unrelated_program(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                return_value=[_dev_rule("C:/OtherApp/other.exe", "40000")],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
            ) as run_elevated:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertFalse(result.success)
        self.assertFalse(result.uac_requested)
        self.assertIn("未执行修改", result.message)
        run_elevated.assert_not_called()

    def test_dev_request_reuses_exact_current_port_without_uac(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                return_value=[_dev_rule(str(executable), "43210")],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
            ) as run_elevated:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertTrue(result.success)
        self.assertFalse(result.uac_requested)
        self.assertIn("TCP 43210", result.message)
        run_elevated.assert_not_called()

    def test_dev_request_without_existing_rule_uses_one_explicit_elevated_powershell(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[[], [_dev_rule(str(executable), "43210")]],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(True, ""),
            ) as run_elevated:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertTrue(result.success)
        self.assertTrue(result.uac_requested)
        self.assertEqual(run_elevated.call_count, 1)
        self.assertIn("43210", run_elevated.call_args.args[0])

    def test_explicit_dev_cleanup_can_remove_marker_owned_old_python_rule(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "current" / "python.exe"
            old = Path(td) / "old" / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[[_dev_rule(str(old), "40000")], []],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_netsh_args",
                return_value=(True, ""),
            ) as run_elevated:
                result = clear_mobile_upload_dev_firewall_access(current)
        self.assertTrue(result.success)
        self.assertTrue(result.uac_requested)
        self.assertEqual(run_elevated.call_count, 1)
        self.assertEqual(run_elevated.call_args.args[0], build_development_firewall_delete_rule_args())

    def test_dev_cleanup_refuses_marker_rule_with_unrelated_program(self):
        with patch(
            "scripts.invoice_fetch.windows_firewall.is_windows",
            return_value=True,
        ), patch(
            "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
            return_value=[_dev_rule("C:/OtherApp/other.exe")],
        ), patch(
            "scripts.invoice_fetch.windows_firewall._run_elevated_netsh_args",
        ) as run_elevated:
            result = clear_mobile_upload_dev_firewall_access(Path("python.exe"))
        self.assertFalse(result.success)
        self.assertIn("未执行删除", result.message)
        run_elevated.assert_not_called()

    def test_uac_rejection_keeps_rule_unauthorized(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_netsh",
                return_value=(False, "UAC rejected"),
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                return_value=[],
            ):
                result = request_mobile_upload_firewall_access(executable)
        self.assertFalse(result.success)
        self.assertTrue(result.uac_requested)
        self.assertEqual(result.status.state, FirewallState.RULE_MISSING)
        self.assertIn("未授权", result.message)

    def test_success_requires_rule_to_be_observable_after_uac(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(td)
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_netsh",
                return_value=(True, ""),
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                return_value=[_rule(str(executable))],
            ):
                result = request_mobile_upload_firewall_access(executable)
        self.assertTrue(result.success)
        self.assertEqual(result.status.state, FirewallState.RULE_PRESENT)
        self.assertEqual(result.message, "已允许手机访问 · 仅私人网络")

    def test_non_windows_is_explicitly_unsupported(self):
        with patch(
            "scripts.invoice_fetch.windows_firewall.is_windows",
            return_value=False,
        ):
            status = get_mobile_upload_firewall_status()
            result = request_mobile_upload_firewall_access()
        self.assertEqual(status.state, FirewallState.NON_WINDOWS)
        self.assertEqual(result.status.state, FirewallState.NON_WINDOWS)


class WindowsFirewallProcessVisibilityTests(unittest.TestCase):
    def test_non_windows_hidden_subprocess_kwargs_are_empty(self):
        with patch.object(firewall, "is_windows", return_value=False):
            self.assertEqual(firewall._hidden_subprocess_kwargs(), {})

    def test_windows_firewall_query_uses_hidden_argv_subprocess(self):
        startupinfo = SimpleNamespace(dwFlags=0, wShowWindow=99)
        completed = SimpleNamespace(returncode=0, stdout="[]")
        with patch.object(firewall, "is_windows", return_value=True), patch.object(
            firewall.subprocess,
            "STARTUPINFO",
            return_value=startupinfo,
        ), patch.object(firewall.subprocess, "run", return_value=completed) as run:
            rules = firewall._query_firewall_rules("Synthetic Rule")

        self.assertEqual(rules, [])
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertEqual(kwargs["shell"], False)
        self.assertEqual(kwargs["creationflags"], firewall.subprocess.CREATE_NO_WINDOW)
        self.assertIs(kwargs["startupinfo"], startupinfo)
        self.assertTrue(startupinfo.dwFlags & firewall.subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startupinfo.wShowWindow, firewall.subprocess.SW_HIDE)

    def test_elevated_netsh_hides_child_console_but_keeps_runas(self):
        captured = {}

        class FakeShell32:
            def ShellExecuteExW(self, info_pointer):
                info = ctypes.cast(
                    info_pointer,
                    ctypes.POINTER(firewall._ShellExecuteInfo),
                ).contents
                captured["verb"] = info.lpVerb
                captured["file"] = info.lpFile
                captured["parameters"] = info.lpParameters
                captured["mask"] = info.fMask
                captured["show"] = info.nShow
                info.hProcess = 0x1234
                return 1

        class FakeKernel32:
            def WaitForSingleObject(self, handle, timeout):
                captured["handle"] = handle
                captured["timeout"] = timeout
                return firewall._WAIT_OBJECT_0

            def GetExitCodeProcess(self, handle, exit_code_pointer):
                ctypes.cast(
                    exit_code_pointer,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value = 0
                return 1

            def CloseHandle(self, handle):
                captured["closed"] = handle
                return 1

        windll = SimpleNamespace(shell32=FakeShell32(), kernel32=FakeKernel32())
        with patch.object(firewall, "is_windows", return_value=True), patch.object(
            firewall.ctypes,
            "windll",
            windll,
        ):
            success, reason = firewall._run_elevated_netsh_args(
                ["advfirewall", "firewall", "add", "rule", "name=Invoice Hub"]
            )

        self.assertTrue(success)
        self.assertEqual(reason, "")
        self.assertEqual(captured["verb"], "runas")
        self.assertEqual(captured["file"], firewall._NETSH)
        self.assertEqual(captured["show"], firewall._SW_HIDE)
        self.assertTrue(captured["mask"] & firewall._SEE_MASK_NOCLOSEPROCESS)
        self.assertIn("advfirewall", captured["parameters"])
        self.assertEqual(captured["closed"], 0x1234)

    def test_build_development_firewall_replace_powershell_script_has_mutation_time_ownership_guard(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            script = firewall.build_development_firewall_replace_powershell_script(executable, 43210)
            self.assertIn("$ErrorActionPreference = 'Stop'", script)
            self.assertIn(f"'{firewall.DEV_FIREWALL_RULE_NAME}'", script)
            self.assertNotIn(f"'{firewall.FIREWALL_RULE_NAME}'", script)
            self.assertNotIn(f'"{firewall.FIREWALL_RULE_NAME}"', script)

            # Ownership pre-validation before any mutation
            self.assertIn("@('python.exe', 'pythonw.exe', 'pytest.exe')", script)
            self.assertIn("Get-NetFirewallApplicationFilter", script)
            self.assertIn("[System.IO.Path]::GetFileName($prog).ToLowerInvariant()", script)
            self.assertIn("throw", script)

            # Check that validation loop comes strictly BEFORE Remove-NetFirewallRule
            validation_idx = script.index("foreach ($rule in $existing)")
            throw_idx = script.index("throw")
            remove_idx = script.index("Remove-NetFirewallRule")
            add_idx = script.index("New-NetFirewallRule")
            self.assertLess(validation_idx, throw_idx)
            self.assertLess(throw_idx, remove_idx)
            self.assertLess(remove_idx, add_idx)

    def test_dev_request_allows_replace_for_old_pythonw_or_pytest_rules(self):
        with tempfile.TemporaryDirectory() as td:
            old_executable = Path(td) / "old" / "pytest.exe"
            current_executable = Path(td) / "current" / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[
                    [_dev_rule(str(old_executable), "40000")],
                    [_dev_rule(str(current_executable), "43210")],
                ],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(True, ""),
            ) as run_pwsh:
                result = request_mobile_upload_dev_firewall_access(current_executable, 43210)
        self.assertTrue(result.success)
        self.assertEqual(run_pwsh.call_count, 1)
        self.assertEqual(result.status.local_port, "43210")

    def test_run_elevated_powershell_script_passes_encoded_command_and_hides_console(self):
        captured = {}

        class FakeShell32:
            def ShellExecuteExW(self, info_pointer):
                info = ctypes.cast(
                    info_pointer,
                    ctypes.POINTER(firewall._ShellExecuteInfo),
                ).contents
                captured["verb"] = info.lpVerb
                captured["file"] = info.lpFile
                captured["parameters"] = info.lpParameters
                captured["mask"] = info.fMask
                captured["show"] = info.nShow
                info.hProcess = 0x5678
                return 1

        class FakeKernel32:
            def WaitForSingleObject(self, handle, timeout):
                captured["handle"] = handle
                captured["timeout"] = timeout
                return firewall._WAIT_OBJECT_0

            def GetExitCodeProcess(self, handle, exit_code_pointer):
                ctypes.cast(
                    exit_code_pointer,
                    ctypes.POINTER(ctypes.c_ulong),
                ).contents.value = 0
                return 1

            def CloseHandle(self, handle):
                captured["closed"] = handle
                return 1

        windll = SimpleNamespace(shell32=FakeShell32(), kernel32=FakeKernel32())
        with patch.object(firewall, "is_windows", return_value=True), patch.object(
            firewall.ctypes,
            "windll",
            windll,
        ):
            script = "Write-Host 'test'"
            success, reason = firewall._run_elevated_powershell_script(script)

        self.assertTrue(success)
        self.assertEqual(reason, "")
        self.assertEqual(captured["verb"], "runas")
        self.assertEqual(captured["file"], firewall._POWERSHELL)
        self.assertEqual(captured["show"], firewall._SW_HIDE)
        self.assertTrue(captured["mask"] & firewall._SEE_MASK_NOCLOSEPROCESS)
        self.assertIn("-EncodedCommand", captured["parameters"])
        self.assertEqual(captured["closed"], 0x5678)

        # Verify decoded parameter matches UTF-16LE
        parts = captured["parameters"].split()
        idx = parts.index("-EncodedCommand")
        b64_str = parts[idx + 1]
        decoded = base64.b64decode(b64_str.encode("ascii")).decode("utf-16le")
        self.assertEqual(decoded, script)

    def test_dev_replace_uses_no_tempfile_or_netsh_f(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "python.exe"
            with patch(
                "scripts.invoice_fetch.windows_firewall.is_windows",
                return_value=True,
            ), patch(
                "scripts.invoice_fetch.windows_firewall._query_firewall_rules",
                side_effect=[
                    [_dev_rule(str(executable), "40000")],
                    [_dev_rule(str(executable), "43210")],
                ],
            ), patch(
                "scripts.invoice_fetch.windows_firewall._run_elevated_powershell_script",
                return_value=(True, ""),
            ) as run_pwsh:
                result = request_mobile_upload_dev_firewall_access(executable, 43210)
        self.assertTrue(result.success)
        self.assertEqual(run_pwsh.call_count, 1)
        self.assertFalse(hasattr(firewall, "tempfile"))


if __name__ == "__main__":
    unittest.main()
