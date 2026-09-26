# Local and GitHub CI validation

Run the complete local preflight before pushing a PR update:

```bash
python -m pip install -r requirements.lock.txt -r requirements-desktop.lock.txt -r requirements-build.lock.txt -r requirements-test.lock.txt
python scripts/dev/run_local_ci_preflight.py
```

The preflight runs the source gates, all three isolated unit-test shards, the
authoritative HCI acceptance, and its oracle contract tests. It stops at the
first failure. It uses the current Python environment and does not install
packages implicitly; install the locked dependencies first. On Linux it uses
Qt offscreen mode when no platform was selected. Native desktop geometry is a
separate Windows-only diagnostic lane, and final Windows installer/UX checks
remain release gates.

## CI ownership

- Pull-request CI owns the source gates, three unit shards, HCI acceptance, and
  the separately reported native geometry lane.
- After a squash merge, the automatic `master` CI verifies the merge SHA, the
  merged PR, and equality between the master tree and the exact tree from a
  successful PR CI run. It confirms all required PR jobs succeeded and records
  that evidence on the master SHA; it does not run the same tests a second time.
- Windows release and Store packaging workflows consume the successful exact
  master CI result and run only their packaging, installation, and distribution
  checks.

Do not push a PR update until `run_local_ci_preflight.py` reports
`LOCAL_CI_PREFLIGHT=PASS`. The pull-request event then starts the authoritative
GitHub run once for that final head.
