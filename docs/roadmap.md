# Invoice Hub Roadmap

This document outlines the development roadmap and upcoming plans for the open-source **Invoice Hub** project. Our core mission is to provide an incredibly fast, secure, local-first utility for organizing personal reimbursement materials before submission.

---

## Current Roadmap & Core Focus Areas

Our development focus is structured around enhancing offline reliability, format compatibility, and personal data safety.

### 1. Offline & Local Import
- **Direct Directory Monitoring**: Enable robust scanning of local folders to bulk-import PDF, OFD, and image invoices.
- **Mobile QR Code Upload**: Simplify local transfers from mobile devices to the desktop application over local area networks (Wi-Fi) without cloud middle-servers.

### 2. Multi-Channel Mailbox Scanning
- **Generic IMAP Synchronization**: Standardize connection flows for QQ Mail, NetEase (163/126), and other generic IMAP email accounts using system-level secure credential managers.
- **Smart Subject Filtering**: Local rule-based scanners to isolate potential invoice emails.

### 3. Extensible Invoice Parsing Rules
- **Regex & Structured Extractors**: Refine localized extraction rules for tax registry IDs, total amounts, dates, and invoice codes from standard Chinese electronic invoices.
- **User Customization**: Allow advanced users to extend local parsing regex configurations for special formats.

### 4. Interactive GUI Verification Workbench
- **PySide6 Review Workspace**: High-performance grid layout supporting instant search, filtering, and detail drawers.
- **Batch Editing**: Support right-click actions on selected rows for setting review status, tags, and category associations.
- **Lazy-Loaded PDF Previews**: Built-in document viewer utilizing lightweight lazy-initialization to keep cold startup under 1.5 seconds.

### 5. Structured Reimbursement Group Bundling
- **Excel Ledger Export**: Output cleanly structured `.xlsx` ledger sheets with comprehensive metadata, filenames, and user categories.
- **Attachment Packages**: Automatically bundle original files into unified, structured ZIP directories.

### 6. Local-First Redacted Diagnostics
- **Privacy-Redacting Feedback Engine**: Build allowlist-based diagnostics generating trouble-shooting logs that thoroughly mask paths, credentials, and financial metrics.

### 7. Core Quality & Format Enhancement
- **Enhanced OFD/Image Processing**: Improve local rendering and text extraction accuracy for national OFD formats and rasterized image receipt scans.
- **Parsing Robustness**: Strengthen rule engines against visual edge cases and layout variations.
