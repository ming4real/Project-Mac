SUMMARY = "Linux image for Intel Apple Mac computers"
DESCRIPTION = "A Yocto Project Linux distribution for repurposed Intel Macs"
LICENSE = "MIT"

require recipes-core/images/core-image-minimal.bb

IMAGE_FEATURES += "ssh-server-openssh"

IMAGE_INSTALL:append = " \
    kernel-modules \
    linux-firmware \
"