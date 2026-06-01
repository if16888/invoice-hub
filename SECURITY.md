# Security Policy

Invoice Hub is designed around a strict local-first architecture. Protecting user data, passwords, and scanned finances is our top priority.

## Security Architecture & Design

To minimize security exposure:
- **Local Credentials Store**: IMAP passwords and application authorization codes are never committed to files or environment setups. They should always be managed using local operating system-level keystores (e.g., Windows Credential Manager) via `cmdkey`.
- **Default No Remote Storage**: Original electronic invoices, parsed databases, logs, and generated Excel files remain local to the user's workspace.
- **Privacy-Preserving Logs**: Runtime logs and diagnostics apply redaction for known sensitive patterns. Do not attach raw logs to public issues.

## Reporting a Vulnerability

If you discover a potential security or privacy vulnerability in this project, **please do not open a public GitHub issue**. Instead, report it directly and confidentially to the maintainers so we can address it safely.

Please send security reports via private channels (e.g., email) to the repository maintainers' contact addresses.

In your report, please include:
- A brief description of the vulnerability.
- Steps to reproduce or a proof of concept (using only synthetic or mock data).
- The potential impact of the issue.

We will review your submission promptly and work to resolve any verified issues in a secure and timely manner.
