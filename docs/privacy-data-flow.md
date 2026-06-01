# Privacy Data Flow

Invoice Hub is a local-first reimbursement preparation tool. This document defines what data is processed, where it is stored, and when network calls may happen.

## Core Principle

By default, invoices, receipts, email bodies, attachments, downloaded files, SQLite databases, and Excel exports remain on the user's machine.

Cloud AI classification is optional. When enabled, the current implementation only sends masked email subject and masked sender information. It must not send email bodies, attachments, PDF text, receipt images, databases, or exports.

## Data Inventory

| Data | Source | Default Storage | Uploaded by Default | Notes |
|---|---|---|---:|---|
| Mailbox address | `config.json` | local config file | No | `config.json` is ignored by Git. |
| QQ Mail auth code | OS credential store | Windows Credential Manager / keyring backend | No | Stored under service `invoice_mail_auth_code`. |
| AI API key | environment variable | process environment | Only sent to selected AI provider as auth | Never store in config or logs. |
| Email UID | IMAP server | `runtime/invoices.db` | No | Used for incremental scan and retry. |
| Email subject | IMAP header | `runtime/invoices.db` | Optional | Sent to AI only when cloud AI provider is explicitly enabled, after masking. |
| Email sender | IMAP header | `runtime/invoices.db` | Optional | Sent to AI only when cloud AI provider is explicitly enabled, after masking. |
| Email date | IMAP header / INTERNALDATE | `runtime/invoices.db` | No | Used for filtering and grouping. |
| Email body | IMAP message | local memory during processing | No | Used for link extraction and fallback parsing only. |
| Attachments | email MIME parts | `runtime/attachments/` | No | Saved locally; untrusted input. |
| Download links | email HTML | `runtime/invoices.db` when associated with a record | No | May contain private tokens; avoid exposing full URLs in public samples or screenshots. |
| Downloaded files | invoice/receipt provider links | `runtime/attachments/` | No | Downloaded through local Playwright browser. |
| Parsed invoice fields | PDF text / subject / HTML fallback | `runtime/invoices.db` | No | Suggested fields, not final truth. |
| SQLite database | local processing | `runtime/invoices.db` | No | Future hardening may add SQLCipher or encrypted backup. |
| Excel export | local export | `runtime/发票汇总.xlsx` | No | User-controlled output. |
| Logs | runtime events | `runtime/logs/` | No | Must not contain secrets or full credential values. |

## Local-Only Workflow

1. User configures mailbox address in `config.json`.
2. User stores QQ Mail auth code in the OS credential store.
3. CLI connects to IMAP and scans lightweight headers.
4. Local rules and trusted sender whitelist classify obvious emails.
5. Matching emails are downloaded and parsed locally.
6. Attachments and downloaded invoice files are saved under `runtime/attachments/`.
7. Parsed fields are stored in local SQLite.
8. Excel summary is generated locally.

No cloud AI call is required for this workflow.

## Optional AI Classification Workflow

AI classification is disabled by default when `ai.provider` is `none`.

When a user explicitly enables `deepseek` or `gemini`:

1. Local rules run first.
2. Only still-unclassified email headers are considered.
3. The classifier builds a prompt from UID, subject, and sender.
4. Subject and sender are masked locally before the request.
5. The AI response is used only as a classification suggestion.
6. Failed AI calls leave emails unclassified for future retry.

The current AI path must not upload:

- email body
- attachment files
- PDF text
- receipt images
- downloaded files
- SQLite database
- Excel exports

## Credential Handling

Mailbox credentials:

- Use OS credential storage through `keyring`.
- Do not store auth codes in `config.json`.
- Do not print auth codes in logs.
- Do not expose auth codes to coding agents.

AI keys:

- Use environment variables such as `DEEPSEEK_API_KEY` or `GEMINI_API_KEY`.
- Do not store real keys in examples, tests, screenshots, or docs.
- Do not commit `.env` files.

## Generated Data Locations

Current generated data is under `runtime/`:

```text
runtime/
  invoices.db
  发票汇总.xlsx
  attachments/
  logs/
```

`runtime/` must remain ignored by Git.

## Sensitive Data That Must Not Be Committed

Do not commit:

- real invoices
- real receipts
- real hotel folios
- real travel records
- mailbox exports
- raw email bodies
- screenshots containing personal or company reimbursement data
- generated Excel files from real data
- API keys, cookies, tokens, or auth codes

Tests should use synthetic fixtures only.

## Link and Attachment Safety

Email attachments and download links are untrusted input.

The implementation should continue to enforce:

- file-name sanitization
- ZIP extraction limits
- no path traversal
- no automatic execution of downloaded files
- conservative failure behavior
- explicit review for future broad-domain or tokenized download behavior

Future improvements should add:

- full file hashing
- domain-level download audit fields
- optional hiding or masking of full download URLs in exports
- stronger link-scheme filtering

## Future Hardening

Potential future hardening items:

- SQLCipher or encrypted database backup
- OS credential-store UI
- log redaction utility
- pre-commit secret scanning
- export manifest with file hashes
- per-record review status and confirmation audit trail
- user-visible privacy mode indicator
