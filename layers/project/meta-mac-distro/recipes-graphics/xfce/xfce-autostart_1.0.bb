SUMMARY = "Start Xfce after the Mac workstation user's console login"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COREBASE}/meta/COPYING.MIT;md5=3da9cfbcb788c80a0384361b4de20420"

SRC_URI = "file://xfce-autostart.sh file://xfce-x11-session"
S = "${UNPACKDIR}"
PACKAGE_ARCH = "${MACHINE_ARCH}"

MAC_USERNAME ?= "ming"
RDEPENDS:${PN} = "dbus-tools xfce4-session xinit xauth xserver-xorg"

do_install() {
    install -d ${D}${sysconfdir}/profile.d
    sed -e 's|@MAC_USERNAME@|${MAC_USERNAME}|g' -e 's|@BINDIR@|${bindir}|g' \
        -e 's|@LIBEXECDIR@|${libexecdir}|g' \
        ${S}/xfce-autostart.sh > ${D}${sysconfdir}/profile.d/xfce-autostart.sh
    chmod 0644 ${D}${sysconfdir}/profile.d/xfce-autostart.sh

    install -Dm0755 ${S}/xfce-x11-session ${D}${libexecdir}/xfce-x11-session
}

FILES:${PN} = "${sysconfdir}/profile.d/xfce-autostart.sh ${libexecdir}/xfce-x11-session"
