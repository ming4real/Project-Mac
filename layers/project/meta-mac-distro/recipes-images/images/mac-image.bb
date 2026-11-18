SUMMARY = "Linux image for Intel Apple Mac computers"
DESCRIPTION = "A Yocto Project Linux distribution for repurposed Intel Macs"
LICENSE = "MIT"

require recipes-core/images/core-image-minimal.bb

IMAGE_FEATURES += "ssh-server-openssh"
IMAGE_FEATURES += "package-management"

IMAGE_INSTALL:append = " kernel-modules"
IMAGE_INSTALL:append = " linux-firmware"
IMAGE_INSTALL:append = " mac-debug-user"
IMAGE_INSTALL:append = " sudo"
IMAGE_INSTALL:append = " systemd-conf"
IMAGE_INSTALL:append = " systemd-networkd"
IMAGE_INSTALL:append = " vim"

