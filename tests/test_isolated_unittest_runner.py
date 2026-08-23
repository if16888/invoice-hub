from pathlib import Path
import tempfile
import unittest

from scripts.dev.run_isolated_unittest import (
    _DEFAULT_MODULE_WEIGHT,
    _MODULE_WEIGHTS,
    _expand_modules,
    _module_names,
    _select_shard,
)


class IsolatedUnittestRunnerTests(unittest.TestCase):
    def test_shards_partition_modules_exactly_once(self):
        modules = [f"tests.test_{index:02d}" for index in range(11)]
        shards = [_select_shard(modules, 3, index) for index in range(3)]

        flattened = [module for shard in shards for module in shard]
        self.assertCountEqual(flattened, modules)
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_shards_are_deterministic(self):
        modules = ["a", "b", "c", "d", "e", "f", "g"]
        weights = {"a": 10.0, "b": 8.0, "c": 6.0, "d": 4.0, "e": 2.0, "f": 2.0, "g": 1.0}

        run1 = [_select_shard(modules, 3, i, module_weights=weights) for i in range(3)]
        run2 = [_select_shard(modules, 3, i, module_weights=weights) for i in range(3)]

        self.assertEqual(run1, run2)
        # Verify LPT assignment order:
        # a (10) -> S0 (10)
        # b (8)  -> S1 (8)
        # c (6)  -> S2 (6)
        # d (4)  -> S2 (10)
        # e (2)  -> S1 (10)
        # f (2)  -> S0 (12)
        # g (1)  -> S1 (11)
        self.assertEqual(run1[0], ["a", "f"])
        self.assertEqual(run1[1], ["b", "e", "g"])
        self.assertEqual(run1[2], ["c", "d"])

    def test_heavy_module_balancing_disperses_top_suites(self):
        modules = [
            "tests.claim_groups_gui",
            "tests.test_ihds09",
            "tests.test_gui_column_filters",
            "tests.test_ihds08",
            "tests.test_preview_workbench_ui",
            "tests.test_mobile_upload",
        ]

        shards = [_select_shard(modules, 3, index) for index in range(3)]

        # The top 3 heaviest modules must be placed on 3 distinct shards
        top_3 = ["tests.claim_groups_gui", "tests.test_ihds09", "tests.test_gui_column_filters"]
        shards_containing_top_3 = [
            i for i, shard in enumerate(shards)
            if any(mod in top_3 for mod in shard)
        ]
        self.assertEqual(len(shards_containing_top_3), 3, "Top 3 heavy modules must be dispersed across all 3 shards")

        # Verify no shard has multiple of the top 3
        for shard in shards:
            intersect = set(shard).intersection(top_3)
            self.assertEqual(len(intersect), 1)

    def test_invalid_shard_arguments_fail_closed(self):
        with self.assertRaises(ValueError):
            _select_shard(["a"], 0, 0)
        with self.assertRaises(ValueError):
            _select_shard(["a"], -1, 0)
        with self.assertRaises(ValueError):
            _select_shard(["a"], 2, -1)
        with self.assertRaises(ValueError):
            _select_shard(["a"], 2, 2)
        with self.assertRaises(ValueError):
            _select_shard(["a"], 2, 5)

    def test_empty_modules_returns_empty_shard(self):
        self.assertEqual(_select_shard([], 3, 0), [])
        self.assertEqual(_select_shard([], 3, 1), [])

    def test_single_shard_contains_all_modules(self):
        modules = ["tests.test_b", "tests.test_a", "tests.test_c"]
        shard = _select_shard(modules, 1, 0)
        self.assertCountEqual(shard, modules)

    def test_unknown_modules_fallback_to_default_weight(self):
        modules = ["tests.test_unknown_z", "tests.test_unknown_a", "tests.test_unknown_m"]
        shards = [_select_shard(modules, 2, i) for i in range(2)]
        flattened = [m for s in shards for m in s]
        self.assertCountEqual(flattened, modules)

    def test_heavy_module_expands_once_into_disjoint_process_owners(self):
        modules = [
            "tests.test_alpha",
            "tests.test_claim_groups",
            "tests.test_omega",
        ]

        expanded = _expand_modules(modules)

        self.assertEqual(
            expanded,
            [
                "tests.test_alpha",
                "tests.claim_groups_core",
                "tests.claim_groups_gui",
                "tests.claim_groups_mail",
                "tests.test_omega",
            ],
        )
        self.assertEqual(len(expanded), len(set(expanded)))

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


    def test_real_repo_modules_partition_without_omissions_or_duplicates(self):
        tests_dir = Path(__file__).resolve().parent
        discovered, _ = _module_names(
            tests_dir,
            "test_*.py",
            exclude_dirs=(tests_dir / "hci_acceptance",),
            exclude_modules=("tests.test_workbench_layout",),
        )
        expanded = _expand_modules(discovered)
        self.assertGreater(len(expanded), 50)

        for shard_count in (1, 2, 3, 4, 5, 8):
            shards = [_select_shard(expanded, shard_count, i) for i in range(shard_count)]
            # Verify pairwise disjoint
            for i in range(shard_count):
                for j in range(i + 1, shard_count):
                    self.assertEqual(
                        set(shards[i]) & set(shards[j]),
                        set(),
                        f"Overlap found between shard {i} and {j} with shard_count={shard_count}",
                    )
            # Verify complete union
            union_modules = [m for s in shards for m in s]
            self.assertCountEqual(
                union_modules,
                expanded,
                f"Union mismatch with shard_count={shard_count}",
            )

    def test_select_shard_tie_breaking_is_alphabetically_deterministic(self):
        modules = ["tests.test_z", "tests.test_a", "tests.test_m"]
        weights = {"tests.test_z": 10.0, "tests.test_a": 10.0, "tests.test_m": 10.0}

        # With equal weights, sorted order should be test_a, test_m, test_z
        # Shard 0 -> test_a, Shard 1 -> test_m, Shard 2 -> test_z
        sh0 = _select_shard(modules, 3, 0, module_weights=weights)
        sh1 = _select_shard(modules, 3, 1, module_weights=weights)
        sh2 = _select_shard(modules, 3, 2, module_weights=weights)

        self.assertEqual(sh0, ["tests.test_a"])
        self.assertEqual(sh1, ["tests.test_m"])
        self.assertEqual(sh2, ["tests.test_z"])

    def test_expand_modules_rejects_duplicates(self):
        with self.assertRaises(ValueError):
            _expand_modules(["tests.test_a", "tests.test_a"])


if __name__ == "__main__":
    unittest.main()
