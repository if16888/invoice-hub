from __future__ import annotations

import unittest

from scripts.dev.attest_master_ci import (
    REQUIRED_CI_JOBS,
    AttestationError,
    attest_master_tree,
)


MASTER_SHA = "a" * 40
PR_HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40
OTHER_TREE_SHA = "d" * 40
PR_NUMBER = 164
RUN_ID = 786


def _fixtures(*, matching_tree: bool = True, failed_job: str | None = None):
    master_tree = TREE_SHA
    pr_tree = TREE_SHA if matching_tree else OTHER_TREE_SHA
    run_jobs = [
        {"name": name, "conclusion": "failure" if name == failed_job else "success"}
        for name in REQUIRED_CI_JOBS
    ]
    responses = {
        f"/commits/{MASTER_SHA}": {
            "sha": MASTER_SHA,
            "commit": {"tree": {"sha": master_tree}},
        },
        f"/commits/{MASTER_SHA}/pulls?per_page=100": [
            {
                "number": PR_NUMBER,
                "state": "closed",
                "merged_at": "2026-09-26T01:00:36Z",
                "merge_commit_sha": MASTER_SHA,
                "base": {"ref": "master"},
                "head": {"sha": PR_HEAD_SHA},
            }
        ],
        f"/commits/{PR_HEAD_SHA}": {
            "sha": PR_HEAD_SHA,
            "commit": {"tree": {"sha": pr_tree}},
        },
        f"/actions/workflows/ci.yml/runs?head_sha={PR_HEAD_SHA}&event=pull_request&per_page=100": {
            "workflow_runs": [
                {
                    "id": RUN_ID,
                    "run_number": 786,
                    "head_sha": PR_HEAD_SHA,
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "success",
                    "pull_requests": [{"number": PR_NUMBER}],
                    "html_url": "https://github.com/if16888/invoice-hub/actions/runs/35798575561",
                }
            ]
        },
        f"/actions/runs/{RUN_ID}/jobs?filter=latest&per_page=100": {
            "jobs": run_jobs
        },
    }

    def get_json(url: str, _token: str):
        for suffix, value in responses.items():
            if url.endswith(suffix):
                return value
        raise AssertionError(f"unexpected API URL: {url}")

    return get_json


class TestMasterCIAttestation(unittest.TestCase):
    def test_reuses_successful_pr_gates_for_identical_master_tree(self):
        result = attest_master_tree(
            "if16888/invoice-hub", MASTER_SHA, "test-token", _fixtures()
        )
        self.assertEqual(result["master_sha"], MASTER_SHA)
        self.assertEqual(result["tree_sha"], TREE_SHA)
        self.assertEqual(result["pull_request"], PR_NUMBER)
        self.assertEqual(result["pr_head_sha"], PR_HEAD_SHA)
        self.assertEqual(result["ci_run_id"], RUN_ID)

    def test_rejects_tree_changed_by_merge(self):
        with self.assertRaisesRegex(AttestationError, "identical tree"):
            attest_master_tree(
                "if16888/invoice-hub",
                MASTER_SHA,
                "test-token",
                _fixtures(matching_tree=False),
            )

    def test_rejects_any_failed_required_pr_job(self):
        with self.assertRaisesRegex(AttestationError, "successful exact-head CI run"):
            attest_master_tree(
                "if16888/invoice-hub",
                MASTER_SHA,
                "test-token",
                _fixtures(failed_job="Unit shard 1"),
            )

    def test_rejects_non_full_master_sha_before_api_calls(self):
        with self.assertRaisesRegex(AttestationError, "full 40-character"):
            attest_master_tree("if16888/invoice-hub", "abc", "test-token")


if __name__ == "__main__":
    unittest.main()
