#!/usr/bin/env python3
"""Read project settings and run kas or the local IPK server."""

import argparse
import base64
import binascii
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import string
import subprocess
import sys
from tempfile import NamedTemporaryFile


PROJECT = Path(__file__).resolve().parent.parent
KAS_CONFIG = "kas/main.yaml:kas/local.yaml"
IMAGES = ("mac-image", "mac-image-installer")
BUILD_KEYS = {"MAC_PASSWORD", "MAC_SSH_PUBLIC_KEY_FILE"}
KEYS = {"MAC_USERNAME", "OPKG_SERVER_IP", "OPKG_SERVER_PORT"} | BUILD_KEYS
SALT_CHARS = string.ascii_letters + string.digits + "./"


def read_config(require_build_inputs):
    path = PROJECT / ".env"
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError("Missing .env. Copy .env.example to .env and edit the settings.") from None
    except UnicodeDecodeError:
        raise ValueError(".env must be UTF-8 text.") from None

    settings = {}
    for number, line in enumerate(contents.split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, equals, value = line.partition("=")
        if not equals or key not in KEYS:
            raise ValueError(f".env line {number}: expected a supported KEY=value setting.")
        if key in settings:
            raise ValueError(f".env line {number}: duplicate setting {key}.")
        settings[key] = value

    required = KEYS if require_build_inputs else KEYS - BUILD_KEYS
    missing = sorted(key for key in required if not settings.get(key))
    if missing:
        raise ValueError(f"Set {', '.join(missing)} in .env.")

    username = settings["MAC_USERNAME"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) or username in {"root", "nobody"}:
        raise ValueError("MAC_USERNAME must be an unprivileged Linux name (1-32 lowercase letters, digits, _ or -).")

    password = settings.get("MAC_PASSWORD", "")
    if password and (not 12 <= len(password.encode("utf-8")) <= 128 or
                     any(ord(char) < 32 or ord(char) == 127 for char in password) or not password.strip()):
        raise ValueError("MAC_PASSWORD must contain 12-128 UTF-8 bytes and no control characters.")

    try:
        address = ip_address(settings["OPKG_SERVER_IP"])
    except ValueError:
        raise ValueError("OPKG_SERVER_IP must be an IPv4 or IPv6 address.") from None
    if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255" or "%" in str(address):
        raise ValueError("OPKG_SERVER_IP must be a usable unicast address without a scope suffix.")

    port = settings["OPKG_SERVER_PORT"]
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise ValueError("OPKG_SERVER_PORT must be an integer between 1 and 65535.")

    return username, password, settings.get("MAC_SSH_PUBLIC_KEY_FILE"), address, int(port)


def write_private_once(path, contents):
    """Publish a private, complete file without replacing a concurrent writer's file."""
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(contents)
            handle.flush()
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink()


def private_input_dir():
    private = PROJECT / ".yocto-secrets"
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink() or private.stat().st_mode & 0o077:
        raise ValueError(".yocto-secrets must be a private directory (chmod 700).")
    return private


def password_file(password, environment):
    private = private_input_dir()

    salt_file = private / "salt"
    if not salt_file.exists():
        salt = "".join(secrets.choice(SALT_CHARS) for _ in range(16))
        write_private_once(salt_file, (salt + "\n").encode("ascii"))
    salt = salt_file.read_text(encoding="ascii").strip()
    if len(salt) != 16 or any(c not in SALT_CHARS for c in salt):
        raise ValueError("Invalid local password salt in .yocto-secrets/salt.")

    try:
        result = subprocess.run(
            ["mkpasswd", "--method=sha512crypt", "--rounds=200000", "--salt", salt, "--stdin"],
            input=password.encode("utf-8") + b"\n", stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=environment, check=True,
        )
    except FileNotFoundError:
        raise ValueError("Install the host mkpasswd command (provided by whois on Debian/Ubuntu).") from None
    except subprocess.CalledProcessError:
        raise ValueError("mkpasswd could not generate a SHA-512 crypt password hash.") from None

    encrypted = result.stdout.decode("ascii").strip()
    if not re.fullmatch(r"\$6\$rounds=200000\$[./0-9A-Za-z]{16}\$[./0-9A-Za-z]{86}", encrypted):
        raise ValueError("mkpasswd returned an unexpected password hash format.")
    path = private / ("password-" + sha256(encrypted.encode("ascii")).hexdigest())
    if not path.exists():
        write_private_once(path, (encrypted + "\n").encode("ascii"))
    return path


def stage_ssh_public_key(configured_path, environment):
    path = Path(configured_path)
    if not path.is_absolute():
        raise ValueError("MAC_SSH_PUBLIC_KEY_FILE must be an absolute path to an OpenSSH public key.")

    # Check the opened file, and avoid blocking on special files such as FIFOs.
    limit = 64 * 1024
    try:
        with open(path, "rb", opener=lambda name, flags: os.open(name, flags | os.O_NONBLOCK)) as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("MAC_SSH_PUBLIC_KEY_FILE must point to a regular file.")
            key = source.read(limit + 1)
    except OSError as error:
        raise ValueError(f"Cannot read MAC_SSH_PUBLIC_KEY_FILE: {error}") from None

    invalid_key = "MAC_SSH_PUBLIC_KEY_FILE must contain one valid OpenSSH public key line without options. Use the .pub file."
    if len(key) > limit:
        raise ValueError(invalid_key)
    line = key.removesuffix(b"\n").removesuffix(b"\r")
    fields = re.fullmatch(
        rb"[ \t]*([A-Za-z0-9@._+-]+)[ \t]+([A-Za-z0-9+/]+={0,2})(?:[ \t]+[^\x00-\x08\x0a-\x1f\x7f]*)?", line
    )
    if fields is None:
        raise ValueError(invalid_key)
    try:
        blob = base64.b64decode(fields[2], validate=True)
    except binascii.Error:
        raise ValueError(invalid_key) from None
    type_size = int.from_bytes(blob[:4], "big")
    if type_size != len(fields[1]) or blob[4:4 + type_size] != fields[1]:
        raise ValueError(invalid_key)

    try:
        check = subprocess.run(["ssh-keygen", "-l", "-f", "-"], input=key, env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise ValueError("Install the host ssh-keygen command (from openssh-client on Debian/Ubuntu).") from None
    if check.returncode:
        raise ValueError(invalid_key)

    staged = private_input_dir() / ("ssh-" + sha256(key).hexdigest() + ".pub")
    if not staged.exists():
        write_private_once(staged, key)
    if staged.is_symlink() or not staged.is_file() or staged.read_bytes() != key:
        raise ValueError("The staged SSH public key is invalid. Remove the affected .yocto-secrets/ssh-*.pub file and retry.")
    return staged


def base_url(address, port):
    host = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{host}:{port}"


def run_kas(args, username, password, key_path, url):
    environment = os.environ.copy()
    environment.pop("MAC_PASSWORD", None)
    environment.pop("MAC_PASSWORD_HASH_FILE", None)
    environment.pop("MAC_SSH_PUBLIC_KEY_FILE", None)
    environment.pop("MAC_SSH_PUBLIC_KEY_STAGED", None)
    environment.update(MAC_USERNAME=username, OPKG_SERVER_URL=url)
    if args.action != "index":
        environment["MAC_SSH_PUBLIC_KEY_STAGED"] = str(stage_ssh_public_key(key_path, environment))
        environment["MAC_PASSWORD_HASH_FILE"] = str(password_file(password, environment))

    if args.action == "shell":
        command = ["kas", "shell", KAS_CONFIG]
        if args.command is not None:
            command.extend(("-c", args.command))
    else:
        command = ["kas", "build", KAS_CONFIG]
        targets = ["package-index"] if args.action == "index" else args.targets or IMAGES
        for target in targets:
            command.extend(("--target", target))

    os.chdir(PROJECT)
    os.execvpe(command[0], command, environment)


def serve_packages(directory, address, port):
    if directory is None:
        build_dir = Path(os.environ.get("KAS_BUILD_DIR", "build"))
        directory = PROJECT / build_dir / "tmp/deploy/ipk"
    if not directory.is_dir():
        raise ValueError(f"IPK deployment directory does not exist: {directory}. Build packages first.")
    directory = directory.resolve()

    class PackageServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET

    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    try:
        with PackageServer((str(address), port), handler) as server:
            print(f"Serving Yocto IPKs from {directory}", flush=True)
            print(f"Package server: {base_url(address, port)} (Ctrl+C to stop)", flush=True)
            if not any(directory.glob("*/Packages.gz")):
                print("No compressed indexes found. Run scripts/yocto.py index after building packages.", file=sys.stderr)
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nPackage server stopped.")
    except OSError as error:
        raise ValueError(f"Cannot serve {base_url(address, port)}: {error}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build", help="Build both Mac images or the named image")
    build.add_argument("targets", nargs="*", metavar="IMAGE")
    actions.add_parser("index", help="Regenerate indexes for existing IPKs")
    shell = actions.add_parser("shell", help="Open a configured kas shell")
    shell.add_argument("-c", "--command")
    serve = actions.add_parser("serve", help="Serve the Yocto IPK deployment directory")
    serve.add_argument("--directory", type=Path, help="Override the default deployment directory")
    args = parser.parse_args()
    if args.action == "build" and any(target not in IMAGES for target in args.targets):
        parser.error("IMAGE must be mac-image or mac-image-installer.")

    try:
        username, password, key_path, address, port = read_config(args.action in {"build", "shell"})
        if args.action == "serve":
            serve_packages(args.directory, address, port)
        else:
            run_kas(args, username, password, key_path, base_url(address, port))
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
