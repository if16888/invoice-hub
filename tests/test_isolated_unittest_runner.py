from pathlib import Path
import tempfile
import unittest

from scripts.dev.run_isolated_unittest import _module_names, _select_shard


class IsolatedUnittestRunnerTests(unittest.TestCase):
    def test_shards_partition_modules_exactly_once(self):
        modules = [f"tests.test_{index:02d}" for index in range(11)]
        shards = [_select_shard(modules, 3, index) for index in range(3)]

        flattened = [module for shard in shards for module in shard]
        self.assertCountEqual(flattened, modules)
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_shards_are_deterministic_round_robin(self):
        modules = ["a", "b", "c", "d", "e", "f", "g"]

        self.assertEqual(_select_shard(modules, 3, 0), ["a", "d", "g"])
        self.assertEqual(_select_shard(modules, 3, 1), ["b", "e"])
        self.assertEqual(_select_shard(modules, 3, 2), ["c", "f"])

    def test_invalid_shard_arguments_fail_closed(self):
        with self.assertRaises(ValueError):
            _select_shard(["a"], 0, 0)
        with self.assertRaises(ValueError):
            _select_shard(["a"], 2, -1)
        with self.assertRaises(ValueError):
            _select_shard(["a"], 2, 2)

    def test_module_exclusions_happen_before_sharding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "tests"
            root.mkdir()
            (root / "test_a.py").write_text("", encoding="utf-8")
            (root / "test_b.py").write_text("", encoding="utf-8")
            owned = root / "owned"
            owned.mkdir()
            (owned / "test_c.py").write_text("", encoding="utf-8")

            modules, excluded = _module_names(
                root,
                "test_*.py",
                exclude_dirs=(owned,),
                exclude_modules=("tests.test_b",),
            )

        self.assertEqual(modules, ["tests.test_a"])
        self.assertCountEqual(
            excluded,
            ["tests.test_b", str(Path("tests") / "owned" / "test_c")],
        )
        self.assertEqual(_select_shard(modules, 1, 0), ["tests.test_a"])


if __name__ == "__main__":
    unittest.main()
