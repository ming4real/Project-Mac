SUMMARY = "Linux image for the MacBook Pro 14,3 internal SSD"
DESCRIPTION = "A Yocto Project Linux distribution for repurposed Intel Macs"
LICENSE = "MIT"

require mac-image-common.inc

IMAGE_FEATURES += "package-management"
PACKAGE_FEED_URIS = "${OPKG_SERVER_URL}"
PACKAGE_FEED_ARCHS = "all ${TUNE_PKGARCH} ${MACHINE_ARCH}"

IMAGE_INSTALL:append = " packagegroup-mac-development"
IMAGE_INSTALL:append = " weston"
IMAGE_INSTALL:append = " weston-init"
IMAGE_INSTALL:append = " labwc"
IMAGE_INSTALL:append = " wlr-randr"
IMAGE_INSTALL:append = " labwc-autostart"
IMAGE_INSTALL:append = " flatpak"
IMAGE_INSTALL:append = " foot"
IMAGE_INSTALL:append = " fuzzel"
IMAGE_INSTALL:append = " waybar"
IMAGE_INSTALL:append = " pavucontrol"

