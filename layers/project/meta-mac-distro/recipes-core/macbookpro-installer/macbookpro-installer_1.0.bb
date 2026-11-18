SUMMARY = "Install a Yocto WIC image on the MacBook Pro 14,3 internal SSD"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://install-macbookpro14-3.sh"
S = "${UNPACKDIR}"

COMPATIBLE_MACHINE = "^macbookpro14-3$"

RDEPENDS:${PN} = " \
    bash \
    coreutils \
    dosfstools \
    e2fsprogs-mke2fs \
    findutils \
    gawk \
    udev \
    util-linux-blockdev \
    util-linux-findmnt \
    util-linux-flock \
    util-linux-losetup \
    util-linux-lsblk \
    util-linux-mount \
    util-linux-sfdisk \
    util-linux-swapon \
    util-linux-umount \
    zstd \
"

do_install() {
    install -d "${D}${sbindir}"
    install -m 0755 "${UNPACKDIR}/install-macbookpro14-3.sh" \
        "${D}${sbindir}/install-macbookpro14-3"
}
