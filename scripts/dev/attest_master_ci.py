"""Attest a master push from the successful PR CI for the identical source tree.

Pull requests run the full source, unit, and HCI gates. A squash merge changes
the commit SHA but preserves the tested tree; on master, this script verifies
that identity and reuses the successful PR run instead of running those tests a
second time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
REQUIRED_CI_JOBS = (
    "Source gates",
    "Unit shard 0",
    "Unit shard 1",
    "Unit shard 2",
    "HCI acceptance lane",
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
JsonFetcher = Callable[[str, str], Any]


class AttestationError(RuntimeError):
    """The exact master tree lacks a successful, matching PR CI run."""


def _fetch_json(url: str, token: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise AttestationError(f"GitHub API request failed: {url}: {exc}") from exc


def _repo_url(repo: str, path: str) -> str:
    owner, separator, name = repo.partition("/")
    if not separator or not owner or not name or "/" in name:
        raise AttestationError(f"invalid repository name: {repo!r}")
    return f"{API_ROOT}/repos/{quote(owner)}/{quote(name)}/{path.lstrip('/')}"


def _tree_sha(commit: Any, label: str) -> str:
    try:
        tree_sha = str(commit["commit"]["tree"]["sha"]).lower()
    except (KeyError, TypeError) as exc:
        raise AttestationError(f"GitHub returned no tree SHA for {label}") from exc
    if not _SHA_RE.fullmatch(tree_sha):
        raise AttestationError(f"GitHub returned an invalid tree SHA for {label}")
    return tree_sha


def _successful_gate_run(
    repo: str,
    pr_number: int,
    head_sha: str,
    token: str,
    get_json: JsonFetcher,
) -> dict[str, Any] | None:
    runs_url = _repo_url(
        repo,
        "actions/workflows/ci.yml/runs"
        f"?head_sha={quote(head_sha)}&event=pull_request&per_page=100",
    )
    runs_response = get_json(runs_url, token)
    runs = runs_response.get("workflow_runs", []) if isinstance(runs_response, dict) else []
    candidates = [
        run
        for run in runs
        if isinstance(run, dict)
        and str(run.get("head_sha", "")).lower() == head_sha.lower()
        and run.get("event") == "pull_request"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    candidates.sort(key=lambda run: int(run.get("run_number", 0)), reverse=True)

    for run in candidates:
        associated_prs = run.get("pull_requests") or []
        if associated_prs and not any(
            int(associated.get("number", 0)) == pr_number
            for associated in associated_prs
            if isinstance(associated, dict)
        ):
            continue
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        jobs_url = _repo_url(
            repo,
            f"actions/runs/{run_id}/jobs?filter=latest&per_page=100",
        )
        jobs_response = get_json(jobs_url, token)
        jobs = jobs_response.get("jobs", []) if isinstance(jobs_response, dict) else []
        by_name: dict[str, list[dict[str, Any]]] = {}
        for job in jobs:
            if isinstance(job, dict) and isinstance(job.get("name"), str):
                by_name.setdefault(job["name"], []).append(job)
        if all(
            len(by_name.get(name, [])) == 1
            and by_name[name][0].get("conclusion") == "success"
            for name in REQUIRED_CI_JOBS
        ):
            return run
    return None


def attest_master_tree(
    repo: str,
    master_sha: str,
    token: str,
    get_json: JsonFetcher = _fetch_json,
) -> dict[str, Any]:
    """Require a successful PR CI run for the exact tree now on master."""
    if not _SHA_RE.fullmatch(master_sha):
        raise AttestationError("master SHA must be a full 40-character commit SHA")
    master_sha = master_sha.lower()

    master_commit = get_json(_repo_url(repo, f"commits/{master_sha}"), token)
    master_tree = _tree_sha(master_commit, master_sha)
    associated_prs = get_json(
        _repo_url(repo, f"commits/{master_sha}/pulls?per_page=100"), token
    )
    if not isinstance(associated_prs, list):
        raise AttestationError("GitHub returned an invalid associated-PR response")

    for pr in associated_prs:
        if not isinstance(pr, dict):
            continue
        if (
            str(pr.get("merge_commit_sha", "")).lower() != master_sha
            or not pr.get("merged_at")
            or pr.get("state") != "closed"
            or (pr.get("base") or {}).get("ref") != "master"
        ):
            continue
        head = pr.get("head") or {}
        head_sha = str(head.get("sha", "")).lower()
        if not _SHA_RE.fullmatch(head_sha):
            continue
        pr_number = pr.get("number")
        if not isinstance(pr_number, int):
            continue

        pr_commit = get_json(_repo_url(repo, f"commits/{head_sha}"), token)
        if _tree_sha(pr_commit, f"PR #{pr_number} head {head_sha}") != master_tree:
            continue
        run = _successful_gate_run(repo, pr_number, head_sha, token, get_json)
        if run is None:
            continue
        return {
            "master_sha": master_sha,
            "tree_sha": master_tree,
            "pull_request": pr_number,
            "pr_head_sha": head_sha,
            "ci_run_id": run["id"],
            "ci_run_number": run.get("run_number"),
            "ci_run_url": run.get("html_url"),
        }

    raise AttestationError(
        "no merged PR to master has an identical tree and a successful exact-head "
        "CI run with all required source, unit, and HCI jobs"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args(argv)
    if not args.repo or not args.sha or not args.token:
        parser.error("--repo, --sha, and --token (or matching environment variables) are required")

    try:
        result = attest_master_tree(args.repo, args.sha, args.token)
    except AttestationError as exc:
        print(f"MASTER_CI_ATTESTATION=FAIL {exc}", file=sys.stderr, flush=True)
        return 1

    print(
        "MASTER_CI_ATTESTATION=PASS "
        f"master_sha={result['master_sha']} tree_sha={result['tree_sha']} "
        f"pull_request=#{result['pull_request']} pr_head={result['pr_head_sha']} "
        f"ci_run=#{result['ci_run_number']} {result['ci_run_url']}",
        flush=True,
    )
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(
                "## Exact-master CI attestation\n\n"
                f"- Master SHA: `{result['master_sha']}`\n"
                f"- Verified tree: `{result['tree_sha']}`\n"
                f"- Merged PR: [#{result['pull_request']}]("
                f"https://github.com/{args.repo}/pull/{result['pull_request']})\n"
                f"- Full required CI: [run #{result['ci_run_number']}]"
                f"({result['ci_run_url']})\n"
                "- Source, unit, and HCI tests were reused from the identical PR tree; "
                "they were not run a second time on master.\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
