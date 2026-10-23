# Capabilities

The current [conformance matrix](conformance.md) records supported operations,
measured effects and limitations for X11, AT-SPI, private Wayland, headless CDP
and the experimental live Revu adapter.

No capability listing grants permission to operate a user's live application.
Fixtures use separate displays, profiles and buses. The private virtual seat can
change its own focus without targeting the user's seat. Live Revu requires
explicit configuration and a five-minute operator grant.

An explicitly enrolled dedicated Sway session supports real native Wayland and
Wine/Xwayland windows through the [Sway adapter](sway-attachment.md). Other host
compositors, GPU overlays, games, password fields and every keyboard layout are
not supported by that attachment path.
A successful event-delivery return must always be followed by effect inspection.
