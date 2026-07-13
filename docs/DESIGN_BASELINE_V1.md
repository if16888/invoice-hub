# Invoice Hub Design Baseline v1.0

This document is the product UI source of truth for the desktop application.
Implementation convenience, legacy test structure, or individual page preferences must not override it.

## Product character

Invoice Hub is an **quiet, trustworthy, compact personal reimbursement workspace**.
It is not an enterprise expense-management console and not a technical admin dashboard.

The interface must be:

- task-first;
- information-cohesive;
- progressively disclosed;
- local-first and honest about state;
- visually restrained;
- consistent without forcing every task into the same layout.

## Information ownership

| Surface | Responsibility |
| --- | --- |
| Page Header | Page name, purpose, page-level action |
| Summary | Page-level actionable metrics only |
| List | Entity identity, one primary state, minimal metadata |
| Detail Header | Current entity and primary state |
| Detail Body | Complete values grouped by responsibility |
| Action Footer | Actions for the current entity |
| Dialog | One editing or credential task |
| Inline status / toast | Result of an operation |
| Log drawer | Technical diagnostics only |

The same information must not be repeated across Summary, List, Header and Detail.

## Global visual contract

### Semantic colors

- page background: `#F7F8FA`
- surface: `#FFFFFF`
- selected surface: `#EFF6FF`
- subtle border: `#E5E7EB`
- primary text: `#182230`
- secondary text: `#667085`
- accent: `#2563EB`
- success: `#16803C`
- warning: `#B54708`
- danger: `#B42318`

Pages must use semantic roles rather than inventing new colors.

### Type

- Page title: 22px / 600
- Page hint: 13px / 400
- Section title: 14px / 600
- Body and buttons: 13px
- Field label and meta: 12px

Do not solve clipping by shrinking body text below the baseline.

### Geometry

- base grid: 4px
- page margin: 24px
- header-to-content gap: 20px
- section gap: 16px
- internal gap: 8–12px
- controls: 34px high
- field rows: approximately 36px
- primary surface radius: 8px
- control radius: 6px
- one visible border layer per information surface

Content height follows content. Large empty cards are prohibited.
Desktop primary buttons use content width, not full-page width.

## Page archetypes

- **Dashboard**: centered, maximum width 1360px.
- **Workspace**: fills available width and height; reserved for invoice review.
- **Task Flow**: centered, maximum width 1440px; source / task / result responsibility columns.
- **Settings**: centered, maximum width 1120px; secondary navigation 168px.

## Golden Page: Settings → Mailbox Accounts

The mailbox page is the reference page for the rest of Settings.

### Geometry

- Settings maximum width: 1120px
- secondary navigation: 168px
- account list: 280px
- detail: minimum 560px, maximum 760px
- column gap: 16px
- account row: 64–72px, target 68px
- field-label column: 104px
- action footer: 52px

### Structure

```text
Page header
Settings navigation | Mailbox page
                    | Page title + add account
                    | Account list | one detail surface
                    |              | entity header + state
                    |              | basic information
                    |              | connection and credentials
                    |              | scan rules
                    |              | recent activity
                    |              | contextual action footer
```

The detail area uses one outer surface. Sections use headings, field rows and dividers; nested cards are prohibited.

### Account list

Each row has two lines:

1. name with at most two compact badges;
2. masked email address.

Long values use elide plus tooltip. Badges must never squeeze the address line.

### Contextual actions

| State | Visible actions |
| --- | --- |
| Normal | Scan now (primary), test, edit, More |
| Missing credential | Add authorization code (primary), edit, More |
| Disabled | Enable account (primary), edit, More |

Normal accounts do not show “补授权码”; “更新授权码” belongs in More.
Only one visual primary action is allowed.

### Empty state

When no account exists, do not show an empty list beside an empty detail panel.
Show one compact Empty State with the primary action “新增邮箱账号”.

## High-DPI contract

At 100%, 125% and 150%:

- button text is complete;
- badges do not clip or wrap;
- navigation collapse leaves no text residue;
- field labels do not wrap unexpectedly;
- action footer remains one line;
- long names, emails, paths and models elide with a tooltip.

## Implementation order

1. Freeze Mailbox Accounts as the Golden Page.
2. Migrate AI configuration.
3. Migrate runtime, privacy, data/backup and About.
4. Migrate Import Center, reimbursement/export and Dashboard.
5. Review Workspace is optimized last as a separate dense archetype.

A later phase must not begin until the previous phase has real Windows screenshots and manual review.

## Prohibited patterns

- adding a new universal card for every problem;
- hiding an entire obsolete UI tree instead of deleting it;
- claiming visual completion from object-existence tests;
- full-width desktop actions without a narrow-container reason;
- emoji or colored Unicode as production icons;
- page-specific arbitrary colors, margins or radii;
- repeating the same status or value in multiple surfaces;
- exposing technical fields before the user asks for advanced details;
- using large empty cards to simulate whitespace;
- changing multiple page archetypes in one visual iteration.
