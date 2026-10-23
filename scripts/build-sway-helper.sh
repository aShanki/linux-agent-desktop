#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
mkdir -p .local/native
protocol=lad/native/virtual-keyboard-unstable-v1.xml
wayland-scanner client-header "$protocol" .local/native/virtual-keyboard-unstable-v1-client-protocol.h
wayland-scanner private-code "$protocol" .local/native/virtual-keyboard-unstable-v1-protocol.c
cc -std=c11 -O2 -Wall -Wextra -Werror -I.local/native lad/native/sway-key.c \
  .local/native/virtual-keyboard-unstable-v1-protocol.c \
  $(pkg-config --cflags --libs wayland-client xkbcommon) -o .local/native/lad-key
