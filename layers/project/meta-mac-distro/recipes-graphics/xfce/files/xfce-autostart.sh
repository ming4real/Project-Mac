#!/bin/sh

# tty1 is the local desktop login. Other VTs and SSH retain a shell.
if [ "$(id -un)" = "@MAC_USERNAME@" ] &&
   [ "$(tty 2>/dev/null)" = "/dev/tty1" ] &&
   [ -z "${DISPLAY:-}" ] &&
   [ -z "${WAYLAND_DISPLAY:-}" ]; then
    # Keep the controlling VT so Xorg can take the logind session devices.
    export XDG_SESSION_TYPE=x11
    exec @BINDIR@/startx @LIBEXECDIR@/xfce-x11-session -- @BINDIR@/Xorg vt1 -keeptty -nolisten tcp
fi
