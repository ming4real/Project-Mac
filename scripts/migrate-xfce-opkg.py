#!/usr/bin/env python3
"""Prepare and apply an additive OPKG migration for MacBookPro14,3."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = "mac-image-macbookpro14-3.rootfs.manifest"
STATUS = Path("/var/lib/opkg/status")
STATE = Path("/var/lib/mac-xfce-migration.json")
MODEL = Path("/sys/class/dmi/id/product_name")
PROFILE = Path("/etc/profile.d")
LEGACY = (PROFILE / "labwc-autostart.sh", PROFILE / "weston-socket.sh")
XFCE = PROFILE / "xfce-autostart.sh"
UNITS = ("weston.socket", "weston.service")
PROTECTED = re.compile(
    r"^(?:kernel|linux|grub|systemd|openssh|opkg|packagegroup|base-files|base-passwd|"
    r"glibc|mac-debug-user|networkmanager)(?:-|$)"
)
NAME = r"[a-z0-9][a-z0-9+.-]*"
INSTALL = re.compile(rf"Installing ({NAME}) \(([^ )]+)\) on root\.?")
ENV = {key: value for key, value in os.environ.items()
       if key not in ("OFFLINE_ROOT", "OPKG_CONF_DIR", "OPKG_TMP_DIR")}
ENV.update(LC_ALL="C", PATH="/usr/sbin:/usr/bin:/sbin:/bin")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args):
    result = subprocess.run(args, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[-1]} failed ({result.returncode})\n{result.stdout}")
    return result.stdout


def paragraphs(text):
    for stanza in text.strip().split("\n\n"):
        yield stanza, dict(line.split(": ", 1) for line in stanza.splitlines()
                           if not line.startswith((" ", "\t")) and ": " in line)


def manifest(path):
    return {name: (arch, version) for name, arch, version in
            (line.split() for line in path.read_text().splitlines())}


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(build, output):
    desired_path = build / "tmp/deploy/images/macbookpro14-3" / MANIFEST
    desired = manifest(desired_path)
    baseline = manifest(build / "rollback-labwc" / MANIFEST)
    candidates = desired.keys() - baseline.keys()
    require(not any(PROTECTED.match(name) for name in candidates),
            "The image delta contains a protected system package.")
    recipe = PROJECT / "layers/project/meta-mac-distro/recipes-images/images/mac-image.bb"
    pkgdata = build / "tmp/pkgdata/macbookpro14-3/runtime"
    direct = re.findall(r'^IMAGE_INSTALL:append\s*=\s*"\s+([^\s"]+)"', recipe.read_text(), re.M)
    roots = set()
    for name in direct:
        data = (pkgdata / name).read_text()
        packaged = re.search(rf"^PKG:{re.escape(name)}: (\S+)$", data, re.M).group(1)
        if packaged in candidates:
            roots.add(packaged)
    require({"xfce-autostart", "xfce4-session", "xserver-xorg", "thunar"} <= roots,
            "The build is missing expected desktop packages.")

    rootfs = build / "tmp/work/macbookpro14_3-oe-linux/mac-image/1.0/rootfs"
    sizes = {record["Package"]: int(record.get("Installed-Size", 0))
             for _, record in paragraphs((rootfs / STATUS.relative_to("/")).read_text())
             if "Package" in record}
    require(not output.exists(), f"Choose a new bundle directory. Already exists: {output}")
    with tempfile.TemporaryDirectory(prefix=".xfce-bundle-", dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        found = {}
        for arch in sorted({desired[name][0] for name in candidates}):
            source = build / "tmp/deploy/ipk" / arch
            target = staging / arch
            target.mkdir()
            index = []
            for stanza, record in paragraphs((source / "Packages").read_text()):
                name = record.get("Package")
                if name not in candidates or (arch, record.get("Version")) != desired[name]:
                    continue
                filename = record["Filename"]
                require(re.fullmatch(r"[A-Za-z0-9_+.%:~-]+\.ipk", filename),
                        f"Unexpected IPK filename: {filename}")
                require(name not in found, f"Duplicate feed candidate: {name}")
                ipk = source / filename
                require(checksum(ipk) == record["SHA256sum"], f"Feed checksum mismatch: {ipk}")
                shutil.copyfile(ipk, target / filename)
                index.append(stanza)
                found[name] = {"version": record["Version"], "arch": arch,
                               "bytes": sizes[name], "archive": ipk.stat().st_size}
            (target / "Packages").write_text("\n\n".join(index) + "\n")
        require(candidates == found.keys(), f"Missing indexed IPKs: {sorted(candidates - found.keys())}")
        shutil.copyfile(desired_path, staging / MANIFEST)
        (staging / "migration.json").write_text(json.dumps(
            {"roots": sorted(roots), "packages": found}, indent=2) + "\n")
        staging.rename(output)
    print(f"Prepared {output} with {len(roots)} desktop packages and {len(found)} feed candidates.")


def installed(path):
    packages = {}
    for _, record in paragraphs(path.read_text()):
        status = record.get("Status", "").split()
        if not status:
            continue
        name = record["Package"]
        require(len(status) == 3 and status[-1] in ("installed", "not-installed", "config-files")
                and "reinstreq" not in status[1],
                f"Resolve the unfinished OPKG state for {name} before migrating.")
        if status[-1] == "installed":
            packages[name] = record["Version"]
    return packages


def plan(bundle, status, opkg, work):
    metadata = json.loads((bundle / "migration.json").read_text())
    desired = manifest(bundle / MANIFEST)
    status_digest = checksum(status)
    before = installed(status)
    candidates = metadata["packages"]
    roots = [name for name in metadata["roots"] if name not in before]
    require({"labwc", "labwc-autostart", "weston-init"} <= before.keys(),
            "The legacy desktop and startup packages must be installed.")
    require(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(bundle)), "Use a bundle path without spaces or special characters.")
    architectures = run(opkg, "print-architecture")
    arch_lines = re.findall(r"^arch [A-Za-z0-9_-]+ [0-9]+$", architectures, re.M)
    require(arch_lines, "No configured OPKG architectures found.")
    config = work / "opkg.conf"
    # A separate config and local feed keep the host's existing feed settings intact.
    config.write_text("\n".join([
        "dest root /", f"option status_file {STATUS}",
        f"option lists_dir {work}/lists", f"option cache_dir {work}/cache",
        *arch_lines,
        *(f"src migration-{arch} file://{bundle}/{arch}"
          for arch in sorted({item["arch"] for item in candidates.values()})),
        "",
    ]))
    command = [opkg, "-f", str(config), "--add-exclude", "weston-init"]
    missing = desired.keys() - before.keys()
    print(f"Image comparison: {len(missing)} missing, "
          f"{len(before.keys() - desired.keys())} locally installed outside the image, "
          f"{sum(before[name] != desired[name][1] for name in before.keys() & desired.keys())} "
          "installed at different versions.")
    if missing - candidates.keys():
        print("Missing packages outside the desktop migration:", ", ".join(sorted(missing - candidates.keys())))
    planned = {}
    if roots:
        run(*command, "update")
        output = run(*command, "--noaction", "install", *roots)
        print(output, end="")
        for line in output.splitlines():
            if not line or line == "No packages installed or removed.":
                continue
            match = INSTALL.fullmatch(line)
            require(match, f"Only new package installs are allowed. OPKG reported: {line}")
            name = match[1]
            require(name not in before and name in candidates and not PROTECTED.match(name),
                    f"Unexpected package action: {line}")
            # libsolv prints the upstream version without the epoch or recipe revision.
            planned[name] = candidates[name]["version"]
        require(set(roots) <= planned.keys(), "OPKG did not plan all missing desktop packages.")
    bytes_needed = sum(candidates[name]["bytes"] + candidates[name]["archive"] for name in planned)
    require(shutil.disk_usage("/").free >= bytes_needed, "Insufficient free space for the planned packages.")
    require(checksum(status) == status_digest, "The OPKG status changed during preflight.")
    return command, roots, before, planned, status_digest


def present(path):
    return path.exists() or path.is_symlink()


def parked(path):
    return path.with_name(path.name + ".mac-xfce-disabled")


def hook(path, disable):
    saved = parked(path)
    source, destination = (path, saved) if disable else (saved, path)
    require(not (present(source) and present(destination)), f"Conflicting copies of {path}.")
    if present(source):
        require(stat.S_ISREG(source.lstat().st_mode), f"Expected a regular hook: {source}")
        source.rename(destination)


def quiet_console():
    # Refuse even a text login on tty1 while its login mechanism is being switched.
    for row in run("loginctl", "list-sessions", "--no-legend", "--no-pager").splitlines():
        tty = run("loginctl", "show-session", row.split()[0], "-p", "TTY", "--value").strip()
        require(tty != "tty1", "Log out of tty1 and run the migration from tty2 or SSH.")
    for process in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = process.read_text().strip()
        except (FileNotFoundError, ProcessLookupError):
            continue
        require(name not in ("labwc", "Xorg", "startx"),
                f"End the active {name} session before switching desktops.")


def unit_override(unit):
    return Path("/etc/systemd/system") / unit


def rollback():
    require(STATE.is_file(), f"No saved startup state at {STATE}.")
    state = json.loads(STATE.read_text())
    require(set(state) == set(UNITS), f"Invalid startup state in {STATE}.")
    hook(XFCE, disable=True)
    for unit in UNITS:
        path = unit_override(unit)
        if present(path):
            require(path.is_symlink() and os.readlink(path) == "/dev/null",
                    f"Unexpected systemd override: {path}")
            run("systemctl", "unmask", unit)
    for path in LEGACY:
        hook(path, disable=False)
        require(path.is_file(), f"Could not restore {path}.")
    for unit in UNITS:
        if state[unit]:
            run("systemctl", "start", unit)
    STATE.unlink()
    print("Legacy startup restored. Xfce packages remain installed with their login hook disabled.")


def apply(command, roots, before, planned, status_digest):
    quiet_console()
    require(not present(STATE), f"Saved state exists at {STATE}. Use rollback before applying again.")
    for path in LEGACY:
        require(path.is_file() and not path.is_symlink() and not present(parked(path)),
                f"Expected an active legacy hook without a parked copy: {path}")
    require(not present(XFCE), f"An active Xfce hook already exists: {XFCE}")
    require(present(parked(XFCE)) == ("xfce-autostart" in before),
            "The Xfce startup package and its parked hook are out of sync.")
    for unit in UNITS:
        override = unit_override(unit)
        require(not present(override) and not present(Path("/run/systemd/system") / unit),
                f"Weston has an existing unit override or mask: {unit}")
    state = {}
    for unit in UNITS:
        active = run("systemctl", "show", unit, "-p", "ActiveState", "--value").strip()
        require(active in ("active", "inactive"), f"Unexpected Weston state for {unit}: {active}")
        state[unit] = active == "active"
    with STATE.open("x") as stream:
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        for path in LEGACY:
            hook(path, disable=True)
        run("systemctl", "mask", "--now", *UNITS)
        require(checksum(STATUS) == status_digest, "The OPKG status changed after preflight.")
        if roots:
            print(run(*command, "install", *roots), end="")
        after = installed(STATUS)
        require(after == (before | planned), "The resulting installed package set differs from the plan.")
        hook(XFCE, disable=False)
        require(XFCE.is_file(), "Xfce login hook is missing.")
        username = re.search(r'= "([a-z_][a-z0-9_-]*)" \] &&', XFCE.read_text())
        require(username and pwd.getpwnam(username[1]).pw_uid >= 1000,
                "The Xfce login hook does not target a local unprivileged account.")
    except (Exception, KeyboardInterrupt):
        try:
            rollback()
        except Exception as error:
            print(f"Automatic startup rollback failed. Fix the error and rerun rollback: {error}",
                  flush=True)
        raise
    print(f"Xfce startup enabled on the next tty1 login. Rollback state: {STATE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    stage = subparsers.add_parser("prepare", help="Build a local OPKG bundle on the build host")
    stage.add_argument("output", type=Path)
    stage.add_argument("--build-dir", type=Path, default=PROJECT / "build")
    for mode in ("plan", "apply"):
        subparsers.add_parser(mode, help=f"{mode.capitalize()} using a copied bundle on the MacBook").add_argument(
            "bundle", type=Path)
    subparsers.add_parser("rollback", help="Restore labwc and Weston startup on the MacBook")
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.build_dir.resolve(), args.output.resolve())
        return
    require(os.geteuid() == 0, "Run the target commands with sudo.")
    require(MODEL.read_text().strip() == "MacBookPro14,3", "Unexpected MacBook model.")
    os.umask(0o077)
    with open("/run/lock/mac-xfce-migration.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.mode == "rollback":
            quiet_console()
            rollback()
            return
        opkg = shutil.which("opkg", path=ENV["PATH"])
        require(opkg and run(opkg, "--version").startswith("opkg version 0.9.0 (libsolv "),
                "Expected the image's OPKG 0.9.0 with libsolv.")
        with tempfile.TemporaryDirectory(prefix="mac-xfce-") as directory:
            if args.mode == "apply":
                require(not present(STATE), "An earlier migration is recorded. Run rollback first.")
            transaction = plan(args.bundle.resolve(), STATUS, opkg, Path(directory))
            if args.mode == "apply":
                apply(*transaction)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        raise SystemExit(f"Migration stopped: {error}") from None
