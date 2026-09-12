from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = ROOT / "scripts/invoice_fetch/link_downloader.py"
TESTS = ROOT / "tests/test_mail_scan_bounded_browser.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one replacement, found {count}: {old[:160]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_exact_count(path: Path, old: str, new: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"{path}: expected {expected} replacements, found {count}: {old[:160]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


# The resolver thread must release the same semaphore instance that admitted it.
# Tests temporarily replace the global semaphore; reading that global again later
# from the worker can otherwise release a different semaphore after the patch exits.
replace_once(
    LINK,
    '''    fingerprint = hashlib.sha256(host.encode("utf-8", errors="ignore")).hexdigest()[:16]\n    if not _DNS_RESOLVE_SLOTS.acquire(blocking=False):\n''',
    '''    fingerprint = hashlib.sha256(host.encode("utf-8", errors="ignore")).hexdigest()[:16]\n    resolver_slots = _DNS_RESOLVE_SLOTS\n    if not resolver_slots.acquire(blocking=False):\n''',
)
replace_exact_count(
    LINK,
    '        _DNS_RESOLVE_SLOTS.release()\n',
    '        resolver_slots.release()\n',
    2,
)

# _ensure_browser now receives the shared deadline. Keep the cancellation test
# focused on control-flow propagation rather than an obsolete zero-argument mock.
replace_once(
    TESTS,
    '        def cancel_during_start():\n',
    '        def cancel_during_start(*_args, **_kwargs):\n',
)

print("mail scan deadline follow-up patch applied")
