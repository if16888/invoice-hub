# Implementation notes

The runtime stylesheet is rebuilt after legacy compatibility tokens are overwritten
from `design_tokens.py`. This preserves existing selectors while removing token drift.

Remaining historical color literals are intentionally migrated component by component
instead of through an unsafe global replacement.
