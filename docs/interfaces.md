# Official interfaces consulted

Read on 2026-10-23. These document interface contracts; local fixture tests establish
what this build actually supports.

- [OpenAI MCP configuration](https://learn.chatgpt.com/docs/extend/mcp): stdio,
  project `.codex/config.toml`, command/args/environment, tool timeouts.
- [OpenAI skills](https://learn.chatgpt.com/docs/build-skills): repository discovery
  through `.agents/skills/<name>/SKILL.md`.
- [Claude Code MCP](https://code.claude.com/docs/en/mcp): project `.mcp.json`, stdio,
  project trust and server approval. Normal client approval remains in effect.
- [Claude Code skills](https://code.claude.com/docs/en/skills): repository
  `.claude/skills/<name>/SKILL.md` and `/linux-agent-desktop` invocation.
- [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports):
  newline-delimited stdio, protocol-only stdout. The official Python SDK handles
  initialization, schema discovery, errors and image content.
- [Wayland protocol](https://wayland.freedesktop.org/docs/book/Protocol.html):
  compositor-mediated surfaces and input; no universal background-input promise.
- [AT-SPI 2 API](https://docs.gtk.org/atspi2/): Accessible, Action, EditableText
  interfaces, process identity, bounded semantic traversal.
- [Chrome DevTools Input](https://chromedevtools.github.io/devtools-protocol/tot/Input/)
  and [Page](https://chromedevtools.github.io/devtools-protocol/tot/Page/):
  target-scoped mouse/key/text input, screenshots and dialog handling.

Installed `kwin_wayland --help` confirms `--virtual`, `--xwayland`, output count and
scale controls. Version 0.2 adds a virtual KWin compositor with a separate runtime, config and
bus. Its EIS input and ScreenShot2 interfaces are scoped to that private process.
The local python-xlib source and Xlib behavior were checked directly. Attempts to
fetch the X.org reference timed out; no unverified X.org citation is used as test
evidence. XSendEvent success alone is explicitly not application success.

- [KWin EIS backend](https://github.com/KDE/kwin/blob/v6.6.6/src/plugins/eis/eisbackend.cpp):
  private virtual-seat input through libei.
- [KWin ScreenShot2](https://github.com/KDE/kwin/blob/v6.6.6/src/plugins/screenshot/screenshotdbusinterface2.cpp):
  UUID-targeted window capture and explicit raw-image format metadata.

Live Kate experimentation also uses the desktop's existing AT-SPI bus and
[KTextEditor accessibility](https://invent.kde.org/frameworks/ktexteditor).
The bus can be inactive; enabling it is an explicit operator setting, not an
MCP permission bypass. The demo restores the previous setting.
