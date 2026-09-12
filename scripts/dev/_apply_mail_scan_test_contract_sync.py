from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK_TESTS = ROOT / "tests/test_link_downloader.py"
WORKFLOW_TESTS = ROOT / "tests/test_invoice_workflow.py"


def replace_exact(path: Path, old: str, new: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"{path}: expected {expected} occurrences, found {count}: {old!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def replace_nonzero(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count <= 0:
        raise RuntimeError(f"{path}: expected at least one occurrence: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"{path.name}: replaced {count} x {old!r}")


# download_from_email now forwards its shared email deadline to the private
# _download_url boundary. Test doubles that intentionally replace/override that
# private boundary must accept the new keyword rather than silently exercising an
# obsolete signature.
replace_nonzero(
    LINK_TESTS,
    "disable_fallback=False):",
    "disable_fallback=False, deadline=None):",
)
replace_nonzero(
    WORKFLOW_TESTS,
    "disable_fallback=False):",
    "disable_fallback=False, deadline=None):",
)

# Keep the single-email budget test attached to the current contract. It used to
# mutate a retired private attribute and patch perf_counter even though production
# now uses monotonic time, so it no longer exercised the claimed boundary.
replace_exact(
    LINK_TESTS,
    "        dl._max_seconds_per_email = 1\n",
    "        dl._email_budget_seconds = 1\n",
    1,
)
replace_exact(
    LINK_TESTS,
    '                patch("scripts.invoice_fetch.link_downloader.time.perf_counter", side_effect=[0, 2, 2]):\n',
    '                patch("scripts.invoice_fetch.link_downloader.time.monotonic", side_effect=[0, 2, 2, 2]):\n',
    1,
)

print("mail scan test-contract sync applied")
