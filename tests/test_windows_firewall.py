import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.invoice_fetch.windows_firewall import (
    FIREWALL_RULE_NAME,
    FirewallState,
    build_firewall_add_rule_args,
    get_mobile_upload_firewall_status,
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


if __name__ == "__main__":
    unittest.main()
