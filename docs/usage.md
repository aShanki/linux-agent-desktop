# Running and connecting clients

Run `./scripts/bootstrap.sh` from the repository root, then keep the daemon alive:

```sh
.venv/bin/lad --observer-port 8765 serve
```

It does not open an OS window. The socket and private observer link are in
`.runtime/`. The bootstrap script uses a system-site-packages virtualenv for
Ubuntu PyQt6/GI. If Xvfb is missing it downloads and extracts an Ubuntu package
under `.local/`, without installing it system-wide. No credentials are needed.

```sh
.venv/bin/lad capabilities
.venv/bin/python scripts/demo.py
.venv/bin/lad revoke-all
```

The demo leaves an owned fixture open for its lease. Its printed observer URL
shows animated cursor activity. Do not publish the URL fragment. The cursor is
an overlay in the viewer, not the user's desktop pointer. Ctrl+C in the daemon
closes owned fixture processes; crash recovery runs on the next service start.

## Register Claude Code and Codex

Run these from the installation directory. Each command stores the installation's
absolute interpreter path. Update the registrations if the checkout moves.

```sh
LAD_INSTALL_DIR="$(pwd -P)"
codex mcp add linux-agent-desktop --env LAD_CLIENT_ID=codex-linux-agent-desktop -- "$LAD_INSTALL_DIR/.venv/bin/python" -m lad.mcp_server
claude mcp add --scope user --transport stdio linux-agent-desktop --env LAD_CLIENT_ID=claude-linux-agent-desktop -- "$LAD_INSTALL_DIR/.venv/bin/python" -m lad.mcp_server
```

Install the maintained skills in each client's user skill directory:

```sh
mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
ln -s "$LAD_INSTALL_DIR/.agents/skills/linux-agent-desktop" "$HOME/.agents/skills/linux-agent-desktop"
ln -s "$LAD_INSTALL_DIR/.claude/skills/linux-agent-desktop" "$HOME/.claude/skills/linux-agent-desktop"
```

These `ln` commands intentionally fail if a destination already exists. Inspect
an existing installation before replacing it. Restart a client session to refresh
cached skill/tool catalogs. Invoke `$linux-agent-desktop` in Codex or
`/linux-agent-desktop` in Claude Code. These registrations do not bypass either
client's normal approval controls. Local `.mcp.json` and `.codex/config.toml`
files are ignored and are not distributed.

Example prompt:

> Use linux-agent-desktop to open an isolated GTK test app. Inspect its tree,
> enter “Hello ✓” in Message, invoke Increment, verify the result, then close it.

## Action contract

1. Call `desktop_capabilities` for current restrictions.
2. `desktop_open_task` supports `qt`, `gtk`, `browser`, `wayland-qt`,
   `wayland-gtk`, and `wayland-canvas`. Scale is 1, 1.5 or 2; private Wayland can
   use one or two virtual outputs.
3. Discover a current target with `desktop_discover`.
4. Supply that task, target and a fresh UUID action ID to `desktop_action` or
   `desktop_screenshot`.
5. Inspect the effect. On uncertainty query `desktop_result`; never blindly
   replay a write under a new ID.
6. Close the task with `desktop_close_task`.

X11 coordinates are window physical pixels; browser coordinates are CSS pixels;
private Wayland coordinates are window logical pixels. Its PNG scale converts
logical coordinates to screenshot pixels. GTK semantic text and CDP support
Unicode. Native Wayland key text currently supports letters, digits and spaces.
Covered coordinate targets reject input; GTK semantic actions can remain usable.

Completed action replays return metadata rather than original screenshots or
text. A timeout or cancellation may leave a partial effect. Tasks cannot resume
after daemon restart. Owner IDs namespace clients; the OS user remains the
security boundary. Fixture leases expire after 30 minutes.

## Live Revu test adapter

Only use an explicitly authorized disposable document. Before daemon startup,
configure the exact existing Wine installation and a distinctive ASCII document
title. Replace these example paths with your own; the service does not start or
sign in to Revu:

```sh
export LAD_WINE_BIN=/absolute/path/to/wine/bin
export LAD_WINEPREFIX=/absolute/path/to/test-prefix
export LAD_REVU_TITLE=LAD-Revu-Test
.venv/bin/lad --observer-port 8765 serve
```

Then grant one client a five-minute enrollment:

```sh
.venv/bin/lad --owner codex-linux-agent-desktop attach-revu
# Or use --owner claude-linux-agent-desktop
```

Find it through `desktop_tasks`. Only discovery, geometry, screenshots, clicks and
drags are supported. Close/revoke detaches; it never saves or closes Revu. The
native helper also needs `x86_64-w64-mingw32-gcc`. Read the
[live-adapter limits](revu-live-test.md) before use. Public MCP tools cannot create
this enrollment, although a same-user shell can run the operator CLI.

## Validation

```sh
.venv/bin/python scripts/conformance.py --rounds 3
.venv/bin/python scripts/benchmark.py
# Optional, with Kate and LibreOffice's Qt plugin installed:
.venv/bin/python scripts/real_apps.py
```

The last command starts fresh private instances and verifies saved scratch text.
It does not enroll existing user windows. See [the evidence](conformance.md).
