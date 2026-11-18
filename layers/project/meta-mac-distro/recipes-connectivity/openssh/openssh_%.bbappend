FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://00-mac-key-only.conf"

do_install:append() {
    install -D -m 0644 ${UNPACKDIR}/00-mac-key-only.conf ${D}${sysconfdir}/ssh/sshd_config.d/00-mac-key-only.conf
}

FILES:${PN}-sshd += "${sysconfdir}/ssh/sshd_config.d/00-mac-key-only.conf"
CONFFILES:${PN}-sshd += "${sysconfdir}/ssh/sshd_config.d/00-mac-key-only.conf"
