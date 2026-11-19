require recipes-core/images/core-image-minimal.bb

IMAGE_FEATURES += "ssh-server-openssh"

MAC_PASSWORD_HASH_FILE ?= ""
OPKG_SERVER_URL ?= ""

python mac_require_project_config() {
    import os
    import re

    username = d.getVar('MAC_USERNAME') or ''
    hash_file = d.getVar('MAC_PASSWORD_HASH_FILE')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', username) or username in ('root', 'nobody'):
        bb.fatal('Invalid or missing MAC_USERNAME. Configure .env and run scripts/yocto.py build.')
    if not hash_file or not os.path.isfile(hash_file) or not d.getVar('OPKG_SERVER_URL'):
        bb.fatal('Missing project build configuration. Configure .env and run scripts/yocto.py build.')
}

python mac_set_initial_password() {
    import pathlib
    import re

    username = d.getVar('MAC_USERNAME')
    passwd_file = pathlib.Path(d.getVar('MAC_PASSWORD_HASH_FILE'))
    encrypted = passwd_file.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'\$6\$rounds=200000\$[./0-9A-Za-z]{16}\$[./0-9A-Za-z]{86}', encrypted):
        bb.fatal('Invalid initial password hash. Run scripts/yocto.py build to regenerate it.')

    etc = pathlib.Path(d.getVar('IMAGE_ROOTFS') + d.getVar('sysconfdir'))
    entries = [line.split(':') for line in (etc / 'passwd').read_text().splitlines()]
    accounts = [entry for entry in entries if entry[0] == username]
    if (len(accounts) != 1 or not 1000 <= int(accounts[0][2]) < 65534 or
            accounts[0][5:] != ['/home/' + username, '/bin/sh']):
        bb.fatal('Configured account collides with an existing system account: %s' % username)

    # Keep the permissions and ownership from shadow-native's rootfs setup.
    with (etc / 'shadow').open('r+', encoding='utf-8') as shadow:
        entries = [line.split(':') for line in shadow.readlines()]
        accounts = [entry for entry in entries if entry[0] == username]
        if len(accounts) != 1 or accounts[0][1] != '*NP*':
            bb.fatal('Cannot identify the newly provisioned shadow entry for %s' % username)
        accounts[0][1] = encrypted
        shadow.seek(0)
        shadow.writelines(':'.join(entry) for entry in entries)
        shadow.truncate()
}

do_rootfs[prefuncs] += "mac_require_project_config"
do_rootfs[file-checksums] += "${@d.getVar('MAC_PASSWORD_HASH_FILE') + ':True' if d.getVar('MAC_PASSWORD_HASH_FILE') else ''}"
ROOTFS_POSTPROCESS_COMMAND += "mac_set_initial_password;"

IMAGE_INSTALL:append = " \
    kernel-modules \
    linux-firmware \
    mac-debug-user \
    sudo \
    systemd-conf \
    systemd-networkd \
    vim \
"
