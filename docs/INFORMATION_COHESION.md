# Information Cohesion

Invoice Hub assigns each piece of information to one surface so users do not
have to reconcile the same state across cards, lists, and dialogs.

## Surface Rules

| Surface | Owns | Does not own |
| --- | --- | --- |
| Summary | Page-level, actionable counts | Complete details of the selected entity |
| List | Identity, one primary status, minimal metadata | Full values or action controls |
| Detail header | Current entity, its primary status, relevant actions | Page-wide statistics |
| Detail body | Complete grouped values | Repeated summary values |
| Dialog | One editing task | A duplicate read-only page |
| Log drawer | Runtime and diagnostic detail | Business-page results |

## Page Rules

- A page exposes at most one visual primary action.
- Low-frequency actions live in a More menu or a danger confirmation flow.
- Empty content uses `EmptyStateCard`; it does not stretch a short hint across
  the workspace.
- A business page never shows raw runtime logs or internal status keys.
- Width follows responsibility: lists stay compact, the working surface grows,
  and result or inspection panels use a bounded contextual width.

## Settings

The in-window settings page is the only settings center. Legacy full settings
dialogs remain compatibility code only and must not be reachable from a
button, menu, shortcut, or error recovery path. Single-task dialogs are used
only to add or edit a mailbox or AI configuration.
