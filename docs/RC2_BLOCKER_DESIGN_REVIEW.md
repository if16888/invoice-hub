# v0.1.5-rc2 blocker design review

## Evidence and root cause

RC1 evidence identifies the remaining export at
`C:\Users\gawk\AppData\Local\Programs\InvoiceHub\exports\...`. The portable
ZIP contains no `exports` entry, so this is runtime-generated data, not a
packaging payload. The frozen runtime derives the old default from
`PROJECT_ROOT / "exports"`; Inno Setup removes only manifest-owned files and
therefore correctly leaves an unknown runtime directory behind.

The mailbox reproduction reached IMAP login and mailbox search. The delay was
the header-query stage: hundreds of candidates were fetched one by one with
`BODY.PEEK[HEADER.FIELDS ...]`. The old worker exposed only a generic busy
state, had no cancellation path, and `IMAP4_SSL` had no bounded connect/TLS/
command-read timeout.

## Ownership boundary

Program files belong under the installation directory. The default export
root belongs to the user and is now the platform Documents directory plus
`Invoice Hub/Exports`. The AppData database, attachments, configuration and
credentials remain user-owned runtime data. A configured non-empty
`export.output_dir` remains authoritative and is not rewritten.

## Minimal repair

* Resolve the Windows Documents known folder through the platform API.
* Copy and verify legacy install-local exports without overwriting; use a
  deterministic digest suffix for conflicts, remove only verified files and
  empty source directories, and report failures while retaining sources.
* Add cooperative scan control and stage events for connect, TLS, auth, query,
  download, parse, save, complete, failed and cancelled.
* Bound TCP connect, TLS handshake and IMAP command/read operations separately.
  Cancellation closes the active socket and is observed at database-safe
  operation boundaries; it never terminates the worker thread.

## Compatibility risks

Existing explicit export paths are preserved. Existing fake MailFetcher
integrations without lifecycle keyword arguments are supported by the scan
factory. The legacy install-local folder is only cleaned after verified
migration; a conflict or copy error keeps the source file.

## Test strategy

Unit coverage verifies default/custom paths, migration idempotence, same-name
conflicts, source retention on failure, staged redacted events, separate
timeouts, socket cancellation, compileability, and existing IMAP semantics.
The remaining release gates and the physical RC2 install/upgrade/uninstall
acceptance remain mandatory before any rc2 tag or stable decision.
