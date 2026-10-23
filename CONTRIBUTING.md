# Contributing

Start with README.md and docs/architecture.md. Keep each adapter's supported
operations and failure conditions explicit. Delivery alone never proves an
application effect. Do not turn a failed background action into global input.

Use fresh profiles and private displays; never test against a contributor's
live applications or credentials. The live Revu adapter is opt-in and is not
used by pytest. New GUI paths need effect assertions, target identity checks,
and tests that unrelated input recipients are unchanged.

```sh
./scripts/bootstrap.sh
.venv/bin/python scripts/conformance.py --rounds 3
# Optional; requires installed Kate and LibreOffice Qt integration:
.venv/bin/python scripts/real_apps.py
```

The [Actions template](docs/checks-workflow.yml) runs the portable policy and
service subset. Copy it to `.github/workflows/checks.yml` to enable CI using a
GitHub login with workflow permissions. Automated CI is not enabled in the initial
release. The full GUI suite requires the system dependencies listed in README.md. Generated profiles, screenshots, logs
and JUnit files belong under `.runtime/`. Review `git diff --cached` before
committing. Keep machine-specific client configs local and copy the examples
from docs/usage.md instead.
