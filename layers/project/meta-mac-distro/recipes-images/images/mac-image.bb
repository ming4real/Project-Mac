SUMMARY = "Linux image for the MacBook Pro 14,3 internal SSD"
DESCRIPTION = "A Yocto Project Linux distribution for repurposed Intel Macs"
LICENSE = "MIT"

require mac-image-common.inc

IMAGE_FEATURES += "package-management"
PACKAGE_FEED_URIS = "${OPKG_SERVER_URL}"
PACKAGE_FEED_ARCHS = "all ${TUNE_PKGARCH} ${MACHINE_ARCH}"
