SUMMARY = "Apple iBridge Touch Bar and ambient light sensor drivers"
DESCRIPTION = "Out-of-tree Linux drivers for the Apple iBridge found in MacBook Pro systems"
HOMEPAGE = "https://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver"

LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://apple-ibridge.c;beginline=1;endline=1;md5=50d2ba0afecd20f74c12a4bdbcfcfe61"

SRC_URI = " \
    git://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver.git;protocol=https;branch=touchbar-driver-hid-driver \
    file://0001-fix-tb-touch-declaration-order.patch \
    file://0002-defer-usb-configuration-switch.patch \
"
SRCREV = "ecfadc37538d1995ddd2383dd83a1be82fdfdf23"

PV = "1.0+git"

inherit module

EXTRA_OEMAKE += "KDIR=${STAGING_KERNEL_DIR}"

RPROVIDES:${PN} += "kernel-module-apple-ibridge"

do_install() {
    install -d ${D}${nonarch_base_libdir}/modules/${KERNEL_VERSION}/extra

    install -m 0644 ${B}/apple-ibridge.ko \
        ${D}${nonarch_base_libdir}/modules/${KERNEL_VERSION}/extra/

    install -m 0644 ${B}/apple-ib-tb.ko \
        ${D}${nonarch_base_libdir}/modules/${KERNEL_VERSION}/extra/

    install -m 0644 ${B}/apple-ib-als.ko \
        ${D}${nonarch_base_libdir}/modules/${KERNEL_VERSION}/extra/
}