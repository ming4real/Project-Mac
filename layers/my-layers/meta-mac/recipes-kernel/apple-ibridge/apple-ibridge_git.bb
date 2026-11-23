SUMMARY = "Apple iBridge Touch Bar and ambient light sensor drivers"
DESCRIPTION = "Out-of-tree Linux drivers for the Apple iBridge found in MacBook Pro systems"
HOMEPAGE = "https://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver"

LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://apple-ibridge.c;beginline=1;endline=1;md5=50d2ba0afecd20f74c12a4bdbcfcfe61"

SRC_URI = " \
    git://github.com/F13-Kr1pt0n/macbook-pro-touchbar-driver.git;protocol=https;branch=touchbar-driver-hid-driver \
    file://0001-fix-tb-touch-declaration-order.patch \
    file://0002-defer-usb-configuration-switch.patch \
    file://0003-log-touch-bar-report-matches.patch \
    file://0004-remove-unused-touch-bar-multitouch-device.patch \
"
SRCREV = "ecfadc37538d1995ddd2383dd83a1be82fdfdf23"

PV = "1.0+git"
PR = "r2"

inherit module

# On this T1, keyboard mode exposes the firmware key strip's HID reports.
KERNEL_MODULE_PROBECONF:append:macbookpro14-3 = " apple-ibridge apple-ib-tb"
module_conf_apple-ibridge:macbookpro14-3 = "options apple_ibridge tb_mode_param=keyboard"
module_conf_apple-ib-tb:macbookpro14-3 = "options apple_ib_tb fnmode=0"

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
