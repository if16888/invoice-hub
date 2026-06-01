# Contributing to Invoice Hub

Thank you for your interest in contributing to Invoice Hub. We welcome issues,
bug reports, documentation improvements, and code contributions that improve
this local-first reimbursement preparation assistant.

---

## Code of Conduct & Principles

Our project prioritizes **local-first privacy by default** and **local-first operations**.
When writing code or adding support for new features:
1. **Do not send invoice files, email bodies, PDF text, databases, exports, or credentials to cloud services.** Optional AI features must be explicit opt-in and limited to documented, redacted metadata.
2. **Never include real financial, invoice, or personal credentials** in unit tests, logs, or diagnostic tools. All test fixtures must use synthetic/mocked data.

---

## Development Environment Setup

We recommend developing on Windows using Python 3.10+.

1. Clone the repository and navigate to the directory:
   ```powershell
   git clone <repository-url>
   cd invoice-hub
   git checkout -b my-change
   ```
2. Create and activate a virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
3. Install core and desktop dependencies:
   ```powershell
   pip install -r requirements.txt
   pip install -r requirements-desktop.txt
   ```
4. Install build dependencies if working on installer packaging:
   ```powershell
   pip install -r requirements-build.txt
   ```

---

## Verification Before Submitting

To ensure safety, compliance, and high reliability, please run the following verification steps on your local branch before committing or opening a Pull Request:

### 1. Execute the Privacy Scanner
We run an automated privacy scanner to protect against the accidental commit of real invoice files, credentials, or corporate tax numbers:
```powershell
python scripts/check_repo_privacy.py
```
This script will fail the build if it detects any restricted file extensions, forbidden directories (e.g., `scratch/`, `real-samples/`), or sensitive keywords (like actual tax identification strings).

### 2. Run the Unit Test Suite
Ensure all existing tests run and pass without regressions:
```powershell
python -m unittest discover -v
```

### 3. Check CLI Entrypoint Integrity
Validate that basic CLI parsing is operational:
```powershell
python -m scripts.invoice_fetch --help
```

### 4. Git Check
Verify there are no trailing whitespaces or formatting issues in the staged diff:
```powershell
git diff --check
```

---

## Pull Request Guidelines

- Ensure your branch is updated with the latest `master`.
- Keep commits descriptive and atomic.
- Do not include real invoices, receipts, screenshots, mailbox exports, local
  databases, generated Excel files, config files, or credentials.
- Avoid exposing your personal email address in commits if that matters to you.
  GitHub supports no-reply commit email addresses.
- Changes to `.github/workflows/`, `packaging/`, `SECURITY.md`, and privacy
  documentation require maintainer review.

---

## Developer Certificate of Origin

Invoice Hub uses the Developer Certificate of Origin (DCO) for inbound
contributions. By adding a `Signed-off-by` line to your commit message, you
certify that you have the right to submit the contribution under this
repository's Apache-2.0 license.

Use:

```powershell
git commit -s -m "describe your change"
```

The sign-off line should look like:

```text
Signed-off-by: Your Name <you@example.com>
```

If you use GitHub no-reply email, use that same email in the sign-off.
