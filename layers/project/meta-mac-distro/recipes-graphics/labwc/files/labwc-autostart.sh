#!/bin/sh

# Start labwc after a local password login on tty1.
# Do not start it for SSH sessions or other virtual terminals.

if [ "$(id -un)" = "ming" ] &&
   [ "$(tty 2>/dev/null)" = "/dev/tty1" ] &&
   [ -z "${WAYLAND_DISPLAY:-}" ] &&
   [ -z "${DISPLAY:-}" ]; then
    exec labwc
fi

