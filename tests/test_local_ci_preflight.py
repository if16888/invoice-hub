from __future__ import annotations

import unittest

from scripts.dev.run_local_ci_preflight import preflight_commands


class TestLocalCIPreflight(unittest.TestCase):
    def test_runs_all_required_gates_and_all_three_unit_shards(self):
        commands = preflight_commands()
        labels = [label for label, _command in commands]
        self.assertEqual(
            labels,
            [
                "CLI help",
                "repository privacy gate",
                "public export/source tree gate",
                "release metadata gate",
                "architecture policy gate",
                "Python compile check",
                "unit shard 0",
                "unit shard 1",
                "unit shard 2",
                "HCI acceptance",
                "HCI oracle contract tests",
            ],
        )
        shard_commands = [
            command for label, command in commands if label.startswith("unit shard ")
        ]
        self.assertEqual(len(shard_commands), 3)
        for index, command in enumerate(shard_commands):
            self.assertEqual(command[command.index("--shard-index") + 1], str(index))

    def test_native_geometry_is_excluded_from_offscreen_local_gate(self):
        shard_commands = [
            command for label, command in preflight_commands() if label.startswith("unit shard ")
        ]
        self.assertTrue(shard_commands)
        for command in shard_commands:
            module_flag = command.index("--exclude-module")
            self.assertEqual(
                command[module_flag + 1], "tests.test_workbench_native_geometry"
            )


if __name__ == "__main__":
    unittest.main()
