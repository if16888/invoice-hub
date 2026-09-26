# README / documentation image assets

This directory contains only synthetic or fully redacted visuals used by README and documentation.

## Current assets

- `invoice-hub-overview-v2.svg` — local-first product workflow overview.
- `desktop-review.svg` — synthetic desktop review-workbench illustration.
- `mobile-upload.svg` — synthetic LAN/mobile-upload illustration.
- `claim-export.svg` — synthetic claim-group and export illustration.

These SVGs are deliberately **editable vector source**, not base64-wrapped raster screenshots. They can be reviewed in diffs, stay small, and avoid accidental private metadata.

## Privacy rules

Never include:

- real invoices, receipts, itineraries or mailbox screenshots;
- real email addresses, tax IDs, amounts or database content;
- authorization codes, API keys, cookies or tokens;
- local private paths or full tokenized download URLs.

Use stable ASCII filenames and manually inspect every new visual before committing it.

## Real screenshots

Real application screenshots may be useful for releases, but repository screenshots must still use isolated synthetic data. Preferred flow:

1. run the existing native screenshot matrix with a disposable database;
2. inspect every image manually at 100% and 150% scale;
3. verify no real file path, account, invoice or credential appears;
4. only then copy an approved screenshot into this directory.

Do not treat offscreen/synthetic geometry evidence as a substitute for physical-Windows visual acceptance.
