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
    return ("连接成功" if success else "连接失败", "approved" if success else "error", message)


def test_mailbox_connection(window, account: dict) -> None:
    """Only a completed authenticated connection can establish success."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from ..credentials import get_auth_code
    from ..mail_fetcher import MailFetcher

    email = str(account.get("address") or "").strip()
    imap = account.get("imap") or {}
    server = str(imap.get("server") or "").strip()
    auth_code = ""
    fetcher = None
    success = False
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        if not email or not server:
            raise ValueError("当前账号缺少邮箱地址或 IMAP 服务器。")
        if window._infer_mail_provider(email, server) == "outlook":
            raise ValueError("Outlook 需要 OAuth2/XOAUTH2，不支持授权码直连测试。")
        try:
            auth_code = get_auth_code(email)
        except SystemExit:
            raise ValueError("缺少授权码，请先补充凭据。") from None
        port = int(imap.get("port") or 993)
        fetcher = MailFetcher(address=email, auth_code=auth_code, server=server, port=port)
        fetcher.connect()
        success = True
        message = "测试连接成功：本次已完成 IMAP 登录验证。"
    except Exception as exc:
        reason = str(exc)
        if auth_code:
            reason = reason.replace(auth_code, "<redacted>")
        message = f"测试连接失败：{sanitize_log_message(reason)}"
    finally:
        if fetcher is not None:
            try:
                fetcher.disconnect()
            except Exception:
                pass
        QApplication.restoreOverrideCursor()
    if not hasattr(window, "_mailbox_connection_results"):
        window._mailbox_connection_results = {}
    window._mailbox_connection_results[_identity(account)] = (success, message)
    window._refresh_settings_mailbox_page()
