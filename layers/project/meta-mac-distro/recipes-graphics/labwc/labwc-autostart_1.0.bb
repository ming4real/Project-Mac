SUMMARY = "Automatically start labwc after local console login"
DESCRIPTION = "Starts labwc for user ming after login on tty1."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://labwc-autostart.sh \
    file://autostart \
    file://rc.xml \
"

inherit allarch

RDEPENDS:${PN} = "labwc"

do_install() {
    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${UNPACKDIR}/labwc-autostart.sh \
        ${D}${sysconfdir}/profile.d/labwc-autostart.sh

    install -d ${D}${sysconfdir}/xdg/labwc
    install -m 0755 ${UNPACKDIR}/autostart \
        ${D}${sysconfdir}/xdg/labwc/autostart

    install -m 0644 ${UNPACKDIR}/rc.xml \
        ${D}${sysconfdir}/xdg/labwc/rc.xml
}

FILES:${PN} = " \
    ${sysconfdir}/profile.d/labwc-autostart.sh \
    ${sysconfdir}/xdg/labwc/autostart \
    ${sysconfdir}/xdg/labwc/rc.xml \
"
