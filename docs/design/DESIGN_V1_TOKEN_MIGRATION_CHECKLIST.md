# Design v1 token migration checklist

Use this checklist when moving remaining legacy UI code onto the Design v1 token authority.

- [ ] Import shared values from `design_tokens.py`.
- [ ] Do not add another product-wide color dictionary.
- [ ] Keep page-specific geometry local unless it is truly shared.
- [ ] Replace hard-coded product accent colors in touched code.
- [ ] Preserve semantic status colors and contrast.
- [ ] Add a focused regression test for each migrated contract.
- [ ] Verify 100%, 125% and 150% Windows scaling during the consolidated physical review.

This checklist is intentionally incremental. Existing hard-coded colors outside the
files touched by a change are migrated in focused follow-up PRs rather than through
an unreviewable repository-wide replacement.
