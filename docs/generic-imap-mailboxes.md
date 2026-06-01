# Generic IMAP Mailbox Setup

## Purpose

Invoice Hub uses standard IMAP for mailbox intake. The first MVP path supports QQ Mail by default and adds lightweight presets for 163/126 mailboxes plus a custom IMAP mode for enterprise or other providers.

This is intentionally not a full Gmail/Outlook OAuth integration. Gmail, Outlook, and enterprise mailboxes can be tested through `custom` IMAP configuration first.

## Supported Provider Values

```text
qq
netease_163
netease_126
custom
```

## QQ Mail

```json
{
  "email": {
    "provider": "qq",
    "address": "your_email@qq.com",
    "username": ""
  },
  "imap": {
    "server": "imap.qq.com",
    "port": 993,
    "ssl": true
  }
}
```

Credential example:

```powershell
cmdkey /generic:invoice_mail_auth_code /user:your_email@qq.com /pass:<邮箱授权码>
```

## 163 Mail

```json
{
  "email": {
    "provider": "netease_163",
    "address": "your_email@163.com",
    "username": ""
  },
  "imap": {
    "server": "imap.163.com",
    "port": 993,
    "ssl": true
  }
}
```

Credential example:

```powershell
cmdkey /generic:invoice_mail_auth_code /user:your_email@163.com /pass:<邮箱授权码或应用密码>
```

## 126 Mail

```json
{
  "email": {
    "provider": "netease_126",
    "address": "your_email@126.com",
    "username": ""
  },
  "imap": {
    "server": "imap.126.com",
    "port": 993,
    "ssl": true
  }
}
```

## Custom / Enterprise IMAP

Use this for enterprise mailboxes or providers not covered by a preset.

```json
{
  "email": {
    "provider": "custom",
    "address": "your_email@example.com",
    "username": ""
  },
  "imap": {
    "server": "imap.example.com",
    "port": 993,
    "ssl": true
  }
}
```

If your provider requires a login name different from the email address, set `email.username`. The current MVP still primarily uses `email.address` as the credential lookup key. Keep the keyring user aligned with the configured mailbox address unless a future provider-specific patch changes this behavior.

Credential example:

```powershell
cmdkey /generic:invoice_mail_auth_code /user:your_email@example.com /pass:<邮箱授权码或应用密码>
```

## MVP Boundary

Included:

- Standard SSL IMAP mailbox scanning.
- Provider presets for QQ, 163, 126, and custom.
- Generic login/error wording.
- Credentials stored in OS keyring / Windows Credential Manager.

Not included yet:

- Gmail OAuth.
- Outlook OAuth.
- Multi-account scanning.
- Automatic provider discovery.
- Non-SSL IMAP.
- Provider-specific folder mapping.

## Troubleshooting

1. Make sure IMAP is enabled in the mailbox provider settings.
2. Use an app password or authorization code, not necessarily the web login password.
3. Confirm `imap.server`, `imap.port`, and `search.folder` match the provider.
4. Confirm the credential is saved with the same user value as `email.address`.
5. Start with `--scan-only --limit 10` before running full download.
