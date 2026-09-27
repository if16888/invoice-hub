"""Session-local connection evidence, separate from credential presence."""

from ..log_privacy import sanitize_log_message


def _identity(account: dict) -> tuple:
    imap = account.get("imap") or {}
    return (str(account.get("mailbox_key") or account.get("address") or ""),
            str(account.get("address") or ""), str(imap.get("server") or ""),
            str(imap.get("port") or 993), bool(imap.get("ssl", True)))


def forget_connection_result(window, account: dict) -> None:
    getattr(window, "_mailbox_connection_results", {}).pop(_identity(account), None)


def connection_feedback(window, account: dict, has_credential: bool) -> tuple[str, str, str]:
    if not account.get("enabled", True):
        return "已停用", "ignored", "账号已停用，未验证连接。"
    if not has_credential:
        forget_connection_result(window, account)
        return "需要授权", "review", "缺少授权码，尚未连接邮箱。请先补充授权码，再测试连接。"
    result = getattr(window, "_mailbox_connection_results", {}).get(_identity(account))
    if result is None:
        return "尚未验证", "muted", "授权码已保存；尚未验证远端登录，请点击“测试连接”。"
    success, message = result
    if success is None:
        return "测试中", "muted", message
    return ("连接成功" if success else "连接失败", "approved" if success else "error", message)


def test_mailbox_connection(window, account: dict) -> None:
    """Run the authenticated IMAP test outside the GUI thread."""
    from ..credentials import get_auth_code
    from .workers import MailboxConnectionTestRequest, MailboxConnectionTestWorker

    email = str(account.get("address") or "").strip()
    imap = account.get("imap") or {}
    server = str(imap.get("server") or "").strip()
    identity = _identity(account)
    if not hasattr(window, "_mailbox_connection_results"):
        window._mailbox_connection_results = {}
    if not hasattr(window, "_settings_mailbox_test_workers"):
        window._settings_mailbox_test_workers = {}
    if not hasattr(window, "_settings_mailbox_test_contexts"):
        window._settings_mailbox_test_contexts = {}

    if not account.get("enabled", True):
        window._mailbox_connection_results[identity] = (False, "账号已停用，不能测试连接。")
        window._refresh_settings_mailbox_page()
        return

    for request_id, context in window._settings_mailbox_test_contexts.items():
        worker = window._settings_mailbox_test_workers.get(request_id)
        if context[0] == identity and worker is not None and worker.isRunning():
            return

    if not email or not server:
        window._mailbox_connection_results[identity] = (False, "测试连接失败：当前账号缺少邮箱地址或 IMAP 服务器。")
        window._refresh_settings_mailbox_page()
        return
    if window._infer_mail_provider(email, server) == "outlook":
        window._mailbox_connection_results[identity] = (
            False,
            "测试连接失败：Outlook 需要 OAuth2/XOAUTH2，当前版本不支持授权码直连。",
        )
        window._refresh_settings_mailbox_page()
        return

    try:
        auth_code = get_auth_code(email)
    except SystemExit:
        auth_code = ""
    except Exception as exc:
        safe_error = sanitize_log_message(str(exc))
        window._mailbox_connection_results[identity] = (
            False,
            f"测试连接失败：无法读取安全凭据。{safe_error}",
        )
        window._refresh_settings_mailbox_page()
        return
    if not auth_code:
        window._mailbox_connection_results[identity] = (False, "测试连接失败：缺少授权码，请先补充凭据。")
        window._refresh_settings_mailbox_page()
        return
    try:
        port = int(imap.get("port") or 993)
    except (TypeError, ValueError):
        window._mailbox_connection_results[identity] = (False, "测试连接失败：IMAP 端口不是有效数字。")
        window._refresh_settings_mailbox_page()
        return

    request_id = int(getattr(window, "_settings_mailbox_test_sequence", 0)) + 1
    window._settings_mailbox_test_sequence = request_id
    request = MailboxConnectionTestRequest(request_id, email, auth_code, server, port)
    worker = MailboxConnectionTestWorker(request, parent=window)
    worker._settings_request_id = request_id
    window._settings_mailbox_test_contexts[request_id] = (identity, email)
    window._settings_mailbox_test_workers[request_id] = worker
    window._mailbox_connection_results[identity] = (None, "正在连接邮箱服务器并验证登录，请稍候…")
    worker.success.connect(window._settings_mailbox_connection_succeeded)
    worker.error.connect(window._settings_mailbox_connection_failed)
    worker.cancelled.connect(window._settings_mailbox_connection_cancelled)
    worker.finished.connect(window._settings_mailbox_connection_thread_done)
    window._refresh_settings_mailbox_page()
    try:
        worker.start()
    except Exception as exc:
        window._settings_mailbox_test_workers.pop(request_id, None)
        window._settings_mailbox_test_contexts.pop(request_id, None)
        safe_error = sanitize_log_message(str(exc))
        window._mailbox_connection_results[identity] = (False, f"测试连接失败：{safe_error}")
        window._refresh_settings_mailbox_page()
