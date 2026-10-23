# Security and privacy

Use dedicated test apps and fresh profiles. The service is an experimental local
agent tool, not a sandbox against malicious code running under your OS account.
Its same-user socket and client owner IDs prevent accidental cross-task access;
they are not separate security principals.

- Do not expose the Unix socket or loopback observer through a proxy or tunnel.
- Treat the observer URL fragment as private. Screenshots may contain document
  contents even though action journals store only metadata.
- Keep `.runtime/`, `.local/`, profiles, screenshots, logs, databases, environment
  files and local client configuration out of Git. Generated JUnit/log output is
  private runtime data, not a public artifact.
- The live Revu adapter requires explicit runner, prefix and test-title settings
  before service startup, followed by an operator enrollment. Use only a
  disposable document with the user's authorization. A timeout or input guard
  failure may leave a partial action; inspect before retrying.
- The private compositor disables its own screenshot permission checks. This
  applies only to the task-owned compositor, not the host desktop.
- Never automate sign-in, passwords, payment, external sends or destructive
  actions through a fixture permission. There is no automatic foreground fallback.

To report a vulnerability, use GitHub's private vulnerability reporting when
available. Do not put credentials, access links or private screenshots in a
public issue. Otherwise open a content-free issue asking for a private channel.

Publication checks cover the staged tree and outgoing history with Gitleaks,
plus explicit checks for local paths and disallowed files. No automated scanner
can prove the absence of every possible sensitive value.

## Dedicated Sway attachment

The operator-only Sway grant explicitly permits session focus/pointer changes
and visible-region capture, including overlays. Use a dedicated, exclusively
controlled session. Focus/identity checks are not atomic with compositor input.
Other participants in that session can redirect events between checks.
No grant is inferred from inherited desktop variables; sockets, compositor and
target process lifetimes are checked. One cross-service seat lease prevents
accidental concurrent enrollment. Revocation kills only helpers, never attached
apps. See [attachment boundaries and recovery](docs/sway-attachment.md).
