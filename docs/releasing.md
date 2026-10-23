# Public-release checks

Do not publish a raw workspace archive. Only publish reviewed Git objects.
Runtime directories, profiles, screenshots, logs, local client configuration and
historical development briefs can contain private material even when application
code is safe to share.

Before release:

1. Run the full conformance suite and the package build.
2. Review `git diff --cached --check` and `git diff --cached --stat`.
3. Export the exact staged tree using `git checkout-index --all --prefix=.../`
   into a new temporary directory outside the source tree.
4. Scan that directory using Gitleaks with default rules and `--redact`. Do not
   suppress findings without investigating them. Reports must not expose values.
5. Check filenames and text for local home paths, private screenshots, document
   identifiers, local client configuration and profiles. Secret-pattern scanners
   do not cover all personal information.
6. Scan the exact outgoing history with `gitleaks git --redact --log-opts=main`.
   A clean worktree alone does not remove secrets from older commits.
7. Push only the reviewed branch, never `--all` or `--mirror`. Verify the remote
   commit and public visibility after pushing.

The initial public release uses a fresh root commit. The machine-specific
original development brief is not part of that branch's history. Public reports
include test outcomes and source fingerprints; detailed JUnit and process logs
remain under `.runtime/`.

Automated scans reduce risk; they cannot prove that every possible sensitive
value is absent. The publication report describes exactly what was checked.

The initial publishing login lacks GitHub workflow-write permission, so the
Actions configuration is distributed as `docs/checks-workflow.yml`. Enabling it
requires copying it to `.github/workflows/checks.yml` with a suitably authorized
GitHub login. Local validation results do not imply hosted CI has run.
