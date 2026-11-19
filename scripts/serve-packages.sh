#!/bin/sh
set -eu

scripts_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$scripts_dir/yocto.py" serve "$@"
