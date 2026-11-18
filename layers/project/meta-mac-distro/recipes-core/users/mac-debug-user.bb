SUMMARY = "Key-only remote debugging account for the Mac image"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COREBASE}/meta/COPYING.MIT;md5=3da9cfbcb788c80a0384361b4de20420"

SRC_URI = " \
    file://ming.pub \
    file://90-ming \
"
S = "${UNPACKDIR}"

inherit useradd

USERADD_PACKAGES = "${PN}"
# An impossible password, not an empty password or a leading '!' account
# lock: OpenSSH without PAM rejects locked accounts even for public keys.
USERADD_PARAM:${PN} = "--create-home --home-dir /home/ming --shell /bin/sh --user-group --password '*NP*' ming"

do_install() {
    install -d -m 0750 ${D}/home/ming
    install -d -m 0700 ${D}/home/ming/.ssh
    install -m 0600 ${UNPACKDIR}/ming.pub ${D}/home/ming/.ssh/authorized_keys
    chown -R ming:ming ${D}/home/ming

    install -d -m 0750 ${D}${sysconfdir}/sudoers.d
    install -m 0440 ${UNPACKDIR}/90-ming ${D}${sysconfdir}/sudoers.d/90-ming
}


FILES:${PN} = " \
    /home/ming \
    ${sysconfdir}/sudoers.d/90-ming \
"
