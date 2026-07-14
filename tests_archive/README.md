# Archived tests

Files in this directory are **not included** by the active CI command:

```text
python -m unittest discover -v -s tests -p "test_*.py"
```

They are retained only when an old test documents a migration or production incident but no longer provides a stable behavioral contract.

A test belongs here when it primarily:

- inspects source text, method names, or implementation shape;
- recreates a branch of production logic inside the test instead of calling production code;
- is tied to an obsolete release-candidate identifier;
- duplicates a stronger behavioral or end-to-end regression test.

Archived tests must not be used as evidence that current functionality works. Active regression coverage belongs under `tests/` and should assert externally observable behavior.
